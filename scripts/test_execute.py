"""
execute.py 리팩터링 안전망 테스트.
리팩터링 전후 동작이 동일한지 검증한다.
"""

import json
import os
import subprocess
import sys
import textwrap
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import execute as ex
import chat_view as cv


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_project(tmp_path):
    """phases/, CLAUDE.md, docs/ 를 갖춘 임시 프로젝트 구조."""
    phases_dir = tmp_path / "phases"
    phases_dir.mkdir()

    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# Rules\n- rule one\n- rule two")

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "arch.md").write_text("# Architecture\nSome content")
    (docs_dir / "guide.md").write_text("# Guide\nAnother doc")

    return tmp_path


@pytest.fixture
def phase_dir(tmp_project):
    """step 3개를 가진 phase 디렉토리."""
    d = tmp_project / "phases" / "0-mvp"
    d.mkdir()

    index = {
        "project": "TestProject",
        "phase": "mvp",
        "steps": [
            {"step": 0, "name": "setup", "status": "completed", "summary": "프로젝트 초기화 완료"},
            {"step": 1, "name": "core", "status": "completed", "summary": "핵심 로직 구현"},
            {"step": 2, "name": "ui", "status": "pending"},
        ],
    }
    (d / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False))
    (d / "step2.md").write_text("# Step 2: UI\n\nUI를 구현하세요.")

    return d


@pytest.fixture
def top_index(tmp_project):
    """phases/index.json (top-level)."""
    top = {
        "phases": [
            {"dir": "0-mvp", "status": "pending"},
            {"dir": "1-polish", "status": "pending"},
        ]
    }
    p = tmp_project / "phases" / "index.json"
    p.write_text(json.dumps(top, indent=2))
    return p


@pytest.fixture
def executor(tmp_project, phase_dir):
    """테스트용 StepExecutor 인스턴스. git 호출은 별도 mock 필요."""
    with patch.object(ex, "ROOT", tmp_project):
        inst = ex.StepExecutor("0-mvp")
    # 내부 경로를 tmp_project 기준으로 재설정
    inst._root = str(tmp_project)
    inst._phases_dir = tmp_project / "phases"
    inst._phase_dir = phase_dir
    inst._phase_dir_name = "0-mvp"
    inst._index_file = phase_dir / "index.json"
    inst._top_index_file = tmp_project / "phases" / "index.json"
    return inst


# ---------------------------------------------------------------------------
# _stamp (= 이전 now_iso)
# ---------------------------------------------------------------------------

class TestStamp:
    def test_returns_kst_timestamp(self, executor):
        result = executor._stamp()
        assert "+0900" in result

    def test_format_is_iso(self, executor):
        result = executor._stamp()
        dt = datetime.strptime(result, "%Y-%m-%dT%H:%M:%S%z")
        assert dt.tzinfo is not None

    def test_is_current_time(self, executor):
        before = datetime.now(ex.StepExecutor.TZ).replace(microsecond=0)
        result = executor._stamp()
        after = datetime.now(ex.StepExecutor.TZ).replace(microsecond=0) + timedelta(seconds=1)
        parsed = datetime.strptime(result, "%Y-%m-%dT%H:%M:%S%z")
        assert before <= parsed <= after


# ---------------------------------------------------------------------------
# _read_json / _write_json
# ---------------------------------------------------------------------------

class TestJsonHelpers:
    def test_roundtrip(self, tmp_path):
        data = {"key": "값", "nested": [1, 2, 3]}
        p = tmp_path / "test.json"
        ex.StepExecutor._write_json(p, data)
        loaded = ex.StepExecutor._read_json(p)
        assert loaded == data

    def test_save_ensures_ascii_false(self, tmp_path):
        p = tmp_path / "test.json"
        ex.StepExecutor._write_json(p, {"한글": "테스트"})
        raw = p.read_text()
        assert "한글" in raw
        assert "\\u" not in raw

    def test_save_indented(self, tmp_path):
        p = tmp_path / "test.json"
        ex.StepExecutor._write_json(p, {"a": 1})
        raw = p.read_text()
        assert "\n" in raw

    def test_load_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ex.StepExecutor._read_json(tmp_path / "nope.json")


# ---------------------------------------------------------------------------
# _load_guardrails
# ---------------------------------------------------------------------------

class TestLoadGuardrails:
    def test_loads_claude_md_and_docs(self, executor, tmp_project):
        with patch.object(ex, "ROOT", tmp_project):
            result = executor._load_guardrails()
        assert "# Rules" in result
        assert "rule one" in result
        assert "# Architecture" in result
        assert "# Guide" in result

    def test_sections_separated_by_divider(self, executor, tmp_project):
        with patch.object(ex, "ROOT", tmp_project):
            result = executor._load_guardrails()
        assert "---" in result

    def test_docs_sorted_alphabetically(self, executor, tmp_project):
        with patch.object(ex, "ROOT", tmp_project):
            result = executor._load_guardrails()
        arch_pos = result.index("arch")
        guide_pos = result.index("guide")
        assert arch_pos < guide_pos

    def test_no_claude_md(self, executor, tmp_project):
        (tmp_project / "CLAUDE.md").unlink()
        with patch.object(ex, "ROOT", tmp_project):
            result = executor._load_guardrails()
        assert "CLAUDE.md" not in result
        assert "Architecture" in result

    def test_no_docs_dir(self, executor, tmp_project):
        import shutil
        shutil.rmtree(tmp_project / "docs")
        with patch.object(ex, "ROOT", tmp_project):
            result = executor._load_guardrails()
        assert "Rules" in result
        assert "Architecture" not in result

    def test_empty_project(self, tmp_path):
        with patch.object(ex, "ROOT", tmp_path):
            # executor가 필요 없는 static-like 동작이므로 임시 인스턴스
            phases_dir = tmp_path / "phases" / "dummy"
            phases_dir.mkdir(parents=True)
            idx = {"project": "T", "phase": "t", "steps": []}
            (phases_dir / "index.json").write_text(json.dumps(idx))
            inst = ex.StepExecutor.__new__(ex.StepExecutor)
            result = inst._load_guardrails()
        assert result == ""


# ---------------------------------------------------------------------------
# _build_step_context
# ---------------------------------------------------------------------------

class TestBuildStepContext:
    def test_includes_completed_with_summary(self, phase_dir):
        index = json.loads((phase_dir / "index.json").read_text())
        result = ex.StepExecutor._build_step_context(index)
        assert "Step 0 (setup): 프로젝트 초기화 완료" in result
        assert "Step 1 (core): 핵심 로직 구현" in result

    def test_excludes_pending(self, phase_dir):
        index = json.loads((phase_dir / "index.json").read_text())
        result = ex.StepExecutor._build_step_context(index)
        assert "ui" not in result

    def test_excludes_completed_without_summary(self, phase_dir):
        index = json.loads((phase_dir / "index.json").read_text())
        del index["steps"][0]["summary"]
        result = ex.StepExecutor._build_step_context(index)
        assert "setup" not in result
        assert "core" in result

    def test_empty_when_no_completed(self):
        index = {"steps": [{"step": 0, "name": "a", "status": "pending"}]}
        result = ex.StepExecutor._build_step_context(index)
        assert result == ""

    def test_has_header(self, phase_dir):
        index = json.loads((phase_dir / "index.json").read_text())
        result = ex.StepExecutor._build_step_context(index)
        assert result.startswith("## 이전 Step 산출물")


# ---------------------------------------------------------------------------
# _build_preamble
# ---------------------------------------------------------------------------

class TestBuildPreamble:
    def test_includes_project_name(self, executor):
        result = executor._build_preamble("", "")
        assert "TestProject" in result

    def test_includes_guardrails(self, executor):
        result = executor._build_preamble("GUARD_CONTENT", "")
        assert "GUARD_CONTENT" in result

    def test_includes_step_context(self, executor):
        ctx = "## 이전 Step 산출물\n\n- Step 0: done"
        result = executor._build_preamble("", ctx)
        assert "이전 Step 산출물" in result

    def test_tells_lead_not_to_commit(self, executor):
        # 커밋은 하네스(execute.py)가 일원화 — 리드/세션은 직접 커밋하지 않는다(이중 커밋 방지).
        result = executor._build_preamble("", "")
        assert "커밋하지 마라" in result
        assert "모든 변경사항을 커밋하라" not in result

    def test_includes_rules(self, executor):
        result = executor._build_preamble("", "")
        assert "작업 규칙" in result
        assert "AC" in result

    def test_no_retry_section_by_default(self, executor):
        result = executor._build_preamble("", "")
        assert "이전 시도 실패" not in result

    def test_retry_section_with_prev_error(self, executor):
        result = executor._build_preamble("", "", prev_error="타입 에러 발생")
        assert "이전 시도 실패" in result
        assert "타입 에러 발생" in result

    def test_includes_inner_rounds(self, executor):
        result = executor._build_preamble("", "")
        assert str(ex.StepExecutor.INNER_ROUNDS) in result

    def test_includes_index_path(self, executor):
        result = executor._build_preamble("", "")
        assert "/phases/0-mvp/index.json" in result

    def test_includes_patrick_data_specialist(self, executor):
        result = executor._build_preamble("", "")
        # 멤버·스킬 매핑·Joy 검수 대상에 Patrick 포함
        assert "Patrick" in result
        assert "data-engineering" in result
        assert "Max·Patrick·Esther" in result
        # 데이터 신호 트리거 문구
        assert "마이그레이션" in result


# ---------------------------------------------------------------------------
# _update_top_index
# ---------------------------------------------------------------------------

class TestUpdateTopIndex:
    def test_completed(self, executor, top_index):
        executor._top_index_file = top_index
        executor._update_top_index("completed")
        data = json.loads(top_index.read_text())
        mvp = next(p for p in data["phases"] if p["dir"] == "0-mvp")
        assert mvp["status"] == "completed"
        assert "completed_at" in mvp

    def test_error(self, executor, top_index):
        executor._top_index_file = top_index
        executor._update_top_index("error")
        data = json.loads(top_index.read_text())
        mvp = next(p for p in data["phases"] if p["dir"] == "0-mvp")
        assert mvp["status"] == "error"
        assert "failed_at" in mvp

    def test_blocked(self, executor, top_index):
        executor._top_index_file = top_index
        executor._update_top_index("blocked")
        data = json.loads(top_index.read_text())
        mvp = next(p for p in data["phases"] if p["dir"] == "0-mvp")
        assert mvp["status"] == "blocked"
        assert "blocked_at" in mvp

    def test_other_phases_unchanged(self, executor, top_index):
        executor._top_index_file = top_index
        executor._update_top_index("completed")
        data = json.loads(top_index.read_text())
        polish = next(p for p in data["phases"] if p["dir"] == "1-polish")
        assert polish["status"] == "pending"

    def test_nonexistent_dir_is_noop(self, executor, top_index):
        executor._top_index_file = top_index
        executor._phase_dir_name = "no-such-dir"
        original = json.loads(top_index.read_text())
        executor._update_top_index("completed")
        after = json.loads(top_index.read_text())
        for p_before, p_after in zip(original["phases"], after["phases"]):
            assert p_before["status"] == p_after["status"]

    def test_no_top_index_file(self, executor, tmp_path):
        executor._top_index_file = tmp_path / "nonexistent.json"
        executor._update_top_index("completed")  # should not raise

    def test_clears_live_fields_on_terminal(self, executor, top_index):
        data = json.loads(top_index.read_text())
        mvp = next(p for p in data["phases"] if p["dir"] == "0-mvp")
        mvp.update({"status": "running", "running_step": "2 (ui)", "attempt": 1,
                    "elapsed_seconds": 120, "progress": "2/3", "heartbeat_at": "x"})
        top_index.write_text(json.dumps(data, indent=2))

        executor._top_index_file = top_index
        executor._update_top_index("completed")

        after = json.loads(top_index.read_text())
        mvp = next(p for p in after["phases"] if p["dir"] == "0-mvp")
        assert mvp["status"] == "completed"
        for k in ("running_step", "attempt", "elapsed_seconds", "progress", "heartbeat_at"):
            assert k not in mvp


# ---------------------------------------------------------------------------
# _write_heartbeat / _heartbeat
# ---------------------------------------------------------------------------

class TestHeartbeat:
    def test_writes_live_status(self, executor, top_index):
        executor._top_index_file = top_index
        executor._write_heartbeat(2, "ui", attempt=1, done=2, elapsed=65)
        data = json.loads(top_index.read_text())
        mvp = next(p for p in data["phases"] if p["dir"] == "0-mvp")
        assert mvp["status"] == "running"
        assert mvp["running_step"] == "2 (ui)"
        assert mvp["progress"] == "2/3"
        assert mvp["attempt"] == 1
        assert mvp["elapsed_seconds"] == 65
        assert "heartbeat_at" in mvp

    def test_only_target_phase_updated(self, executor, top_index):
        executor._top_index_file = top_index
        executor._write_heartbeat(2, "ui", attempt=1, done=2, elapsed=10)
        data = json.loads(top_index.read_text())
        polish = next(p for p in data["phases"] if p["dir"] == "1-polish")
        assert polish["status"] == "pending"
        assert "running_step" not in polish

    def test_no_top_index_is_noop(self, executor, tmp_path):
        executor._top_index_file = tmp_path / "nonexistent.json"
        executor._write_heartbeat(2, "ui", attempt=1, done=2, elapsed=10)  # should not raise

    def test_corrupt_top_index_is_noop(self, executor, top_index):
        top_index.write_text("{ not valid json")
        executor._top_index_file = top_index
        executor._write_heartbeat(2, "ui", attempt=1, done=2, elapsed=10)  # should not raise

    def test_context_manager_writes_at_least_once(self, executor, top_index):
        import time
        executor._top_index_file = top_index
        with executor._heartbeat(2, "ui", attempt=1, done=2, interval=60):
            time.sleep(0.05)
        data = json.loads(top_index.read_text())
        mvp = next(p for p in data["phases"] if p["dir"] == "0-mvp")
        assert mvp["status"] == "running"
        assert mvp["elapsed_seconds"] >= 0


# ---------------------------------------------------------------------------
# _checkout_branch (mocked)
# ---------------------------------------------------------------------------

class TestCheckoutBranch:
    def _mock_git(self, executor, responses):
        call_idx = {"i": 0}
        def fake_git(*args):
            idx = call_idx["i"]
            call_idx["i"] += 1
            if idx < len(responses):
                return responses[idx]
            return MagicMock(returncode=0, stdout="", stderr="")
        executor._run_git = fake_git

    def test_already_on_branch(self, executor):
        self._mock_git(executor, [
            MagicMock(returncode=0, stdout="feat-mvp\n", stderr=""),
        ])
        executor._checkout_branch()  # should return without checkout

    def test_branch_exists_checkout(self, executor):
        self._mock_git(executor, [
            MagicMock(returncode=0, stdout="main\n", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ])
        executor._checkout_branch()

    def test_branch_not_exists_create(self, executor):
        self._mock_git(executor, [
            MagicMock(returncode=0, stdout="main\n", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="not found"),
            MagicMock(returncode=0, stdout="", stderr=""),
        ])
        executor._checkout_branch()

    def test_checkout_fails_exits(self, executor):
        self._mock_git(executor, [
            MagicMock(returncode=0, stdout="main\n", stderr=""),
            MagicMock(returncode=1, stdout="", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="dirty tree"),
        ])
        with pytest.raises(SystemExit) as exc_info:
            executor._checkout_branch()
        assert exc_info.value.code == 1

    def test_no_git_exits(self, executor):
        self._mock_git(executor, [
            MagicMock(returncode=1, stdout="", stderr="not a git repo"),
        ])
        with pytest.raises(SystemExit) as exc_info:
            executor._checkout_branch()
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# _commit_step (mocked)
# ---------------------------------------------------------------------------

class TestCommitStep:
    def test_two_phase_commit(self, executor):
        calls = []
        def fake_git(*args):
            calls.append(args)
            if args[:2] == ("diff", "--cached"):
                return MagicMock(returncode=1)
            return MagicMock(returncode=0, stdout="", stderr="")
        executor._run_git = fake_git

        executor._commit_step(2, "ui")

        commit_calls = [c for c in calls if c[0] == "commit"]
        assert len(commit_calls) == 2
        assert "feat(mvp):" in commit_calls[0][2]
        assert "chore(mvp):" in commit_calls[1][2]

    def test_no_code_changes_skips_feat_commit(self, executor):
        call_count = {"diff": 0}
        calls = []
        def fake_git(*args):
            calls.append(args)
            if args[:3] == ("diff", "--cached", "--name-only"):
                return MagicMock(returncode=0, stdout="", stderr="")  # 시크릿 스캔 (코드 변경 무관)
            if args[:3] == ("diff", "--cached", "--quiet"):
                call_count["diff"] += 1
                if call_count["diff"] == 1:
                    return MagicMock(returncode=0)  # 코드 변경 없음 → feat 스킵
                return MagicMock(returncode=1)      # 메타 변경 있음 → chore
            return MagicMock(returncode=0, stdout="", stderr="")
        executor._run_git = fake_git

        executor._commit_step(2, "ui")

        commit_msgs = [c[2] for c in calls if c[0] == "commit"]
        assert len(commit_msgs) == 1
        assert "chore" in commit_msgs[0]


class TestCommitStepIntegration:
    """실제 임시 git repo에서 _commit_step을 돌려 커밋 무결성을 검증한다 (#1, #5).

    fake_git 단위테스트가 못 잡는 회귀(메타 흡수·실패 step 오라벨)를 실제 git으로 잠근다.
    """

    def _git(self, repo, *args):
        return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)

    def _init_repo(self, tmp_path):
        self._git(tmp_path, "init", "-q")
        self._git(tmp_path, "config", "user.email", "t@example.com")
        self._git(tmp_path, "config", "user.name", "t")
        self._git(tmp_path, "config", "commit.gpgsign", "false")
        self._git(tmp_path, "commit", "-q", "--allow-empty", "-m", "init")
        d = tmp_path / "phases" / "0-x"
        d.mkdir(parents=True)
        (d / "index.json").write_text(
            json.dumps({"project": "P", "phase": "x",
                        "steps": [{"step": 0, "name": "core", "status": "completed", "summary": "s"}]}),
            encoding="utf-8")
        return tmp_path, d

    def _executor(self, repo):
        with patch.object(ex, "ROOT", repo):
            inst = ex.StepExecutor("0-x")
        inst._root = str(repo)
        inst._phases_dir = repo / "phases"
        inst._phase_dir = repo / "phases" / "0-x"
        inst._phase_dir_name = "0-x"
        inst._phase_name = "x"
        inst._index_file = repo / "phases" / "0-x" / "index.json"
        return inst

    def _commit_files(self, repo, subj_substr):
        r = self._git(repo, "log", "--format=%H\t%s")
        for line in r.stdout.strip().splitlines():
            h, _, subj = line.partition("\t")
            if subj_substr in subj:
                files = self._git(repo, "show", "--name-only", "--format=", h).stdout.strip().splitlines()
                return [f for f in files if f]
        return None

    def _porcelain(self, repo):
        return self._git(repo, "status", "--porcelain").stdout.strip()

    def test_success_feat_has_code_chore_has_meta(self, tmp_path):
        repo, d = self._init_repo(tmp_path)
        (repo / "smoke.py").write_text("x = 1\n", encoding="utf-8")
        (d / "step0-output.json").write_text("{}", encoding="utf-8")
        self._executor(repo)._commit_step(0, "core", success=True)

        feat = self._commit_files(repo, "feat(x): step 0")
        assert feat is not None and "smoke.py" in feat
        assert "phases/0-x/index.json" not in feat       # 메타는 feat에 안 들어간다
        chore = self._commit_files(repo, "chore(x): step 0")
        assert chore is not None and "phases/0-x/index.json" in chore
        assert self._porcelain(repo) == ""               # 트리 clean

    def test_feat_failure_does_not_absorb_code_into_chore(self, tmp_path):
        repo, d = self._init_repo(tmp_path)
        # feat/wip 메시지 커밋만 거부하는 commit-msg 훅 (chore는 통과)
        hook = repo / ".git" / "hooks" / "commit-msg"
        hook.write_text('#!/bin/sh\ngrep -qE "^(feat|wip)" "$1" && exit 1\nexit 0\n', encoding="utf-8")
        hook.chmod(0o755)
        (repo / "smoke.py").write_text("x = 1\n", encoding="utf-8")
        (d / "step0-output.json").write_text("{}", encoding="utf-8")
        self._executor(repo)._commit_step(0, "core", success=True)

        chore = self._commit_files(repo, "chore(x): step 0")
        assert chore is None or "smoke.py" not in chore   # 코드가 chore에 흡수되면 안 됨
        assert "smoke.py" in self._porcelain(repo)        # 코드는 워킹트리에 남는다

    def test_failed_step_uses_wip_not_feat(self, tmp_path):
        repo, d = self._init_repo(tmp_path)
        (repo / "broken.py").write_text("def f(\n", encoding="utf-8")
        (d / "step0-output.json").write_text("{}", encoding="utf-8")
        self._executor(repo)._commit_step(0, "core", success=False)

        subjects = self._git(repo, "log", "--format=%s").stdout
        assert "wip(x): step 0" in subjects
        assert "feat(x): step 0" not in subjects

    def test_secret_files_not_committed(self, tmp_path):
        repo, d = self._init_repo(tmp_path)
        (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
        (repo / ".env").write_text("SECRET=abc\n", encoding="utf-8")
        (d / "step0-output.json").write_text("{}", encoding="utf-8")
        self._executor(repo)._commit_step(0, "core", success=True)

        feat = self._commit_files(repo, "feat(x): step 0")
        assert feat is not None and "app.py" in feat
        assert ".env" not in feat                      # 시크릿은 커밋되지 않는다
        assert ".env" in self._porcelain(repo)         # 워킹트리에 남는다(미커밋)


class TestSecretGuard:
    def test_looks_secret_true(self):
        for p in [".env", ".env.local", "dir/.env.production",
                  "id_rsa", "certs/server.pem", "app.key", "store.p12"]:
            assert ex.StepExecutor._looks_secret(p) is True, p

    def test_looks_secret_false(self):
        for p in ["main.py", "README.md", ".env.example", ".env.sample",
                  "config.json", "styles.css"]:
            assert ex.StepExecutor._looks_secret(p) is False, p


# ---------------------------------------------------------------------------
# _invoke_claude (mocked)
# ---------------------------------------------------------------------------

class TestInvokeClaude:
    def test_invokes_claude_with_correct_args(self, executor):
        mock_result = MagicMock(returncode=0, stdout='{"result": "ok"}', stderr="")
        step = {"step": 2, "name": "ui"}
        preamble = "PREAMBLE\n"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            output = executor._invoke_claude(step, preamble)

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "--dangerously-skip-permissions" in cmd
        assert "--output-format" in cmd
        assert "PREAMBLE" in cmd[-1]
        assert "UI를 구현하세요" in cmd[-1]

    def test_saves_output_json(self, executor):
        mock_result = MagicMock(returncode=0, stdout='{"ok": true}', stderr="")
        step = {"step": 2, "name": "ui"}

        with patch("subprocess.run", return_value=mock_result):
            executor._invoke_claude(step, "preamble")

        output_file = executor._phase_dir / "step2-output.json"
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert data["step"] == 2
        assert data["name"] == "ui"
        assert data["exitCode"] == 0

    def test_nonexistent_step_file_exits(self, executor):
        step = {"step": 99, "name": "nonexistent"}
        with pytest.raises(SystemExit) as exc_info:
            executor._invoke_claude(step, "preamble")
        assert exc_info.value.code == 1

    def test_timeout_is_timeout_seconds(self, executor):
        mock_result = MagicMock(returncode=0, stdout="{}", stderr="")
        step = {"step": 2, "name": "ui"}

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            executor._invoke_claude(step, "preamble")

        assert mock_run.call_args[1]["timeout"] == ex.StepExecutor.TIMEOUT_SECONDS
        assert ex.StepExecutor.TIMEOUT_SECONDS == 3600


# ---------------------------------------------------------------------------
# progress_indicator (= 이전 Spinner)
# ---------------------------------------------------------------------------

class TestProgressIndicator:
    def test_context_manager(self):
        import time
        with ex.progress_indicator("test") as pi:
            time.sleep(0.15)
        assert pi.elapsed >= 0.1

    def test_elapsed_increases(self):
        import time
        with ex.progress_indicator("test") as pi:
            time.sleep(0.2)
        assert pi.elapsed > 0


# ---------------------------------------------------------------------------
# main() CLI 파싱 (mocked)
# ---------------------------------------------------------------------------

class TestMainCli:
    def test_no_args_exits(self):
        with patch("sys.argv", ["execute.py"]):
            with pytest.raises(SystemExit) as exc_info:
                ex.main()
            assert exc_info.value.code == 2  # argparse exits with 2

    def test_invalid_phase_dir_exits(self):
        with patch("sys.argv", ["execute.py", "nonexistent"]):
            with patch.object(ex, "ROOT", Path("/tmp/fake_nonexistent")):
                with pytest.raises(SystemExit) as exc_info:
                    ex.main()
                assert exc_info.value.code == 1

    def test_missing_index_exits(self, tmp_project):
        (tmp_project / "phases" / "empty").mkdir()
        with patch("sys.argv", ["execute.py", "empty"]):
            with patch.object(ex, "ROOT", tmp_project):
                with pytest.raises(SystemExit) as exc_info:
                    ex.main()
                assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# _check_blockers (= 이전 main() error/blocked 체크)
# ---------------------------------------------------------------------------

class TestCheckBlockers:
    def _make_executor_with_steps(self, tmp_project, steps):
        d = tmp_project / "phases" / "test-phase"
        d.mkdir(exist_ok=True)
        index = {"project": "T", "phase": "test", "steps": steps}
        (d / "index.json").write_text(json.dumps(index))

        with patch.object(ex, "ROOT", tmp_project):
            inst = ex.StepExecutor.__new__(ex.StepExecutor)
        inst._root = str(tmp_project)
        inst._phases_dir = tmp_project / "phases"
        inst._phase_dir = d
        inst._phase_dir_name = "test-phase"
        inst._index_file = d / "index.json"
        inst._top_index_file = tmp_project / "phases" / "index.json"
        inst._phase_name = "test"
        inst._total = len(steps)
        return inst

    def test_error_step_exits_1(self, tmp_project):
        steps = [
            {"step": 0, "name": "ok", "status": "completed"},
            {"step": 1, "name": "bad", "status": "error", "error_message": "fail"},
        ]
        inst = self._make_executor_with_steps(tmp_project, steps)
        with pytest.raises(SystemExit) as exc_info:
            inst._check_blockers()
        assert exc_info.value.code == 1

    def test_blocked_step_exits_2(self, tmp_project):
        steps = [
            {"step": 0, "name": "ok", "status": "completed"},
            {"step": 1, "name": "stuck", "status": "blocked", "blocked_reason": "API key"},
        ]
        inst = self._make_executor_with_steps(tmp_project, steps)
        with pytest.raises(SystemExit) as exc_info:
            inst._check_blockers()
        assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# 규칙 신선도 (rules freshness)
# ---------------------------------------------------------------------------

class TestRulesFreshness:
    def _mk_rules(self, tmp_project, content="# rules\n- rule a"):
        rd = tmp_project / ".claude" / "rules"
        rd.mkdir(parents=True, exist_ok=True)
        (rd / "rules.md").write_text(content)
        return rd

    def test_rules_files_empty_when_no_dir(self, executor, tmp_project):
        with patch.object(ex, "ROOT", tmp_project):
            assert executor._rules_files() == []

    def test_rules_files_lists_md(self, executor, tmp_project):
        self._mk_rules(tmp_project)
        with patch.object(ex, "ROOT", tmp_project):
            files = executor._rules_files()
        assert [f.name for f in files] == ["rules.md"]

    def test_guardrails_includes_rules(self, executor, tmp_project):
        self._mk_rules(tmp_project, "# rules\n- 항상 UTC 사용")
        with patch.object(ex, "ROOT", tmp_project):
            result = executor._load_guardrails()
        assert "항상 UTC 사용" in result
        assert ".claude/rules/rules.md" in result

    def test_stale_command_refs_flags_missing(self, executor, tmp_project):
        (tmp_project / "package.json").write_text(
            json.dumps({"scripts": {"build": "x", "test": "y"}}))
        self._mk_rules(tmp_project, "규칙: `npm run lint` 후 `npm run typecheck` 실행")
        with patch.object(ex, "ROOT", tmp_project):
            missing = executor._stale_command_refs(executor._rules_files())
        assert "lint" in missing
        assert "typecheck" in missing
        assert "build" not in missing

    def test_stale_command_refs_no_pkg_is_empty(self, executor, tmp_project):
        self._mk_rules(tmp_project, "`npm run lint`")
        with patch.object(ex, "ROOT", tmp_project):
            assert executor._stale_command_refs(executor._rules_files()) == []

    def test_freshness_silent_when_no_rules(self, executor, tmp_project, capsys):
        with patch.object(ex, "ROOT", tmp_project):
            executor._check_rules_freshness()
        assert capsys.readouterr().out == ""

    def test_freshness_warns_pending_proposals(self, executor, tmp_project, capsys):
        self._mk_rules(tmp_project)
        (tmp_project / "phases" / "0-mvp" / "rules-proposals.md").write_text("- 제안: x")
        with patch.object(ex, "ROOT", tmp_project):
            executor._check_rules_freshness()
        assert "검토 대기" in capsys.readouterr().out

    def test_freshness_warns_stale_date(self, executor, tmp_project, capsys):
        self._mk_rules(tmp_project,
                       "<!-- harness:freshness last_reviewed=2000-01-01 -->\n# rules")
        with patch.object(ex, "ROOT", tmp_project):
            executor._check_rules_freshness()
        assert "리뷰되지 않" in capsys.readouterr().out

    def test_freshness_fresh_date_no_stale_warn(self, executor, tmp_project, capsys):
        today = datetime.now(ex.StepExecutor.TZ).date().isoformat()
        self._mk_rules(tmp_project,
                       f"<!-- harness:freshness last_reviewed={today} -->\n# rules")
        with patch.object(ex, "ROOT", tmp_project):
            executor._check_rules_freshness()
        assert "리뷰되지 않" not in capsys.readouterr().out

    def test_preamble_includes_proposals_instruction(self, executor):
        result = executor._build_preamble("", "")
        assert "rules-proposals.md" in result
        assert "신선도" in result


# ---------------------------------------------------------------------------
# 팀 협업 — 상수 (INNER_ROUNDS / OUTER_ATTEMPTS / TIMEOUT_SECONDS)
# ---------------------------------------------------------------------------

class TestTeamConstants:
    def test_inner_rounds_is_3(self):
        assert ex.StepExecutor.INNER_ROUNDS == 3

    def test_outer_attempts_is_2(self):
        assert ex.StepExecutor.OUTER_ATTEMPTS == 2

    def test_timeout_seconds_is_3600(self):
        assert ex.StepExecutor.TIMEOUT_SECONDS == 3600


# ---------------------------------------------------------------------------
# 팀 협업 — 프리앰블(팀 리드 프로토콜)
# ---------------------------------------------------------------------------

class TestTeamPreamble:
    def test_frames_session_as_team_lead(self, executor):
        r = executor._build_preamble("", "")
        assert "팀 리드" in r

    def test_names_all_three_agents(self, executor):
        r = executor._build_preamble("", "")
        assert "Max" in r
        assert "Joy" in r
        assert "Esther" in r

    def test_includes_verdict_sentinel_grammar(self, executor):
        r = executor._build_preamble("", "")
        assert "VERDICT: PASS" in r
        assert "VERDICT: IMPROVE" in r

    def test_includes_inner_rounds_bound(self, executor):
        r = executor._build_preamble("", "")
        assert str(ex.StepExecutor.INNER_ROUNDS) in r

    def test_references_live_chat(self, executor):
        r = executor._build_preamble("", "")
        assert "chat.md" in r

    def test_chat_uses_speaker_prefixes(self, executor):
        r = executor._build_preamble("", "")
        assert "[Max]" in r
        assert "[Joy]" in r
        assert "실시간" in r

    def test_includes_no_retry_protocol(self, executor):
        r = executor._build_preamble("", "")
        assert "no_retry" in r

    def test_points_subagents_to_read_rules_themselves(self, executor):
        r = executor._build_preamble("", "")
        # 서브에이전트는 CLAUDE.md만 자동 로드되므로, 가드레일을 직접 읽으라는 포인터가 필요
        assert ".claude/rules" in r
        assert "직접 읽" in r

    def test_binds_pass_to_ac_exit_code(self, executor):
        r = executor._build_preamble("", "")
        assert "exit" in r.lower()

    # 기존 규약 보존 확인
    def test_still_includes_status_protocol(self, executor):
        r = executor._build_preamble("", "")
        assert "completed" in r
        assert "blocked" in r

    def test_lead_does_not_commit(self, executor):
        # 커밋은 하네스가 일원화 — 프리앰블은 리드에게 직접 커밋하지 말라고 한다(이중 커밋 방지).
        r = executor._build_preamble("", "")
        assert "커밋하지 마라" in r
        assert "feat(mvp):" not in r  # 더 이상 커밋 예시를 리드에게 주지 않는다

    def test_still_includes_freshness(self, executor):
        r = executor._build_preamble("", "")
        assert "rules-proposals.md" in r


# ---------------------------------------------------------------------------
# 팀 협업 — _invoke_claude 타임아웃 안전성 (terminal로 귀결, 미예외)
# ---------------------------------------------------------------------------

class TestInvokeClaudeTimeout:
    def test_timeout_does_not_raise(self, executor):
        step = {"step": 2, "name": "ui"}
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=10)):
            executor._invoke_claude(step, "preamble")  # 예외를 던지면 안 됨

    def test_timeout_returns_nonzero_exit(self, executor):
        step = {"step": 2, "name": "ui"}
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=10)):
            out = executor._invoke_claude(step, "preamble")
        assert out["exitCode"] != 0

    def test_timeout_message_in_stderr(self, executor):
        step = {"step": 2, "name": "ui"}
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=10)):
            out = executor._invoke_claude(step, "preamble")
        assert "timed out" in (out["stderr"] or "").lower()


# ---------------------------------------------------------------------------
# 팀 협업 — _execute_single_step 신호 주입 / 재시도 정합 / no_retry 단락
# ---------------------------------------------------------------------------

class TestExecuteSingleStepSignals:
    def _neuter(self, executor):
        """git/commit/top-index 부수효과 제거."""
        executor._commit_step = lambda *a, **k: None
        executor._update_top_index = lambda *a, **k: None
        executor._run_git = lambda *a, **k: MagicMock(returncode=0, stdout="", stderr="")

    def _set_status(self, executor, step_num, **fields):
        idx = json.loads(executor._index_file.read_text())
        for s in idx["steps"]:
            if s["step"] == step_num:
                s.update(fields)
        executor._index_file.write_text(json.dumps(idx, ensure_ascii=False))

    def test_unset_status_injects_stderr_and_exit_into_error(self, executor):
        self._neuter(executor)
        executor._invoke_claude = lambda step, preamble: {
            "step": step["step"], "name": step["name"],
            "exitCode": 2, "stdout": "", "stderr": "boom-traceback-XYZ",
        }
        with pytest.raises(SystemExit):
            executor._execute_single_step({"step": 2, "name": "ui"}, "guard")
        idx = json.loads(executor._index_file.read_text())
        err = next(s.get("error_message", "") for s in idx["steps"] if s["step"] == 2)
        assert "boom-traceback-XYZ" in err
        assert "exit 2" in err

    def test_error_with_no_retry_terminates_in_one_pass(self, executor):
        self._neuter(executor)
        calls = {"n": 0}

        def fake(step, preamble):
            calls["n"] += 1
            self._set_status(executor, step["step"],
                             status="error", error_message="unresolved", no_retry=True)
            return {"step": step["step"], "name": step["name"],
                    "exitCode": 0, "stdout": "", "stderr": ""}

        executor._invoke_claude = fake
        with pytest.raises(SystemExit):
            executor._execute_single_step({"step": 2, "name": "ui"}, "guard")
        assert calls["n"] == 1

    def test_plain_error_retries_to_outer_attempts(self, executor):
        self._neuter(executor)
        calls = {"n": 0}

        def fake(step, preamble):
            calls["n"] += 1
            self._set_status(executor, step["step"],
                             status="error", error_message="boom")
            return {"step": step["step"], "name": step["name"],
                    "exitCode": 1, "stdout": "", "stderr": "boom"}

        executor._invoke_claude = fake
        with pytest.raises(SystemExit):
            executor._execute_single_step({"step": 2, "name": "ui"}, "guard")
        assert calls["n"] == ex.StepExecutor.OUTER_ATTEMPTS

    def test_completed_status_returns_true_without_exit(self, executor):
        self._neuter(executor)

        def fake(step, preamble):
            self._set_status(executor, step["step"], status="completed", summary="done")
            return {"step": step["step"], "name": step["name"],
                    "exitCode": 0, "stdout": "", "stderr": ""}

        executor._invoke_claude = fake
        result = executor._execute_single_step({"step": 2, "name": "ui"}, "guard")
        assert result is True


# ---------------------------------------------------------------------------
# 팀 협업 — 하트비트 team_round 전파(단독 writer 불변식 보존)
# ---------------------------------------------------------------------------

class TestHeartbeatTeamRound:
    def test_copies_team_round_from_phase_index(self, executor, top_index):
        executor._top_index_file = top_index
        idx = json.loads(executor._index_file.read_text())
        idx["team_round"] = "2/3 IMPROVE"
        executor._index_file.write_text(json.dumps(idx, ensure_ascii=False))
        executor._write_heartbeat(2, "ui", attempt=1, done=2, elapsed=10)
        data = json.loads(top_index.read_text())
        mvp = next(p for p in data["phases"] if p["dir"] == "0-mvp")
        assert mvp.get("team_round") == "2/3 IMPROVE"

    def test_absent_team_round_is_fine(self, executor, top_index):
        executor._top_index_file = top_index
        executor._write_heartbeat(2, "ui", attempt=1, done=2, elapsed=10)
        data = json.loads(top_index.read_text())
        mvp = next(p for p in data["phases"] if p["dir"] == "0-mvp")
        assert "team_round" not in mvp

    def test_team_round_cleared_on_terminal(self, executor, top_index):
        data = json.loads(top_index.read_text())
        for p in data["phases"]:
            if p["dir"] == "0-mvp":
                p["status"] = "running"
                p["team_round"] = "1/3 IMPROVE"
        top_index.write_text(json.dumps(data))
        executor._top_index_file = top_index
        executor._update_top_index("completed")
        after = json.loads(top_index.read_text())
        mvp = next(p for p in after["phases"] if p["dir"] == "0-mvp")
        assert "team_round" not in mvp


# ---------------------------------------------------------------------------
# 팀 협업 — 에이전트 정의(.claude/agents) frontmatter (재사용 스캐폴드 검증)
# ---------------------------------------------------------------------------

class TestAgentDefinitions:
    AGENTS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "agents"

    def _frontmatter(self, name):
        text = (self.AGENTS_DIR / f"{name}.md").read_text(encoding="utf-8")
        assert text.startswith("---"), f"{name}.md must start with YAML frontmatter"
        fm = text.split("---", 2)[1]
        out = {}
        for line in fm.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip()
        return out

    def test_three_agent_files_exist(self):
        for name in ("max", "joy", "esther"):
            assert (self.AGENTS_DIR / f"{name}.md").exists(), f"{name}.md missing"

    def test_names_match_filenames(self):
        for name in ("max", "joy", "esther"):
            assert self._frontmatter(name)["name"] == name

    def test_all_models_opus_4_8(self):
        for name in ("max", "joy", "esther"):
            assert self._frontmatter(name)["model"] == "claude-opus-4-8"

    def test_colors(self):
        expected = {"max": "blue", "joy": "pink", "esther": "yellow"}
        for name, color in expected.items():
            assert self._frontmatter(name)["color"] == color

    def test_each_has_description(self):
        for name in ("max", "joy", "esther"):
            assert self._frontmatter(name).get("description")

    def test_joy_defines_verdict_sentinels(self):
        text = (self.AGENTS_DIR / "joy.md").read_text(encoding="utf-8")
        assert "VERDICT: PASS" in text
        assert "VERDICT: IMPROVE" in text

    def test_esther_references_ui_guide(self):
        text = (self.AGENTS_DIR / "esther.md").read_text(encoding="utf-8")
        assert "UI_GUIDE" in text

    def test_each_has_persona_and_self_chat_tag(self):
        for name in ("max", "joy", "esther"):
            text = (self.AGENTS_DIR / f"{name}.md").read_text(encoding="utf-8")
            assert "페르소나" in text, f"{name}.md에 페르소나 섹션이 없음"
            assert f"[{name.capitalize()}]" in text, f"{name}.md에 자기 대화 태그 예시가 없음"

    def test_joy_is_rules_guardian(self):
        text = (self.AGENTS_DIR / "joy.md").read_text(encoding="utf-8")
        assert "규칙 수호자" in text
        assert "rules-proposals" in text


# ---------------------------------------------------------------------------
# 팀 대화창 — chat_view 렌더링/팔로우
# ---------------------------------------------------------------------------

class TestChatView:
    def test_render_known_speaker_plain(self):
        out = cv.render_chat_line("[Max] adder 만들었어요", color=False)
        assert "Max" in out
        assert "adder 만들었어요" in out
        assert "│" in out

    def test_render_joy_and_lead(self):
        assert "Joy" in cv.render_chat_line("[Joy] 통과입니다", color=False)
        assert "리드" in cv.render_chat_line("[리드] 시작합니다", color=False)

    def test_render_strips_colon_after_bracket(self):
        out = cv.render_chat_line("[Max]: 안녕", color=False)
        assert "안녕" in out
        assert "│ : " not in out  # 선행 콜론 제거됨

    def test_render_color_adds_ansi(self):
        assert "\033[" in cv.render_chat_line("[Max] hi", color=True)

    def test_render_no_color_has_no_ansi(self):
        assert "\033[" not in cv.render_chat_line("[Max] hi", color=False)

    def test_render_unknown_speaker_keeps_text(self):
        assert "Bob" in cv.render_chat_line("[Bob] hi", color=False)

    @staticmethod
    def _bg_codes(s):
        import re
        codes = set()
        for seq in re.findall(r"\033\[([0-9;]+)m", s):
            for p in seq.split(";"):
                if p.isdigit() and (40 <= int(p) <= 47 or 100 <= int(p) <= 107):
                    codes.add(int(p))
        return frozenset(codes)

    def test_render_uses_background_color(self):
        # 사용자 요청: 이름을 '배경색 배지'로 구분한다.
        for spk in ("리드", "Max", "Joy", "Esther"):
            out = cv.render_chat_line(f"[{spk}] hi", color=True)
            assert self._bg_codes(out), f"{spk} 배지에 배경색 SGR이 없음"

    def test_render_speakers_have_distinct_backgrounds(self):
        seen = {spk: self._bg_codes(cv.render_chat_line(f"[{spk}] hi", color=True))
                for spk in ("리드", "Max", "Joy", "Esther")}
        assert len(set(seen.values())) == 4  # 4명 모두 다른 배경색

    def test_render_separator(self):
        assert "Step 0" in cv.render_chat_line("=== Step 0: adder ===", color=False)

    def test_render_empty_is_blank(self):
        assert cv.render_chat_line("   ", color=False) == ""

    def test_read_new_lines_basic(self, tmp_path):
        p = tmp_path / "chat.md"
        p.write_text("a\nb\n", encoding="utf-8")
        lines, count = cv.read_new_lines(str(p), 0)
        assert lines == ["a", "b"]
        assert count == 2

    def test_read_new_lines_incremental(self, tmp_path):
        p = tmp_path / "chat.md"
        p.write_text("a\nb\n", encoding="utf-8")
        _, count = cv.read_new_lines(str(p), 0)
        p.write_text("a\nb\nc\n", encoding="utf-8")
        lines, count = cv.read_new_lines(str(p), count)
        assert lines == ["c"]
        assert count == 3

    def test_read_new_lines_excludes_partial(self, tmp_path):
        p = tmp_path / "chat.md"
        p.write_text("a\nb", encoding="utf-8")  # b는 미완성(개행 없음)
        lines, count = cv.read_new_lines(str(p), 0)
        assert lines == ["a"]
        assert count == 1

    def test_read_new_lines_missing_file(self, tmp_path):
        lines, count = cv.read_new_lines(str(tmp_path / "nope.md"), 5)
        assert lines == []
        assert count == 5

    def test_follow_emits_new_lines_then_stops(self, tmp_path):
        import threading
        import time
        p = tmp_path / "chat.md"
        p.write_text("[Max] hi\n", encoding="utf-8")
        got = []
        stop = threading.Event()
        th = threading.Thread(target=cv.follow,
                              args=(str(p), stop, got.append),
                              kwargs={"interval": 0.02})
        th.start()
        time.sleep(0.1)
        with open(p, "a", encoding="utf-8") as f:
            f.write("[Joy] 통과\n")
        time.sleep(0.1)
        stop.set()
        th.join()
        assert "[Max] hi" in got
        assert "[Joy] 통과" in got


# ---------------------------------------------------------------------------
# 대화창 줄바꿈 — 긴 줄은 '...' 잘림 없이 터미널 폭에 맞춰 wrap (작은 모니터 대응)
# ---------------------------------------------------------------------------

class TestChatWrap:
    def test_long_line_wraps_not_truncates(self):
        msg = "가" * 80
        out = cv.render_chat_line(f"[Max] {msg}", color=False, width=40)
        assert "\n" in out            # 여러 줄로 줄바꿈됨
        assert "..." not in out        # 잘림 없음
        assert out.count("가") == 80    # 전체 텍스트 보존(한 글자도 안 잘림)

    def test_each_wrapped_line_within_width(self):
        msg = "가" * 80
        out = cv.render_chat_line(f"[Max] {msg}", color=False, width=40)
        for ln in out.split("\n"):
            assert cv._disp_width(ln) <= 40

    def test_short_line_does_not_wrap(self):
        out = cv.render_chat_line("[Max] 짧은 메시지", color=False, width=80)
        assert "\n" not in out

    def test_continuation_is_indented(self):
        msg = "나" * 80
        out = cv.render_chat_line(f"[Max] {msg}", color=False, width=40)
        cont = out.split("\n")[1]
        assert cont.startswith(" ")    # 이어지는 줄은 메시지 열에 맞춰 들여쓰기


# ---------------------------------------------------------------------------
# 대화창 색상 — FORCE_COLOR (파이프 실행 시에도 컬러 유지)
# ---------------------------------------------------------------------------

class TestUseColor:
    class _Stream:
        def __init__(self, tty):
            self._tty = tty
        def isatty(self):
            return self._tty

    def test_force_color_env_forces_on_even_when_piped(self, monkeypatch):
        monkeypatch.setenv("FORCE_COLOR", "1")
        assert ex.StepExecutor._use_color(self._Stream(tty=False)) is True

    def test_tty_is_on(self, monkeypatch):
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        assert ex.StepExecutor._use_color(self._Stream(tty=True)) is True

    def test_pipe_without_force_is_off(self, monkeypatch):
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        assert ex.StepExecutor._use_color(self._Stream(tty=False)) is False


# ---------------------------------------------------------------------------
# 팀 대화창 — watch.py phase 자동 감지
# ---------------------------------------------------------------------------

class TestWatch:
    def _write_top(self, tmp_path, phases):
        (tmp_path / "phases").mkdir(exist_ok=True)
        (tmp_path / "phases" / "index.json").write_text(
            json.dumps({"phases": phases}), encoding="utf-8")

    def test_detect_running_phase(self, tmp_path, monkeypatch):
        import watch
        self._write_top(tmp_path, [
            {"dir": "0-a", "status": "completed"},
            {"dir": "1-b", "status": "running"},
        ])
        monkeypatch.setattr(watch, "ROOT", tmp_path)
        assert watch._detect_running_phase() == "1-b"

    def test_detect_falls_back_to_last(self, tmp_path, monkeypatch):
        import watch
        self._write_top(tmp_path, [
            {"dir": "0-a", "status": "completed"},
            {"dir": "1-b", "status": "pending"},
        ])
        monkeypatch.setattr(watch, "ROOT", tmp_path)
        assert watch._detect_running_phase() == "1-b"

    def test_detect_none_when_no_index(self, tmp_path, monkeypatch):
        import watch
        monkeypatch.setattr(watch, "ROOT", tmp_path)
        assert watch._detect_running_phase() is None


# ---------------------------------------------------------------------------
# run.py — 하네스 백그라운드 + 라이브 컬러 뷰어 (한 방 런처)
# ---------------------------------------------------------------------------

class TestRunLauncher:
    def test_harness_cmd_targets_execute_unbuffered(self):
        import run as rn
        cmd = rn._harness_cmd("0-smoke")
        assert any("execute.py" in part for part in cmd)
        assert cmd[-1] == "0-smoke"
        assert "-u" in cmd  # 언버퍼드라야 tail이 실시간

    def test_use_color_force_env(self, monkeypatch):
        import run as rn
        monkeypatch.setenv("FORCE_COLOR", "1")

        class S:
            def isatty(self):
                return False
        assert rn._use_color(S()) is True

    def test_use_color_pipe_off(self, monkeypatch):
        import run as rn
        monkeypatch.delenv("FORCE_COLOR", raising=False)

        class S:
            def isatty(self):
                return False
        assert rn._use_color(S()) is False

    def test_drain_renders_new_lines(self, tmp_path):
        import run as rn
        p = tmp_path / "chat.md"
        p.write_text("[Max] 안녕\n[Joy] 통과\n", encoding="utf-8")
        rendered, count = rn._drain(p, 0, color=False)
        assert count == 2
        assert any("Max" in r for r in rendered)
        assert any("통과" in r for r in rendered)

    def test_drain_incremental_only_new(self, tmp_path):
        import run as rn
        p = tmp_path / "chat.md"
        p.write_text("[Max] a\n", encoding="utf-8")
        _, count = rn._drain(p, 0, color=False)
        p.write_text("[Max] a\n[Joy] b\n", encoding="utf-8")
        rendered, count = rn._drain(p, count, color=False)
        assert len(rendered) == 1
        assert "b" in rendered[0]


# ---------------------------------------------------------------------------
# chat.py — 상시 팀 대화창 (한 번 띄워두면 활성 phase의 하네스에 자동 연결)
# ---------------------------------------------------------------------------

class TestChatFollower:
    """phase에 묶이지 않는 상시 뷰어. 어떤 phase의 하네스가 돌든 그 대화로 따라간다.

    핵심 규칙: 시작 시점에 이미 있던 줄은 '본 것'으로 간주(옛 기록 덤프 방지),
    그 뒤로 쌓이는 줄만 라이브로 보여준다. mtime이 가장 최신인 chat.md가 '활성'.
    """

    def _chat(self, phases_dir, name, text, mtime):
        d = phases_dir / name
        d.mkdir(parents=True, exist_ok=True)
        c = d / "chat.md"
        c.write_text(text, encoding="utf-8")
        os.utime(c, (mtime, mtime))  # write 후에 설정해야 mtime이 안 덮인다
        return c

    def _join(self, lines):
        return "".join(lines)

    def test_freshest_picks_most_recently_written(self, tmp_path):
        import chat as ch
        phases = tmp_path / "phases"
        self._chat(phases, "0-a", "[Max] a\n", mtime=1000)
        self._chat(phases, "1-b", "[Joy] b\n", mtime=2000)
        name, path = ch._freshest_chat(phases)
        assert name == "1-b"
        assert path.name == "chat.md"

    def test_freshest_none_when_empty(self, tmp_path):
        import chat as ch
        (tmp_path / "phases").mkdir()
        assert ch._freshest_chat(tmp_path / "phases") == (None, None)

    def test_preexisting_history_not_dumped(self, tmp_path):
        import chat as ch
        phases = tmp_path / "phases"
        self._chat(phases, "0-a", "[Max] 옛날1\n[Joy] 옛날2\n", mtime=1000)
        f = ch.Follower(phases, color=False)
        assert f.poll() == []  # 시작 전 기록은 다시 안 뱉는다

    def test_new_appended_line_is_emitted_live(self, tmp_path):
        import chat as ch
        phases = tmp_path / "phases"
        c = self._chat(phases, "0-a", "[Max] 옛날\n", mtime=1000)
        f = ch.Follower(phases, color=False)
        assert f.poll() == []
        c.write_text("[Max] 옛날\n[Joy] 새거\n", encoding="utf-8")
        os.utime(c, (3000, 3000))
        out = self._join(f.poll())
        assert "새거" in out
        assert "옛날" not in out  # 옛 줄은 라이브로 재출력 안 함

    def test_banner_on_first_real_activity(self, tmp_path):
        import chat as ch
        phases = tmp_path / "phases"
        c = self._chat(phases, "2-mvp", "", mtime=1000)
        f = ch.Follower(phases, color=False)
        c.write_text("[리드] step 0 시작\n", encoding="utf-8")
        os.utime(c, (3000, 3000))
        out = self._join(f.poll())
        assert "2-mvp" in out  # 연결 배너에 phase 이름

    def test_switches_to_newly_active_phase(self, tmp_path):
        import chat as ch
        phases = tmp_path / "phases"
        a = self._chat(phases, "0-a", "[Max] a옛\n", mtime=1000)
        f = ch.Follower(phases, color=False)
        a.write_text("[Max] a옛\n[Max] a라이브\n", encoding="utf-8")
        os.utime(a, (2000, 2000))
        assert "a라이브" in self._join(f.poll())
        # 이제 다른 phase의 하네스가 새로 돌기 시작 (더 최신 mtime)
        self._chat(phases, "1-b", "[Joy] b라이브\n", mtime=3000)
        out = self._join(f.poll())
        assert "b라이브" in out
        assert "1-b" in out  # 전환 배너

    def test_new_phase_dir_after_start_shown_from_top(self, tmp_path):
        import chat as ch
        phases = tmp_path / "phases"
        self._chat(phases, "0-a", "[Max] a\n", mtime=1000)
        f = ch.Follower(phases, color=False)
        self._chat(phases, "1-new", "[리드] 안녕\n[Max] 시작\n", mtime=5000)
        out = self._join(f.poll())
        assert "안녕" in out and "시작" in out  # 시작 후 생긴 파일은 처음부터

    def test_no_double_emit_incremental(self, tmp_path):
        import chat as ch
        phases = tmp_path / "phases"
        c = self._chat(phases, "0-a", "", mtime=1000)
        f = ch.Follower(phases, color=False)
        c.write_text("[Max] 하나\n", encoding="utf-8")
        os.utime(c, (2000, 2000))
        f.poll()
        c.write_text("[Max] 하나\n[Max] 둘\n", encoding="utf-8")
        os.utime(c, (3000, 3000))
        out = self._join(f.poll())
        assert "둘" in out
        assert "하나" not in out  # 이미 본 줄 재출력 금지

    def test_use_color_force_env(self, monkeypatch):
        import chat as ch
        monkeypatch.setenv("FORCE_COLOR", "1")

        class S:
            def isatty(self):
                return False
        assert ch._use_color(S()) is True

    def test_use_color_pipe_off(self, monkeypatch):
        import chat as ch
        monkeypatch.delenv("FORCE_COLOR", raising=False)

        class S:
            def isatty(self):
                return False
        assert ch._use_color(S()) is False

    def test_banner_uses_color_when_enabled(self, tmp_path):
        import chat as ch
        phases = tmp_path / "phases"
        c = self._chat(phases, "0-a", "", mtime=1000)
        f = ch.Follower(phases, color=True)
        c.write_text("[Max] hi\n", encoding="utf-8")
        os.utime(c, (2000, 2000))
        out = self._join(f.poll())
        assert "\033[" in out  # 컬러 켜면 ANSI 포함


# ---------------------------------------------------------------------------
# execute.py --quiet — 인라인 대화 표시를 끈다 (상시 chat.py와 이중 표시 방지)
# ---------------------------------------------------------------------------

class TestQuietMode:
    """--quiet면 하네스는 chat.md에 기록은 계속하되, 자기 stdout으로는 대화를
    표시하지 않는다. 표시는 상시 뷰어(chat.py)가 전담한다."""

    def _mk(self, tmp_project, phase_dir, **kw):
        with patch.object(ex, "ROOT", tmp_project):
            inst = ex.StepExecutor("0-mvp", **kw)
        inst._phase_dir = phase_dir
        inst._phase_dir_name = "0-mvp"
        return inst

    def test_default_not_quiet(self, executor):
        assert executor._quiet is False

    def test_quiet_flag_stored(self, tmp_project, phase_dir):
        inst = self._mk(tmp_project, phase_dir, quiet=True)
        assert inst._quiet is True

    def test_quiet_tailer_does_not_spawn_follow(self, tmp_project, phase_dir, monkeypatch):
        inst = self._mk(tmp_project, phase_dir, quiet=True)
        called = {"n": 0}
        monkeypatch.setattr(cv, "follow",
                            lambda *a, **k: called.__setitem__("n", called["n"] + 1))
        with inst._chat_tailer():
            pass
        assert called["n"] == 0  # quiet면 인라인 표시 스레드를 안 띄운다

    def test_loud_tailer_spawns_follow(self, tmp_project, phase_dir, monkeypatch):
        inst = self._mk(tmp_project, phase_dir, quiet=False)
        ev = threading.Event()

        def fake_follow(path, stop, emit, **k):
            ev.set()
            stop.wait(0.05)
        monkeypatch.setattr(cv, "follow", fake_follow)
        with inst._chat_tailer():
            assert ev.wait(1.0)  # loud면 인라인 표시 스레드가 뜬다

    def test_cli_parses_quiet(self, monkeypatch):
        captured = {}

        class FakeExec:
            def __init__(self, phase, **kw):
                captured["phase"] = phase
                captured.update(kw)

            def run(self):
                pass
        monkeypatch.setattr(ex, "StepExecutor", FakeExec)
        monkeypatch.setattr(sys, "argv", ["execute.py", "0-mvp", "--quiet"])
        ex.main()
        assert captured["quiet"] is True

    def test_cli_default_quiet_false(self, monkeypatch):
        captured = {}

        class FakeExec:
            def __init__(self, phase, **kw):
                captured.update(kw)

            def run(self):
                pass
        monkeypatch.setattr(ex, "StepExecutor", FakeExec)
        monkeypatch.setattr(sys, "argv", ["execute.py", "0-mvp"])
        ex.main()
        assert captured["quiet"] is False


# ---------------------------------------------------------------------------
# index.json 입력 검증 + phase 정규화 (#9, #13) — 손편집 권장 파일을 기동 시 검증
# ---------------------------------------------------------------------------

class TestIndexValidation:
    def _construct(self, tmp_project, index):
        d = tmp_project / "phases" / "0-mvp"
        d.mkdir(parents=True, exist_ok=True)
        content = index if isinstance(index, str) else json.dumps(index)
        (d / "index.json").write_text(content, encoding="utf-8")
        with patch.object(ex, "ROOT", tmp_project):
            return ex.StepExecutor("0-mvp")

    def test_valid_index_ok(self, tmp_project):
        inst = self._construct(tmp_project, {"phase": "mvp",
                "steps": [{"step": 0, "name": "a", "status": "pending"}]})
        assert inst._total == 1

    def test_malformed_json_exits(self, tmp_project):
        with pytest.raises(SystemExit):
            self._construct(tmp_project, "{not valid json")

    def test_missing_steps_exits(self, tmp_project):
        with pytest.raises(SystemExit):
            self._construct(tmp_project, {"phase": "mvp"})

    def test_empty_steps_exits(self, tmp_project):
        with pytest.raises(SystemExit):
            self._construct(tmp_project, {"phase": "mvp", "steps": []})

    def test_duplicate_step_num_exits(self, tmp_project):
        with pytest.raises(SystemExit):
            self._construct(tmp_project, {"phase": "mvp", "steps": [
                {"step": 0, "name": "a", "status": "pending"},
                {"step": 0, "name": "b", "status": "pending"}]})

    def test_invalid_status_exits(self, tmp_project):
        with pytest.raises(SystemExit):
            self._construct(tmp_project, {"phase": "mvp",
                "steps": [{"step": 0, "name": "a", "status": "done"}]})

    def test_step_not_int_exits(self, tmp_project):
        with pytest.raises(SystemExit):
            self._construct(tmp_project, {"phase": "mvp",
                "steps": [{"step": "0", "name": "a", "status": "pending"}]})

    def test_unsafe_phase_name_exits(self, tmp_project):
        with pytest.raises(SystemExit):
            self._construct(tmp_project, {"phase": "bad name!",
                "steps": [{"step": 0, "name": "a", "status": "pending"}]})


# ---------------------------------------------------------------------------
# 동시 실행 락 (#2) — 공유 워킹트리 손상 방지
# ---------------------------------------------------------------------------

class TestConcurrencyLock:
    def _exec(self, tmp_project):
        d = tmp_project / "phases" / "0-mvp"
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.json").write_text(json.dumps(
            {"phase": "mvp", "steps": [{"step": 0, "name": "a", "status": "pending"}]}))
        with patch.object(ex, "ROOT", tmp_project):
            return ex.StepExecutor("0-mvp")

    def test_pid_alive_self(self):
        assert ex.StepExecutor._pid_alive(os.getpid()) is True

    def test_pid_alive_dead(self):
        assert ex.StepExecutor._pid_alive(2 ** 31 - 1) is False

    def test_acquire_creates_and_release_removes(self, tmp_project):
        inst = self._exec(tmp_project)
        inst._acquire_lock()
        assert (tmp_project / ".harness.lock").exists()
        inst._release_lock()
        assert not (tmp_project / ".harness.lock").exists()

    def test_second_acquire_blocks_when_holder_alive(self, tmp_project):
        inst1 = self._exec(tmp_project)
        inst2 = self._exec(tmp_project)
        inst1._acquire_lock()
        try:
            with pytest.raises(SystemExit):
                inst2._acquire_lock()  # 살아있는 보유자(이 프로세스) → 차단
        finally:
            inst1._release_lock()

    def test_stale_lock_taken_over(self, tmp_project):
        (tmp_project / ".harness.lock").write_text(json.dumps(
            {"pid": 2 ** 31 - 1, "phase": "x", "started_at": "t"}))
        inst = self._exec(tmp_project)
        inst._acquire_lock()  # 죽은 pid → stale → takeover (예외 없음)
        holder = json.loads((tmp_project / ".harness.lock").read_text())
        assert holder["pid"] == os.getpid()
        inst._release_lock()


# ---------------------------------------------------------------------------
# 관측성·CLI preflight·detach (#12)
# ---------------------------------------------------------------------------

class TestObservability:
    def test_result_detail_parses_error(self):
        env = json.dumps({"type": "result", "subtype": "error_max_turns",
                          "is_error": True, "result": "turn limit reached"})
        d = ex.StepExecutor._result_detail(env)
        assert "error_max_turns" in d and "turn limit reached" in d

    def test_result_detail_parses_success_result(self):
        env = json.dumps({"subtype": "success", "is_error": False, "result": "done ok"})
        d = ex.StepExecutor._result_detail(env)
        assert "done ok" in d

    def test_result_detail_non_json_empty(self):
        assert ex.StepExecutor._result_detail("not json at all") == ""
        assert ex.StepExecutor._result_detail("") == ""

    def test_preflight_missing_exits(self, monkeypatch):
        monkeypatch.setattr(ex.shutil, "which", lambda c: None)
        with pytest.raises(SystemExit):
            ex.StepExecutor._preflight()

    def test_preflight_present_ok(self, monkeypatch):
        monkeypatch.setattr(ex.shutil, "which", lambda c: "/usr/bin/claude")
        ex.StepExecutor._preflight()  # 예외 없음


class TestRunDetach:
    def test_spawn_kwargs_detaches(self):
        import run as rn
        assert rn._spawn_kwargs().get("start_new_session") is True


# ---------------------------------------------------------------------------
# 스킬 배선 + cross-step 규칙 제안 (#6, #11)
# ---------------------------------------------------------------------------

class TestSkillWiringAndProposals:
    def test_preamble_points_to_skills(self, executor):
        p = executor._build_preamble("GR", "", None)
        assert ".claude/skills/" in p   # preamble이 스킬을 명시 (페르소나 prose에만 의존하지 않음)

    def test_preamble_includes_prior_proposals(self, executor, phase_dir):
        (phase_dir / "rules-proposals.md").write_text(
            "- 제안: 항상 ABC (근거: DEF)\n", encoding="utf-8")
        p = executor._build_preamble("GR", "", None)
        assert "항상 ABC" in p           # Joy가 직전 제안을 보고 중복/2번째 발생 인지

    def test_preamble_no_proposals_section_when_absent(self, executor):
        p = executor._build_preamble("GR", "", None)
        assert "이미 제안된 규칙" not in p


# ---------------------------------------------------------------------------
# 미작성 플레이스홀더 가드 (#4)
# ---------------------------------------------------------------------------

class TestPlaceholderGuard:
    def test_finds_korean_placeholders(self, executor, tmp_project):
        (tmp_project / "CLAUDE.md").write_text("# 프로젝트: {프로젝트명}\n개요: {한두 문장}\n", encoding="utf-8")
        with patch.object(ex, "ROOT", tmp_project):
            ph = executor._unfilled_placeholders()
        assert any("프로젝트명" in p for p in ph)

    def test_ignores_code_braces(self, executor, tmp_project):
        (tmp_project / "CLAUDE.md").write_text('cfg = { "key": 1 }\nfn() { return 0; }\n', encoding="utf-8")
        with patch.object(ex, "ROOT", tmp_project):
            ph = executor._unfilled_placeholders()
        assert ph == []

    def test_filled_has_no_placeholders(self, executor, tmp_project):
        (tmp_project / "CLAUDE.md").write_text("# 프로젝트: MyApp\n개요: 실시간 채팅 앱.\n", encoding="utf-8")
        with patch.object(ex, "ROOT", tmp_project):
            ph = executor._unfilled_placeholders()
        assert ph == []


# ---------------------------------------------------------------------------
# 뷰어 정확성 (#10) — chat.md 회전 + watch.py 하트비트 신선도
# ---------------------------------------------------------------------------

class TestViewerAccuracy:
    def test_read_new_lines_shrink_resyncs_no_replay(self, tmp_path):
        p = tmp_path / "c.md"
        p.write_text("a\nb\nc\nd\n", encoding="utf-8")
        _, count = cv.read_new_lines(str(p), 0)
        assert count == 4
        p.write_text("x\n", encoding="utf-8")          # truncate → 1줄
        new, count2 = cv.read_new_lines(str(p), count)
        assert new == []                                # 옛 줄 재생 안 함
        assert count2 == 1                              # 새 끝으로 resync
        p.write_text("x\ny\n", encoding="utf-8")        # 이후 append
        new3, _ = cv.read_new_lines(str(p), count2)
        assert new3 == ["y"]                            # append는 정상 표시

    def _write_top(self, tmp_path, phases):
        (tmp_path / "phases").mkdir(exist_ok=True)
        (tmp_path / "phases" / "index.json").write_text(
            json.dumps({"phases": phases}), encoding="utf-8")

    def test_fresh_running_returned(self, tmp_path, monkeypatch):
        import watch
        self._write_top(tmp_path, [
            {"dir": "1-b", "status": "running", "heartbeat_at": "2020-01-01T00:00:30+0900"}])
        monkeypatch.setattr(watch, "ROOT", tmp_path)
        now = datetime(2020, 1, 1, 0, 1, 0, tzinfo=timezone(timedelta(hours=9)))  # +30s
        assert watch._detect_running_phase(now=now) == "1-b"

    def test_stale_running_falls_back_to_freshest_chat(self, tmp_path, monkeypatch):
        import watch
        self._write_top(tmp_path, [
            {"dir": "0-a", "status": "completed"},
            {"dir": "1-b", "status": "running", "heartbeat_at": "2020-01-01T00:00:00+0900"}])
        (tmp_path / "phases" / "0-a").mkdir(parents=True, exist_ok=True)
        (tmp_path / "phases" / "0-a" / "chat.md").write_text("x", encoding="utf-8")
        monkeypatch.setattr(watch, "ROOT", tmp_path)
        now = datetime(2020, 1, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=9)))  # +1h → stale
        assert watch._detect_running_phase(now=now) == "0-a"

    def test_no_heartbeat_trusts_status(self, tmp_path, monkeypatch):
        import watch
        self._write_top(tmp_path, [
            {"dir": "0-a", "status": "completed"},
            {"dir": "1-b", "status": "running"}])  # 하트비트 없음 → status 신뢰 (backward compat)
        monkeypatch.setattr(watch, "ROOT", tmp_path)
        assert watch._detect_running_phase() == "1-b"


# ---------------------------------------------------------------------------
# settings.json 훅 — 스택 중립 Stop · 보강된 Bash 가드 (#7, #8)
# ---------------------------------------------------------------------------

class TestSettingsHooks:
    def _settings(self):
        return json.loads((ex.ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))

    def test_stop_hook_is_stack_neutral(self):
        cmd = self._settings()["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert "npm" not in cmd  # 기본 no-op(스택 중립), npm 하드코딩 제거

    def test_bash_guard_broadened_and_no_false_positive(self):
        cmd = self._settings()["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        assert "--recursive" in cmd          # rm 변형까지 broaden
        assert "delete" in cmd               # find ... -delete
        assert "with-lease" not in cmd       # --force-with-lease 오탐 차단(명시 제외 안 함)


# ---------------------------------------------------------------------------
# Task 2: _chat_verify_meta — step 완료 시 검수 메타 줄 chat.md에 기계 append
# ---------------------------------------------------------------------------

def _make_executor(tmp_path, steps):
    """테스트용 StepExecutor 인스턴스(phase dir + index.json + chat.md 구성)."""
    d = tmp_path / "phases" / "test-phase"
    d.mkdir(parents=True, exist_ok=True)
    index = {"project": "T", "phase": "test", "steps": steps}
    (d / "index.json").write_text(json.dumps(index, ensure_ascii=False))
    (d / "chat.md").write_text("", encoding="utf-8")  # chat.md 빈 파일로 초기화

    with patch.object(ex, "ROOT", tmp_path):
        inst = ex.StepExecutor.__new__(ex.StepExecutor)
    inst._root = str(tmp_path)
    inst._phases_dir = tmp_path / "phases"
    inst._phase_dir = d
    inst._phase_dir_name = "test-phase"
    inst._index_file = d / "index.json"
    inst._top_index_file = tmp_path / "phases" / "index.json"
    inst._phase_name = "test"
    inst._total = len(steps)
    inst._project = "T"
    return inst


class TestChatVerifyMeta:
    def test_chat_verify_meta_appends_round_fact(self, tmp_path, monkeypatch):
        # 기존 테스트와 동일한 방식으로 executor를 만든다(phase dir + index.json + chat.md).
        ex_inst = _make_executor(tmp_path, steps=[{"step": 0, "name": "x", "status": "completed",
                                              "team_round": "1/3 PASS"}])
        step_obj = {"step": 0, "name": "x", "team_round": "1/3 PASS"}
        ex_inst._chat_verify_meta(step_obj)
        chat = ex_inst._chat_path().read_text(encoding="utf-8")
        assert "[검수·meta] round=1/3 PASS" in chat

    def test_chat_verify_meta_noop_without_round(self, tmp_path, monkeypatch):
        ex_inst = _make_executor(tmp_path, steps=[{"step": 0, "name": "x", "status": "completed"}])
        before = ex_inst._chat_path().read_text(encoding="utf-8") if ex_inst._chat_path().exists() else ""
        ex_inst._chat_verify_meta({"step": 0, "name": "x"})   # team_round 없음
        after = ex_inst._chat_path().read_text(encoding="utf-8") if ex_inst._chat_path().exists() else ""
        assert before == after                            # 아무것도 추가하지 않음


# ---------------------------------------------------------------------------
# Task 3: _build_preamble — 게이팅 룰 + 생산자 메타 규약 + 핸드오프 규약
# ---------------------------------------------------------------------------

def test_preamble_has_gating_and_meta_handoff(tmp_path):
    ex_inst = _make_executor(tmp_path, steps=[{"step": 0, "name": "x", "status": "pending"}])
    p = ex_inst._build_preamble("guard", "ctx", None)
    assert "trivial" in p and "standard" in p and "complex" in p   # 난이도 게이팅 룰
    assert "·meta]" in p                                            # 생산자 메타 규약 예시
    assert "handoff.md" in p                                        # 핸드오프 계약 파일
    assert "Joy" in p and "항상" in p                               # 검수는 난이도 무관 항상
