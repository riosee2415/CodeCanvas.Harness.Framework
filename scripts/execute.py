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
    CHORE_MSG = "chore({phase}): step {num} output"
    TZ = timezone(timedelta(hours=9))
    STALE_AFTER_DAYS = 14  # rules.md가 이 일수 이상 리뷰되지 않으면 경고

    def __init__(self, phase_dir_name: str, *, auto_push: bool = False):
        self._root = str(ROOT)
        self._phases_dir = ROOT / "phases"
        self._phase_dir = self._phases_dir / phase_dir_name
        self._phase_dir_name = phase_dir_name
        self._top_index_file = self._phases_dir / "index.json"
        self._auto_push = auto_push

        if not self._phase_dir.is_dir():
            print(f"ERROR: {self._phase_dir} not found")
            sys.exit(1)

        self._index_file = self._phase_dir / "index.json"
        if not self._index_file.exists():
            print(f"ERROR: {self._index_file} not found")
            sys.exit(1)

        idx = self._read_json(self._index_file)
        self._project = idx.get("project", "project")
        self._phase_name = idx.get("phase", phase_dir_name)
        self._total = len(idx["steps"])

    def run(self):
        self._print_header()
        self._check_blockers()
        self._check_rules_freshness()
        self._checkout_branch()
        guardrails = self._load_guardrails()
        self._ensure_created_at()
        self._execute_all_steps(guardrails)
        self._finalize()

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

    def _commit_step(self, step_num: int, step_name: str):
        output_rel = f"phases/{self._phase_dir_name}/step{step_num}-output.json"
        index_rel = f"phases/{self._phase_dir_name}/index.json"

        self._run_git("add", "-A")
        self._run_git("reset", "HEAD", "--", output_rel)
        self._run_git("reset", "HEAD", "--", index_rel)

        if self._run_git("diff", "--cached", "--quiet").returncode != 0:
            msg = self.FEAT_MSG.format(phase=self._phase_name, num=step_num, name=step_name)
            r = self._run_git("commit", "-m", msg)
            if r.returncode == 0:
                print(f"  Commit: {msg}")
            else:
                print(f"  WARN: 코드 커밋 실패: {r.stderr.strip()}")

        self._run_git("add", "-A")
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
        """
        path = str(self._chat_path())
        _, start = chat_view.read_new_lines(path, 0)
        color = sys.stdout.isatty()
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

    def _build_preamble(self, guardrails: str, step_context: str,
                        prev_error: Optional[str] = None) -> str:
        commit_example = self.FEAT_MSG.format(
            phase=self._phase_name, num="N", name="<step-name>"
        )
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
            f"당신은 직접 구현하지 않는다. **Max·Esther·Joy 서브에이전트를 Task 도구로 지휘**하고 모든 대화는 "
            f"한국어로 한다. 서브에이전트에는 CLAUDE.md만 자동 로드되므로, 각 서브에이전트에게 "
            f"\"시작 전 CLAUDE.md, .claude/rules/ 전체, 네 작업에 관련된 docs/를 **직접 읽어라**\"라고 지시한다.\n\n"
            f"진행 순서:\n"
            f"1. **Max**(개발)에게 이 step 구현을 지시한다.\n"
            f"2. step에 UI·디자인·프론트엔드 신호가 있으면 **Esther**(UI/UX)를 투입한다(순수 백엔드면 생략, 토큰 절약).\n"
            f"3. 해당 step의 AC(실행 커맨드)를 **직접 실행**해 결과(커맨드 + exit code)를 확보한다.\n"
            f"4. **Joy**(검수)에게 **Max·Esther의 작업 전부(git diff)**와 위 AC 결과로 검수를 맡긴다. Joy는 보고의 **마지막 줄**에 "
            f"정확히 하나의 센티넬을 찍는다: `VERDICT: PASS` 또는 `VERDICT: IMPROVE`. (Joy는 발견한 반복 실수를 규칙으로 제안하는 임무도 갖는다 — 작업규칙 참조.)\n"
            f"5. 당신은 **그 마지막 센티넬 줄만** 파싱해 루프를 제어한다.\n"
            f"   - `VERDICT: IMPROVE` → Joy의 `개선지시(→Max)` 불릿을 Max에게 전달해 수정 → Joy 재검수. 내부 최대 **{r}회**.\n"
            f"   - **Fail-safe**: 센티넬이 없거나·둘 이상이거나·변형되면 그 라운드를 IMPROVE로 처리한다 "
            f"(**절대 자동 PASS 금지**). 마지막 라운드였다면 step을 error로.\n"
            f"   - **Ground-truth 결박**: 실행 가능한 AC가 있는 step은, Joy가 센티넬 바로 위에 실제 커맨드와 exit "
            f"code(예: `AC: <cmd> -> exit 0`)를 제시했고 **exit 0일 때만 PASS 유효**. exit가 0이 아닌데 PASS면 "
            f"IMPROVE로 강등한다. (커맨드가 없는 docs-only step은 체크리스트 근거로 대체.)\n"
            f"   - **검증자 실패**: Joy의 Task가 죽거나·무응답이거나·센티넬을 못 찾으면 스스로 PASS를 만들지 말고 "
            f"step을 error(\"verifier unavailable\")로 두고 멈춘다. (리드 직접처리 폴백은 생산자 Max·Esther에만.)\n"
            f"6. **실시간 대화창** (이 프레임워크의 핵심 — 사용자는 팀이 일하는 모습을 채팅으로 실시간으로 본다): "
            f"팀 대화를 phases/{d}/chat.md에 한 줄씩 즉시 쌓는다. **리드**는 step 헤더와 [리드] 메시지(지시·정리)를 쓴다. "
            f"**각 서브에이전트**를 Task로 호출할 때 이 chat.md 경로를 알려주고 '작업하며 **네 페르소나 말투로** [이름] 형식 한 줄을 "
            f"그때그때 append하라'고 지시한다 (Max=차분·겸손, Joy=밝고 활기참, Esther=따뜻하지만 자신 있게 — 자세한 건 .claude/agents/ 정의). "
            f"직원들은 가끔(~5%) 실없는 농담도 섞어 사람이 보기 즐겁게 하되, 일·검증은 진지하게 한다. "
            f"팀은 서로 친한 동료라 **편하게 반말로, 마크다운(별표·백틱) 없이, AI 격식 빼고 진짜 사람처럼** 대화한다. "
            f"서브에이전트가 빠뜨리면 리드가 그 팀원 말투로 대신 한 줄 남긴다. **코드·diff·전체 출력 금지** — 무엇을 하고/했는지만 대화체로. "
            f"예: [리드] 맥스, 이 step 좀 맡아줄래? · [Max] 응, 조용히 만들어놨어. pytest도 통과했고 · "
            f"[리드] 조이, 검수 좀 부탁해 · [Joy] 오 맥스 빠르다~ 바로 돌려볼게! exit 0, 통과 🎉\n"
            f"7. **진행 노출**: phases/{d}/index.json에 \"team_round\" 필드를 갱신한다(예: \"2/{r} IMPROVE\").\n"
            f"8. **내부 루프 미해결**: 내부 {r}회로도 해결 못 하면(비-blocked) step status를 error로, "
            f"**\"no_retry\": true**를 함께 기록하고 Joy의 마지막 개선지시 top-3를 error_message에 적는다.\n\n"
            f"---\n\n"
        )
        return (
            f"당신은 {self._project} 프로젝트의 **팀 리드**입니다. 아래 step을 팀으로 수행하세요.\n\n"
            f"{guardrails}\n\n---\n\n"
            f"{step_context}{retry_section}"
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
            f"7. 모든 변경사항을 커밋하라:\n"
            f"   {commit_example}\n\n---\n\n"
        )

    # --- Claude 호출 ---

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
        print(f"  팀원   🔵 Max(개발)    🩷 Joy(검수)    🟡 Esther(UI/UX)")
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

    def _check_rules_freshness(self):
        """rules.md를 fresh하게 유지하기 위한 결정적(비-LLM) 점검.

        근거: 사람이 큐레이션한 규칙만 성과를 높인다(ETH arXiv 2602.11988).
        따라서 자동으로 규칙을 덮어쓰지 않고, 신선도 신호만 표면화해 사람의
        검토를 유도한다. 세 가지 신호를 경고로 출력한다:
          1) 검토 대기 중인 규칙 제안(rules-proposals.md)
          2) rules.md가 STALE_AFTER_DAYS 이상 리뷰되지 않음
          3) 규칙/CLAUDE.md가 package.json에 없는 npm 스크립트를 참조 (stale 가능)
        """
        rules_files = self._rules_files()
        if not rules_files:
            return

        warnings = []

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
                stderr_tail = (out.get("stderr") or "")[-1500:]
                err_msg = f"{err_msg} [exit {out.get('exitCode')}; stderr tail: {stderr_tail}]"

            no_retry = bool(step_obj.get("no_retry", False))
            is_last = attempt >= self.OUTER_ATTEMPTS

            if no_retry or is_last:
                step_obj["status"] = "error"
                step_obj["error_message"] = f"[{attempt}회 시도 후 실패] {err_msg}"
                step_obj["failed_at"] = ts
                self._write_json(self._index_file, index)
                self._commit_step(step_num, step_name)
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
    args = parser.parse_args()

    StepExecutor(args.phase_dir, auto_push=args.push).run()


if __name__ == "__main__":
    main()
