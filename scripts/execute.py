#!/usr/bin/env python3
"""
Harness Step Executor — phase 내 step을 순차 실행하고 자가 교정한다.

Usage:
    python3 scripts/execute.py <phase-dir> [--push]
"""

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import types
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import chat_view

ROOT = Path(__file__).resolve().parent.parent


@contextlib.contextmanager
def progress_indicator(label: str):
    """터미널 진행 표시기. with 문으로 사용하며 .elapsed 로 경과 시간을 읽는다."""
    frames = "◐◓◑◒"
    stop = threading.Event()
    t0 = time.monotonic()

    def _animate():
        idx = 0
        while not stop.wait(0.12):
            sec = int(time.monotonic() - t0)
            sys.stderr.write(f"\r{frames[idx % len(frames)]} {label} [{sec}s]")
            sys.stderr.flush()
            idx += 1
        sys.stderr.write("\r" + " " * (len(label) + 20) + "\r")
        sys.stderr.flush()

    th = threading.Thread(target=_animate, daemon=True)
    th.start()
    info = types.SimpleNamespace(elapsed=0.0)
    try:
        yield info
    finally:
        stop.set()
        th.join()
        info.elapsed = time.monotonic() - t0


class StepExecutor:
    """Phase 디렉토리 안의 step들을 순차 실행하는 하네스."""

    INNER_ROUNDS = 3        # 팀 리드의 내부 Max↔Joy 개선 루프 상한 (프리앰블에 주입)
    OUTER_ATTEMPTS = 2      # execute.py 바깥 재시도(초기 1 + 재시작 1) — 프로세스 실패 복구용
    TIMEOUT_SECONDS = 3600  # 한 step 세션(팀 루프 포함)의 최대 실행 시간(초)
    FEAT_MSG = "feat({phase}): step {num} — {name}"
    WIP_MSG = "wip({phase}): step {num} FAILED — {name}"  # 실패 종료 step의 코드 — feat로 위장하지 않는다
    CHORE_MSG = "chore({phase}): step {num} output"
    TZ = timezone(timedelta(hours=9))
    STALE_AFTER_DAYS = 14  # rules.md가 이 일수 이상 리뷰되지 않으면 경고
    VALID_STATUSES = {"pending", "running", "completed", "error", "blocked"}
    _SAFE_PHASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")  # git 브랜치명 안전 슬러그
    _PLACEHOLDER_RE = re.compile(r"\{[^}\n]{1,80}\}")          # 템플릿 미작성 칸 {...}

    def __init__(self, phase_dir_name: str, *, auto_push: bool = False, quiet: bool = False):
        self._root = str(ROOT)
        self._phases_dir = ROOT / "phases"
        self._phase_dir = self._phases_dir / phase_dir_name
        self._phase_dir_name = phase_dir_name
        self._top_index_file = self._phases_dir / "index.json"
        self._auto_push = auto_push
        self._quiet = quiet  # True면 인라인 대화 표시를 끈다 (상시 chat.py가 전담)
        self._lock_file = ROOT / ".harness.lock"
        self._have_lock = False

        if not self._phase_dir.is_dir():
            print(f"ERROR: {self._phase_dir} not found")
            sys.exit(1)

        self._index_file = self._phase_dir / "index.json"
        if not self._index_file.exists():
            print(f"ERROR: {self._index_file} not found")
            sys.exit(1)

        idx = self._load_index_validated()
        self._project = idx.get("project", "project")
        self._phase_name = idx.get("phase", phase_dir_name)
        self._total = len(idx["steps"])

    @staticmethod
    def _preflight():
        """claude CLI가 PATH에 있는지 부팅 시 점검한다 (복제 환경의 FileNotFoundError 방지)."""
        if shutil.which("claude") is None:
            print("ERROR: 'claude' CLI를 PATH에서 찾을 수 없습니다. "
                  "Claude Code가 설치되어 있어야 하네스가 헤드리스 세션을 띄울 수 있습니다.")
            sys.exit(1)

    def run(self):
        self._preflight()
        self._acquire_lock()
        try:
            self._print_header()
            self._check_blockers()
            self._check_rules_freshness()
            self._checkout_branch()
            guardrails = self._load_guardrails()
            self._ensure_created_at()
            self._execute_all_steps(guardrails)
            self._finalize()
        finally:
            self._release_lock()

    # --- 동시 실행 락 (공유 워킹트리·top-index 손상 방지) ---

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True   # 존재하나 다른 유저 — 살아있다고 본다
        except OSError:
            return False
        return True

    @staticmethod
    def _read_lock(lock: Path) -> dict:
        try:
            return json.loads(lock.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _acquire_lock(self):
        """원자적 lockfile로 동시 실행을 막는다. 살아있는 보유자가 있으면 중단,
        죽은 프로세스가 남긴 stale lock이면 정리 후 인수한다."""
        lock = self._lock_file
        for _ in range(2):  # 1회는 stale 정리 후 재시도
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                holder = self._read_lock(lock)
                pid = holder.get("pid")
                if isinstance(pid, int) and self._pid_alive(pid):
                    self._fatal(
                        f"다른 하네스가 이미 실행 중입니다 (pid {pid}, phase "
                        f"'{holder.get('phase')}', {holder.get('started_at')}). "
                        f"동시 실행은 공유 워킹트리를 손상시킵니다 — 끝나길 기다리거나, "
                        f"죽은 프로세스라면 {lock} 를 지우세요.")
                try:
                    lock.unlink()   # stale → 정리 후 재시도
                except OSError:
                    pass
                continue
            else:
                with os.fdopen(fd, "w") as f:
                    json.dump({"pid": os.getpid(), "phase": self._phase_dir_name,
                               "started_at": self._stamp()}, f)
                self._have_lock = True
                return
        self._fatal(f"락을 획득하지 못했습니다: {lock}")

    def _release_lock(self):
        if self._have_lock:
            try:
                self._lock_file.unlink()
            except OSError:
                pass
            self._have_lock = False

    # --- timestamps ---

    def _stamp(self) -> str:
        return datetime.now(self.TZ).strftime("%Y-%m-%dT%H:%M:%S%z")

    # --- JSON I/O ---

    @staticmethod
    def _read_json(p: Path) -> dict:
        return json.loads(p.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(p: Path, data: dict):
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _fatal(self, msg: str):
        print(f"ERROR: {msg}")
        sys.exit(1)

    def _load_index_validated(self) -> dict:
        """index.json을 읽고 최소 스키마를 검증한다 (손편집 권장 파일 → 친절한 에러).

        위반 시 raw 트레이스백 대신 어느 필드가 틀렸는지 한국어로 알리고 종료한다.
        검증: 객체 · 비어있지 않은 steps 배열 · 각 step의 step(정수·유일)·name·status(enum) · phase 슬러그.
        """
        try:
            idx = json.loads(self._index_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            self._fatal(f"{self._index_file} 가 올바른 JSON이 아닙니다: {e}")
        if not isinstance(idx, dict):
            self._fatal("index.json 최상위는 JSON 객체여야 합니다.")
        steps = idx.get("steps")
        if not isinstance(steps, list) or not steps:
            self._fatal('index.json에 비어있지 않은 "steps" 배열이 필요합니다.')
        seen = set()
        for i, s in enumerate(steps):
            if not isinstance(s, dict):
                self._fatal(f"steps[{i}] 가 객체가 아닙니다.")
            if not isinstance(s.get("step"), int) or isinstance(s.get("step"), bool):
                self._fatal(f"steps[{i}].step 은 정수여야 합니다 (현재: {s.get('step')!r}).")
            if s["step"] in seen:
                self._fatal(f"steps 의 step 번호 {s['step']} 가 중복됩니다.")
            seen.add(s["step"])
            if not s.get("name"):
                self._fatal(f"steps[{i}].name 이 필요합니다.")
            st = s.get("status")
            if st not in self.VALID_STATUSES:
                self._fatal(f"steps[{i}].status '{st}' 가 유효하지 않습니다 "
                            f"(허용: {', '.join(sorted(self.VALID_STATUSES))}).")
        phase = idx.get("phase", self._phase_dir_name)
        if not self._SAFE_PHASE.fullmatch(str(phase)):
            self._fatal(f"phase 이름 '{phase}' 에 git 브랜치로 못 쓰는 문자가 있습니다 "
                        f"(영문/숫자/._- 만 허용).")
        return idx

    # --- git ---

    def _run_git(self, *args) -> subprocess.CompletedProcess:
        cmd = ["git"] + list(args)
        return subprocess.run(cmd, cwd=self._root, capture_output=True, text=True)

    def _checkout_branch(self):
        branch = f"feat-{self._phase_name}"

        r = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        if r.returncode != 0:
            print(f"  ERROR: git을 사용할 수 없거나 git repo가 아닙니다.")
            print(f"  {r.stderr.strip()}")
            sys.exit(1)

        if r.stdout.strip() == branch:
            return

        r = self._run_git("rev-parse", "--verify", branch)
        r = self._run_git("checkout", branch) if r.returncode == 0 else self._run_git("checkout", "-b", branch)

        if r.returncode != 0:
            print(f"  ERROR: 브랜치 '{branch}' checkout 실패.")
            print(f"  {r.stderr.strip()}")
            print(f"  Hint: 변경사항을 stash하거나 commit한 후 다시 시도하세요.")
            sys.exit(1)

        print(f"  Branch: {branch}")

    @staticmethod
    def _looks_secret(path: str) -> bool:
        """파일명이 흔한 시크릿(.env·키·인증서)으로 보이면 True (커밋 차단용)."""
        base = path.rsplit("/", 1)[-1].lower()
        if base.endswith((".example", ".sample", ".template", ".dist")):
            return False
        if base == ".env" or base.startswith(".env."):
            return True
        if base in ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"):
            return True
        if base.endswith((".pem", ".key", ".pfx", ".p12", ".keystore")):
            return True
        return False

    def _unstage_secrets(self) -> list:
        """스테이징된 파일 중 시크릿 의심 파일을 스테이징 해제하고 경고한다.

        .gitignore가 1차 방어선이지만, 강제 추가(add -f)·미설정 다운스트림을 위한
        2차 가드. 워킹트리에는 남기므로 의도된 파일이면 사용자가 직접 커밋할 수 있다.
        """
        r = self._run_git("diff", "--cached", "--name-only")
        secrets = [f for f in r.stdout.splitlines() if f.strip() and self._looks_secret(f)]
        for s in secrets:
            self._run_git("reset", "HEAD", "--", s)
        if secrets:
            print(f"  ⚠ 시크릿 의심 파일을 커밋에서 제외합니다(스테이징 해제): {', '.join(secrets)}")
        return secrets

    def _commit_step(self, step_num: int, step_name: str, success: bool = True):
        """코드(feat/wip)와 메타데이터(chore)를 분리 커밋한다.

        success=False면 코드를 feat가 아니라 wip로 커밋한다(실패 step을 성공으로 위장 방지).
        2층 커밋의 핵심: 코드와 메타를 **명시적 경로**로 분리해, feat 커밋이 (다운스트림 훅 등으로)
        실패해도 그 코드가 chore에 흡수되지 않게 한다.
        """
        output_rel = f"phases/{self._phase_dir_name}/step{step_num}-output.json"
        index_rel = f"phases/{self._phase_dir_name}/index.json"

        # 1) 코드 커밋 — 메타 파일을 제외하고 스테이징
        self._run_git("add", "-A")
        self._run_git("reset", "HEAD", "--", output_rel)
        self._run_git("reset", "HEAD", "--", index_rel)
        self._unstage_secrets()  # 시크릿 의심 파일은 커밋하지 않는다

        if self._run_git("diff", "--cached", "--quiet").returncode != 0:
            tmpl = self.FEAT_MSG if success else self.WIP_MSG
            msg = tmpl.format(phase=self._phase_name, num=step_num, name=step_name)
            r = self._run_git("commit", "-m", msg)
            if r.returncode == 0:
                print(f"  Commit: {msg}")
            else:
                # 코드 커밋 실패 → chore에 흡수하지 않는다. 스테이징을 해제해 워킹트리에 그대로 남기고
                # 명확히 표면화한다(다운스트림 훅·서명 문제는 사람이 해결해야 한다).
                print(f"  ⚠ ERROR: 코드 커밋 실패 — chore에 흡수하지 않습니다: {r.stderr.strip()}")
                print(f"    스테이징을 해제합니다. 코드는 워킹트리에 남으니 훅·서명 문제 해결 후 직접 커밋하세요.")
                self._run_git("reset", "HEAD")

        # 2) 메타데이터(chore) 커밋 — 메타 경로만 **명시적으로** 스테이징한다.
        #    (`git add -A` 금지: 실패한 feat의 코드를 흡수하는 것을 막는다.)
        self._run_git("add", "--", output_rel, index_rel)
        if self._run_git("diff", "--cached", "--quiet").returncode != 0:
            msg = self.CHORE_MSG.format(phase=self._phase_name, num=step_num)
            r = self._run_git("commit", "-m", msg)
            if r.returncode != 0:
                print(f"  WARN: housekeeping 커밋 실패: {r.stderr.strip()}")

    # --- top-level index ---

    # top-level index의 phase 항목에 실시간으로 기록되는 라이브 필드.
    # 터미널 상태(completed/error/blocked)로 전이할 때 정리한다.
    LIVE_FIELDS = ("running_step", "attempt", "elapsed_seconds", "progress", "heartbeat_at", "team_round")

    def _update_top_index(self, status: str):
        if not self._top_index_file.exists():
            return
        top = self._read_json(self._top_index_file)
        ts = self._stamp()
        for phase in top.get("phases", []):
            if phase.get("dir") == self._phase_dir_name:
                phase["status"] = status
                ts_key = {"completed": "completed_at", "error": "failed_at", "blocked": "blocked_at"}.get(status)
                if ts_key:
                    phase[ts_key] = ts
                for k in self.LIVE_FIELDS:
                    phase.pop(k, None)
                break
        self._write_json(self._top_index_file, top)

    # --- 라이브 하트비트 (실행 중 진행 상태 공개) ---

    def _write_heartbeat(self, step_num: int, step_name: str, attempt: int,
                         done: int, elapsed: int):
        """현재 실행 중인 step의 상태를 top-level index.json에 1회 기록한다.

        step 실행 중에는 메인 스레드가 subprocess에서 블록되고 Claude 세션은
        phase-level index.json만 건드리므로, 이 시점에 top-level index.json을
        쓰는 주체는 하트비트 스레드뿐이다 → 경합 없음.
        """
        if not self._top_index_file.exists():
            return
        try:
            top = self._read_json(self._top_index_file)
        except (json.JSONDecodeError, OSError):
            return
        # 팀 리드가 자기 소유인 phase-level index.json에 기록한 team_round를 읽어
        # top-level로 복사한다 (하트비트 스레드의 top-index 단독 writer 불변식 유지).
        team_round = None
        try:
            team_round = self._read_json(self._index_file).get("team_round")
        except (json.JSONDecodeError, OSError):
            pass
        for phase in top.get("phases", []):
            if phase.get("dir") == self._phase_dir_name:
                phase["status"] = "running"
                phase["progress"] = f"{done}/{self._total}"
                phase["running_step"] = f"{step_num} ({step_name})"
                phase["attempt"] = attempt
                phase["elapsed_seconds"] = elapsed
                phase["heartbeat_at"] = self._stamp()
                if team_round:
                    phase["team_round"] = team_round
                break
        else:
            return
        self._write_json(self._top_index_file, top)

    @contextlib.contextmanager
    def _heartbeat(self, step_num: int, step_name: str, attempt: int,
                   done: int, interval: int = 60):
        """interval초(기본 60초)마다 진행 상태를 top-level index.json에 기록한다.

        사용자는 `watch -n5 cat phases/index.json` 등으로 장시간 실행 중인
        step의 진행 상황을 실시간으로 확인할 수 있다.
        """
        stop = threading.Event()
        t0 = time.monotonic()

        def _beat():
            while True:
                self._write_heartbeat(step_num, step_name, attempt, done,
                                      int(time.monotonic() - t0))
                if stop.wait(interval):
                    break

        th = threading.Thread(target=_beat, daemon=True)
        th.start()
        try:
            yield
        finally:
            stop.set()
            th.join()

    # --- 라이브 팀 대화창 (chat.md) ---

    def _chat_path(self) -> Path:
        return self._phase_dir / "chat.md"

    @staticmethod
    def _use_color(stream=None) -> bool:
        """대화창 ANSI 색 사용 여부. tty이거나 FORCE_COLOR가 설정되면 켠다.

        하네스를 파이프(예: Claude Code의 bash 도구, `| tee`)로 실행하면
        stdout.isatty()가 False라 색이 꺼진다. FORCE_COLOR=1을 주면 그 경우에도
        배경색 배지를 유지한다 — 라이브 대화창은 색이 핵심이므로.
        """
        stream = stream or sys.stdout
        return bool(os.environ.get("FORCE_COLOR")) or stream.isatty()

    def _chat_header(self, step_num: int, step_name: str, attempt: int):
        """이번 step 시작 구분선을 chat.md에 append한다 (리드가 대화를 이어 쓰기 전)."""
        tag = f"=== Step {step_num}: {step_name}"
        if attempt > 1:
            tag += f" (재시도 {attempt})"
        tag += " ==="
        try:
            with open(self._chat_path(), "a", encoding="utf-8") as f:
                f.write(f"\n{tag}\n")
        except OSError:
            pass

    @contextlib.contextmanager
    def _chat_tailer(self):
        """step 실행 동안 chat.md의 새 줄을 실시간으로 터미널에 채팅처럼 출력한다.

        시작 시점의 줄 수를 세어 '이번 step' 이후만 출력한다(이전 step 재출력 방지).
        리드(헤드리스 세션)가 chat.md에 append하는 주체이고, 여기선 읽기만 하므로 경합 없음.

        --quiet면 표시 스레드를 띄우지 않는다 — chat.md 기록은 그대로 쌓이므로
        상시 뷰어(scripts/chat.py)가 대화를 전담 표시한다 (이중 표시 방지).
        """
        if self._quiet:
            yield
            return
        path = str(self._chat_path())
        _, start = chat_view.read_new_lines(path, 0)
        color = self._use_color()
        stop = threading.Event()

        def _emit(line):
            rendered = chat_view.render_chat_line(line, color=color)
            if rendered:
                sys.stdout.write(rendered + "\n")
                sys.stdout.flush()

        th = threading.Thread(
            target=chat_view.follow,
            args=(path, stop, _emit),
            kwargs={"start_count": start},
            daemon=True,
        )
        th.start()
        try:
            yield
        finally:
            stop.set()
            th.join()

    # --- guardrails & context ---

    def _load_guardrails(self) -> str:
        sections = []
        claude_md = ROOT / "CLAUDE.md"
        if claude_md.exists():
            sections.append(f"## 프로젝트 규칙 (CLAUDE.md)\n\n{claude_md.read_text()}")
        for rules_file in self._rules_files():
            sections.append(f"## 프로젝트 규칙 (.claude/rules/{rules_file.name})\n\n{rules_file.read_text()}")
        docs_dir = ROOT / "docs"
        if docs_dir.is_dir():
            for doc in sorted(docs_dir.glob("*.md")):
                sections.append(f"## {doc.stem}\n\n{doc.read_text()}")
        return "\n\n---\n\n".join(sections) if sections else ""

    @staticmethod
    def _rules_files() -> list:
        """.claude/rules/ 하위의 living rules 파일들 (없으면 빈 리스트)."""
        rules_dir = ROOT / ".claude" / "rules"
        return sorted(rules_dir.glob("*.md")) if rules_dir.is_dir() else []

    @staticmethod
    def _build_step_context(index: dict) -> str:
        lines = [
            f"- Step {s['step']} ({s['name']}): {s['summary']}"
            for s in index["steps"]
            if s["status"] == "completed" and s.get("summary")
        ]
        if not lines:
            return ""
        return "## 이전 Step 산출물\n\n" + "\n".join(lines) + "\n\n"

    def _proposals_text(self) -> str:
        """이 phase에 이미 쌓인 rules-proposals.md를 preamble에 주입한다(cross-step 인지).

        헤드리스 Joy는 step마다 새로 스폰돼 직전 제안을 모른다 → 같은 제안 중복·
        '같은 실수 2번째' 트리거 누락을 막기 위해 기존 제안을 함께 넘긴다.
        """
        f = self._phase_dir / "rules-proposals.md"
        try:
            txt = f.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        if not txt:
            return ""
        return (
            f"## 이미 제안된 규칙 (중복 방지 · cross-step)\n\n"
            f"아래는 이 phase에서 이미 제안된 규칙이다. **같은 제안을 중복하지 말고**, "
            f"여기 있는 실수가 또 보이면 '2번째 발생'으로 인지해 즉시 교정 지시하라:\n\n"
            f"{txt[:1500]}\n\n---\n\n"
        )

    def _build_preamble(self, guardrails: str, step_context: str,
                        prev_error: Optional[str] = None) -> str:
        d = self._phase_dir_name
        r = self.INNER_ROUNDS
        retry_section = ""
        if prev_error:
            retry_section = (
                f"\n## ⚠ 이전 시도 실패 — 아래 에러를 반드시 참고하여 수정하라\n\n"
                f"{prev_error}\n\n---\n\n"
            )
        team_protocol = (
            f"## 팀 협업 프로토콜 (당신 = 팀 리드)\n\n"
            f"당신은 직접 구현하지 않는다. **Max·Patrick·Esther·Joy 서브에이전트를 Task 도구로 지휘**하고 모든 대화는 "
            f"한국어로 한다. 서브에이전트에는 CLAUDE.md만 자동 로드되므로, 각 서브에이전트에게 "
            f"\"시작 전 CLAUDE.md, .claude/rules/ 전체, **.claude/skills/의 네 craft 스킬**"
            f"(Max: test-driven-development·systematic-debugging, Patrick: data-engineering, Joy: code-review, Esther: frontend-design), "
            f"네 작업에 관련된 docs/를 **직접 읽어라**\"라고 지시한다(스킬은 페르소나 말투가 아니라 작업 규율이다).\n\n"
            f"진행 순서:\n"
            f"1. **Max**(개발)에게 이 step 구현을 지시한다.\n"
            f"2. step에 **데이터·DB·스키마·마이그레이션·쿼리·ETL·데이터모델링** 신호가 있으면 **Patrick**(데이터)을 투입한다(순수 비-데이터면 생략, 토큰 절약).\n"
            f"3. step에 UI·디자인·프론트엔드 신호가 있으면 **Esther**(UI/UX)를 투입한다(순수 백엔드면 생략, 토큰 절약).\n"
            f"4. 해당 step의 AC(실행 커맨드)를 **직접 실행**해 결과(커맨드 + exit code)를 확보한다.\n"
            f"5. **Joy**(검수)에게 **Max·Patrick·Esther의 작업 전부(git diff)**와 위 AC 결과로 검수를 맡긴다(보안·데이터 민감 diff—인증·외부 입력·시크릿·마이그레이션·데이터 손실—는 code-review 스킬 기준으로 특히 꼼꼼히 본다). Joy는 보고의 **마지막 줄**에 "
            f"정확히 하나의 센티넬을 찍는다: `VERDICT: PASS` 또는 `VERDICT: IMPROVE`. (Joy는 발견한 반복 실수를 규칙으로 제안하는 임무도 갖는다 — 작업규칙 참조.)\n"
            f"6. 당신은 **그 마지막 센티넬 줄만** 파싱해 루프를 제어한다.\n"
            f"   - `VERDICT: IMPROVE` → Joy의 `개선지시(→Max)` 불릿을 Max에게 전달해 수정 → Joy 재검수. 내부 최대 **{r}회**.\n"
            f"   - **Fail-safe**: 센티넬이 없거나·둘 이상이거나·변형되면 그 라운드를 IMPROVE로 처리한다 "
            f"(**절대 자동 PASS 금지**). 마지막 라운드였다면 step을 error로.\n"
            f"   - **Ground-truth 결박**: 실행 가능한 AC가 있는 step은, Joy가 센티넬 바로 위에 실제 커맨드와 exit "
            f"code(예: `AC: <cmd> -> exit 0`)를 제시했고 **exit 0일 때만 PASS 유효**. exit가 0이 아닌데 PASS면 "
            f"IMPROVE로 강등한다. (커맨드가 없는 docs-only step은 체크리스트 근거로 대체.)\n"
            f"   - **검증자 실패**: Joy의 Task가 죽거나·무응답이거나·센티넬을 못 찾으면 스스로 PASS를 만들지 말고 "
            f"step을 error(\"verifier unavailable\")로 두고 멈춘다. (리드 직접처리 폴백은 생산자 Max·Patrick·Esther에만.)\n"
            f"7. **실시간 대화창** (이 프레임워크의 핵심 — 사용자는 팀이 일하는 모습을 채팅으로 실시간으로 본다): "
            f"팀 대화를 phases/{d}/chat.md에 한 줄씩 즉시 쌓는다. **리드**는 step 헤더와 [리드] 메시지(지시·정리)를 쓴다. "
            f"**각 서브에이전트**를 Task로 호출할 때 이 chat.md 경로를 알려주고 '작업하며 **네 페르소나 말투로** [이름] 형식 한 줄을 "
            f"그때그때 append하라'고 지시한다 (Max=차분·겸손, Patrick=장난기 있지만 진중·배려 깊은 사수, Joy=밝고 활기참, Esther=따뜻하지만 자신 있게 — 자세한 건 .claude/agents/ 정의). "
            f"직원들은 가끔(~5%) 실없는 농담도 섞어 사람이 보기 즐겁게 하되, 일·검증은 진지하게 한다. "
            f"팀은 서로 친한 동료라 **편하게 반말로, 마크다운(별표·백틱) 없이, AI 격식 빼고 진짜 사람처럼** 대화한다. "
            f"서브에이전트가 빠뜨리면 리드가 그 팀원 말투로 대신 한 줄 남긴다. **코드·diff·전체 출력 금지** — 무엇을 하고/했는지만 대화체로. "
            f"예: [리드] 맥스, 이 step 좀 맡아줄래? · [Max] 응, 조용히 만들어놨어. pytest도 통과했고 · "
            f"[리드] 조이, 검수 좀 부탁해 · [Joy] 오 맥스 빠르다~ 바로 돌려볼게! exit 0, 통과 🎉\n"
            f"8. **진행 노출**: phases/{d}/index.json에 \"team_round\" 필드를 갱신한다(예: \"2/{r} IMPROVE\").\n"
            f"9. **내부 루프 미해결**: 내부 {r}회로도 해결 못 하면(비-blocked) step status를 error로, "
            f"**\"no_retry\": true**를 함께 기록하고 Joy의 마지막 개선지시 top-3를 error_message에 적는다.\n\n"
            f"---\n\n"
        )
        return (
            f"당신은 {self._project} 프로젝트의 **팀 리드**입니다. 아래 step을 팀으로 수행하세요.\n\n"
            f"{guardrails}\n\n---\n\n"
            f"{step_context}{self._proposals_text()}{retry_section}"
            f"{team_protocol}"
            f"## 작업 규칙\n\n"
            f"1. 이전 step에서 작성된 코드를 확인하고 일관성을 유지하라.\n"
            f"2. 이 step에 명시된 작업만 수행하라. 추가 기능이나 파일을 만들지 마라.\n"
            f"3. 기존 테스트를 깨뜨리지 마라.\n"
            f"4. AC(Acceptance Criteria) 검증을 직접 실행하라.\n"
            f"5. /phases/{d}/index.json의 해당 step status를 업데이트하라:\n"
            f"   - Joy가 PASS → \"completed\" + \"summary\" 필드에 이 step의 산출물을 한 줄로 요약\n"
            f"   - 내부 루프 미해결 → \"error\" + \"error_message\" + \"no_retry\": true 기록\n"
            f"   - 사용자 개입이 필요한 경우 (API 키, 인증, 수동 설정 등) → \"blocked\" + \"blocked_reason\" 기록 후 즉시 중단\n"
            f"6. 규칙 신선도(rules freshness) — **특히 Joy의 핵심 임무**: Max·Esther가 같은 실수를 반복하지 않도록,\n"
            f"   검수 중 발견한 (반복) 실수·새 컨벤션을 /phases/{d}/rules-proposals.md에\n"
            f"   \"- 제안: <규칙> (근거: <어떤 실수를 막는지>)\" 한 줄로 append한다 (파일이 없으면 생성). CLAUDE.md나\n"
            f"   .claude/rules/는 직접 수정하지 마라 — 사람이 검토 후 병합한다(자동 생성 규칙은 성과를 낮춘다). 제안할 것이 없으면 건너뛴다.\n"
            f"7. **직접 git add·커밋하지 마라** — 하네스(execute.py)가 step 종료 후 "
            f"코드(feat)와 메타데이터(chore)를 분리해 자동 커밋한다. 너는 위 5번"
            f"(index.json status·summary 갱신)까지만 하면 된다 (이중 커밋 방지).\n\n---\n\n"
        )

    # --- Claude 호출 ---

    @staticmethod
    def _result_detail(stdout: str) -> str:
        """claude `--output-format json` 봉투에서 사람이 읽을 실패/결과 요약을 뽑는다.

        파싱 실패면 빈 문자열을 반환한다(호출부가 raw stderr로 폴백). 재시도 모델에
        exit 코드만이 아니라 실제 실패 내용(subtype·result)을 피드백하기 위함이다.
        """
        try:
            env = json.loads(stdout)
        except (json.JSONDecodeError, TypeError):
            return ""
        if not isinstance(env, dict):
            return ""
        parts = []
        if env.get("subtype"):
            parts.append(f"subtype={env['subtype']}")
        if env.get("is_error"):
            parts.append("is_error=true")
        res = env.get("result") or env.get("error")
        if isinstance(res, str) and res.strip():
            parts.append(res.strip()[:800])
        return "; ".join(parts)

    def _invoke_claude(self, step: dict, preamble: str) -> dict:
        step_num, step_name = step["step"], step["name"]
        step_file = self._phase_dir / f"step{step_num}.md"

        if not step_file.exists():
            print(f"  ERROR: {step_file} not found")
            sys.exit(1)

        prompt = preamble + step_file.read_text()
        try:
            result = subprocess.run(
                ["claude", "-p", "--dangerously-skip-permissions", "--output-format", "json", prompt],
                cwd=self._root, capture_output=True, text=True, timeout=self.TIMEOUT_SECONDS,
            )
            returncode, stdout, stderr = result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as e:
            # 팀 루프가 한 세션에 들어가 타임아웃이 가장 흔한 실패가 된다.
            # 예외를 터뜨려 step을 비-terminal로 두지 말고, 비정상 종료로 귀결시킨다.
            returncode = 124
            stdout = e.stdout if isinstance(e.stdout, str) else ""
            stderr = f"session timed out after {self.TIMEOUT_SECONDS}s"
            print(f"\n  WARN: Claude 세션이 {self.TIMEOUT_SECONDS}s 타임아웃 (step {step_num})")

        if returncode != 0:
            print(f"\n  WARN: Claude가 비정상 종료됨 (code {returncode})")
            if stderr:
                print(f"  stderr: {stderr[:500]}")

        output = {
            "step": step_num, "name": step_name,
            "exitCode": returncode,
            "detail": self._result_detail(stdout),
            "stdout": stdout, "stderr": stderr,
        }
        out_path = self._phase_dir / f"step{step_num}-output.json"
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        return output

    # --- 헤더 & 검증 ---

    def _print_header(self):
        print(f"\n{'='*60}")
        print(f"  💼 팀 하네스 — '{self._project}'")
        print(f"  팀원   🔵 Max(개발)   🟠 Patrick(데이터)   🩷 Joy(검수)   🟡 Esther(UI/UX)")
        print(f"  Phase: {self._phase_name} | Steps: {self._total}")
        if self._auto_push:
            print(f"  Auto-push: enabled")
        print(f"{'='*60}")
        print(f"  팀이 일하는 대화를 실시간으로 봅니다 — 별도 창: python3 scripts/watch.py {self._phase_dir_name}")

    def _check_blockers(self):
        index = self._read_json(self._index_file)
        for s in reversed(index["steps"]):
            if s["status"] == "error":
                print(f"\n  ✗ Step {s['step']} ({s['name']}) failed.")
                print(f"  Error: {s.get('error_message', 'unknown')}")
                print(f"  Fix and reset status to 'pending' to retry.")
                sys.exit(1)
            if s["status"] == "blocked":
                print(f"\n  ⏸ Step {s['step']} ({s['name']}) blocked.")
                print(f"  Reason: {s.get('blocked_reason', 'unknown')}")
                print(f"  Resolve and reset status to 'pending' to retry.")
                sys.exit(2)
            if s["status"] != "pending":
                break

    def _ensure_created_at(self):
        index = self._read_json(self._index_file)
        if "created_at" not in index:
            index["created_at"] = self._stamp()
            self._write_json(self._index_file, index)

    # --- 규칙 신선도(rules freshness) ---

    def _unfilled_placeholders(self) -> list:
        """가드레일 소스(CLAUDE.md/rules/docs)에 남은 미작성 템플릿 칸을 찾는다.

        템플릿은 {프로젝트명}·{예: ...} 같은 한글 플레이스홀더를 쓴다. 실제 코드의
        중괄호 오탐을 줄이려고, 중괄호 안에 한글이나 '예:'가 있는 것만 플레이스홀더로 본다.
        """
        sources = [ROOT / "CLAUDE.md", *self._rules_files()]
        docs_dir = ROOT / "docs"
        if docs_dir.is_dir():
            sources += sorted(docs_dir.glob("*.md"))
        found = set()
        for src in sources:
            try:
                text = src.read_text(encoding="utf-8")
            except OSError:
                continue
            for m in self._PLACEHOLDER_RE.findall(text):
                inner = m[1:-1]
                if re.search(r"[가-힣]", inner) or inner.strip().startswith("예:"):
                    found.add(m.strip())
        return sorted(found)

    def _check_rules_freshness(self):
        """가드레일을 fresh하게 유지하기 위한 결정적(비-LLM) 점검.

        근거: 사람이 큐레이션한 규칙만 성과를 높인다(ETH arXiv 2602.11988).
        자동으로 덮어쓰지 않고 신선도 신호만 표면화해 사람의 검토를 유도한다:
          0) 미작성 템플릿 플레이스홀더({...}) — 채우지 않은 채 주입되면 LLM을 오도
          1) 검토 대기 중인 규칙 제안(rules-proposals.md)
          2) rules.md가 STALE_AFTER_DAYS 이상 리뷰되지 않음
          3) 규칙/CLAUDE.md가 정의되지 않은 빌드/테스트 커맨드를 참조 (stale 가능)
        """
        warnings = []

        placeholders = self._unfilled_placeholders()
        if placeholders:
            sample = ", ".join(placeholders[:5])
            more = " …" if len(placeholders) > 5 else ""
            warnings.append(
                f"가드레일에 미작성 템플릿 플레이스홀더가 {len(placeholders)}개 남아 있습니다: {sample}{more}\n"
                f"      → CLAUDE.md/.claude/rules/docs의 {{...}}를 실제 값으로 채우세요 "
                f"(미작성 컨텍스트가 매 step 주입되어 LLM을 오도합니다)."
            )

        rules_files = self._rules_files()
        if not rules_files:
            if warnings:
                print(f"\n  [rules freshness]")
                for w in warnings:
                    print(f"  ⚠ {w}")
            return

        proposals = sorted(self._phases_dir.glob("*/rules-proposals.md"))
        if proposals:
            rels = ", ".join(str(p.relative_to(ROOT)) for p in proposals)
            warnings.append(
                f"검토 대기 중인 규칙 제안 {len(proposals)}건: {rels}\n"
                f"      → 검토 후 .claude/rules/rules.md에 병합하고, 병합한 제안 파일은 삭제하세요."
            )

        rules_md = ROOT / ".claude" / "rules" / "rules.md"
        if rules_md.exists():
            m = re.search(r"last_reviewed\s*=\s*(\d{4}-\d{2}-\d{2})", rules_md.read_text())
            if m:
                try:
                    last = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                    age = (datetime.now(self.TZ).date() - last).days
                    if age > self.STALE_AFTER_DAYS:
                        warnings.append(
                            f"rules.md가 {age}일째 리뷰되지 않았습니다 (>{self.STALE_AFTER_DAYS}일). "
                            f"가지치기/검토 후 last_reviewed를 갱신하세요."
                        )
                except ValueError:
                    pass

        stale_cmds = self._stale_command_refs(rules_files)
        if stale_cmds:
            warnings.append(
                f"규칙/CLAUDE.md가 package.json에 없는 npm 스크립트를 참조합니다 (stale 가능): "
                f"{', '.join(stale_cmds)}"
            )

        if warnings:
            print(f"\n  [rules freshness]")
            for w in warnings:
                print(f"  ⚠ {w}")

    def _stale_command_refs(self, rules_files: list) -> list:
        """CLAUDE.md + rules에서 참조하는 `npm run <x>` 중 package.json에 없는 것."""
        pkg = ROOT / "package.json"
        if not pkg.exists():
            return []
        try:
            scripts = set(json.loads(pkg.read_text()).get("scripts", {}))
        except (json.JSONDecodeError, OSError):
            return []
        texts = []
        cm = ROOT / "CLAUDE.md"
        if cm.exists():
            texts.append(cm.read_text())
        texts.extend(f.read_text() for f in rules_files)
        referenced = set(re.findall(r"npm run ([A-Za-z0-9:_-]+)", "\n".join(texts)))
        return sorted(referenced - scripts)

    # --- 실행 루프 ---

    def _execute_single_step(self, step: dict, guardrails: str) -> bool:
        """단일 step 실행 (재시도 포함). 완료되면 True, 실패/차단이면 False."""
        step_num, step_name = step["step"], step["name"]
        done = sum(1 for s in self._read_json(self._index_file)["steps"] if s["status"] == "completed")
        prev_error = None

        for attempt in range(1, self.OUTER_ATTEMPTS + 1):
            index = self._read_json(self._index_file)
            step_context = self._build_step_context(index)
            preamble = self._build_preamble(guardrails, step_context, prev_error)

            tag = f"Step {step_num}/{self._total - 1} ({done} done): {step_name}"
            if attempt > 1:
                tag += f" [retry {attempt}/{self.OUTER_ATTEMPTS}]"
            print(f"\n▶ {tag} — 팀 대화 시작 …")

            t0 = time.monotonic()
            with self._chat_tailer():
                self._chat_header(step_num, step_name, attempt)
                with self._heartbeat(step_num, step_name, attempt, done):
                    out = self._invoke_claude(step, preamble)
            elapsed = int(time.monotonic() - t0)

            index = self._read_json(self._index_file)
            step_obj = next((s for s in index["steps"] if s["step"] == step_num), {})
            status = step_obj.get("status", "pending")
            ts = self._stamp()

            if status == "completed":
                step_obj["completed_at"] = ts
                self._write_json(self._index_file, index)
                self._commit_step(step_num, step_name)
                print(f"  ✓ Step {step_num}: {step_name} [{elapsed}s]")
                return True

            if status == "blocked":
                step_obj["blocked_at"] = ts
                self._write_json(self._index_file, index)
                print(f"  ⏸ Step {step_num}: {step_name} blocked [{elapsed}s]")
                print(f"    Reason: {step_obj.get('blocked_reason', '')}")
                self._update_top_index("blocked")
                sys.exit(2)

            # error 또는 status 미설정(프로세스 사망/타임아웃)
            err_msg = step_obj.get("error_message", "Step did not update status")
            # 실제 실패 신호(exit code + stderr 꼬리)를 주입해 다음 시도/최종 에러를 구체화한다.
            if out.get("exitCode", 0) != 0 or err_msg == "Step did not update status":
                detail = out.get("detail") or ""
                stderr_tail = (out.get("stderr") or "")[-1500:]
                detail_part = f"; {detail}" if detail else ""
                err_msg = f"{err_msg} [exit {out.get('exitCode')}{detail_part}; stderr tail: {stderr_tail}]"

            no_retry = bool(step_obj.get("no_retry", False))
            is_last = attempt >= self.OUTER_ATTEMPTS

            if no_retry or is_last:
                step_obj["status"] = "error"
                step_obj["error_message"] = f"[{attempt}회 시도 후 실패] {err_msg}"
                step_obj["failed_at"] = ts
                self._write_json(self._index_file, index)
                self._commit_step(step_num, step_name, success=False)
                why = " (no_retry: 내부 루프 미해결)" if no_retry and not is_last else ""
                print(f"  ✗ Step {step_num}: {step_name} failed{why} [{elapsed}s]")
                print(f"    Error: {err_msg}")
                self._update_top_index("error")
                sys.exit(1)

            # 바깥 재시도: 신규 컨텍스트로 재시작하며 이전 에러를 prev_error로 피드백한다.
            step_obj["status"] = "pending"
            step_obj.pop("error_message", None)
            step_obj.pop("no_retry", None)
            self._write_json(self._index_file, index)
            prev_error = err_msg
            print(f"  ↻ Step {step_num}: retry {attempt}/{self.OUTER_ATTEMPTS} — {err_msg}")

        return False  # unreachable

    def _execute_all_steps(self, guardrails: str):
        while True:
            index = self._read_json(self._index_file)
            pending = next((s for s in index["steps"] if s["status"] == "pending"), None)
            if pending is None:
                print("\n  All steps completed!")
                return

            step_num = pending["step"]
            for s in index["steps"]:
                if s["step"] == step_num and "started_at" not in s:
                    s["started_at"] = self._stamp()
                    self._write_json(self._index_file, index)
                    break

            self._execute_single_step(pending, guardrails)

    def _finalize(self):
        index = self._read_json(self._index_file)
        index["completed_at"] = self._stamp()
        self._write_json(self._index_file, index)
        self._update_top_index("completed")

        self._run_git("add", "-A")
        if self._run_git("diff", "--cached", "--quiet").returncode != 0:
            msg = f"chore({self._phase_name}): mark phase completed"
            r = self._run_git("commit", "-m", msg)
            if r.returncode == 0:
                print(f"  ✓ {msg}")

        if self._auto_push:
            branch = f"feat-{self._phase_name}"
            r = self._run_git("push", "-u", "origin", branch)
            if r.returncode != 0:
                print(f"\n  ERROR: git push 실패: {r.stderr.strip()}")
                sys.exit(1)
            print(f"  ✓ Pushed to origin/{branch}")

        print(f"\n{'='*60}")
        print(f"  Phase '{self._phase_name}' completed!")
        print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Harness Step Executor")
    parser.add_argument("phase_dir", help="Phase directory name (e.g. 0-mvp)")
    parser.add_argument("--push", action="store_true", help="Push branch after completion")
    parser.add_argument("--quiet", "--no-chat", action="store_true", dest="quiet",
                        help="인라인 대화 표시를 끈다 (상시 뷰어 scripts/chat.py와 함께 쓸 때)")
    args = parser.parse_args()

    StepExecutor(args.phase_dir, auto_push=args.push, quiet=args.quiet).run()


if __name__ == "__main__":
    main()
