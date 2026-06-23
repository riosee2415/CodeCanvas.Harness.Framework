"""
execute.py 리팩터링 안전망 테스트.
리팩터링 전후 동작이 동일한지 검증한다.
"""

import json
import os
import subprocess
import sys
import textwrap
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

    def test_includes_commit_example(self, executor):
        result = executor._build_preamble("", "")
        assert "feat(mvp):" in result

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
            if args[:2] == ("diff", "--cached"):
                call_count["diff"] += 1
                if call_count["diff"] == 1:
                    return MagicMock(returncode=0)
                return MagicMock(returncode=1)
            return MagicMock(returncode=0, stdout="", stderr="")
        executor._run_git = fake_git

        executor._commit_step(2, "ui")

        commit_msgs = [c[2] for c in calls if c[0] == "commit"]
        assert len(commit_msgs) == 1
        assert "chore" in commit_msgs[0]


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

    def test_still_includes_commit_example(self, executor):
        r = executor._build_preamble("", "")
        assert "feat(mvp):" in r

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
