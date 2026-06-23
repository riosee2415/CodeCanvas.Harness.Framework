#!/usr/bin/env python3
"""하네스를 백그라운드로 돌리고, 팀 대화를 실시간 컬러로 보여주는 한 방 런처.

사용법:
    python3 scripts/run.py <phase-dir>

- execute.py(하네스)를 **백그라운드 자식 프로세스**로 실행 → 콘솔 출력은
  `phases/<phase>/harness.log`로 숨긴다 (사용자는 하네스 기계장치를 안 본다).
- 같은 터미널에 `chat.md`를 tail하며 **배경색 이름 배지로 실시간 렌더** → 대화만 흐른다.
- 하네스가 끝나면 뷰어도 종료하고 최종 결과를 출력한다.

가장 좋은 화면: **당신 터미널에서 직접 실행**하면 풀스크린 진짜 컬러 라이브 대화창이 된다.
(긴 줄은 터미널 폭에 맞춰 줄바꿈되어 '...' 잘림 없이 전부 보인다 — 작은 모니터 대응.)
"""
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chat_view

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent


def _use_color(stream=None) -> bool:
    """tty이거나 FORCE_COLOR가 설정되면 컬러를 켠다 (파이프 실행 대응)."""
    stream = stream or sys.stdout
    return bool(os.environ.get("FORCE_COLOR")) or stream.isatty()


def _harness_cmd(phase: str) -> list:
    """백그라운드로 띄울 execute.py 커맨드 (언버퍼드 → 실시간 chat.md 기록)."""
    return [sys.executable, "-u", str(SCRIPTS / "execute.py"), phase]


def _spawn_kwargs() -> dict:
    """하네스 자식을 새 세션으로 분리(detach)한다 — 뷰어(부모)가 SIGHUP으로 죽어도
    하네스는 살아남아 step 경계까지 진행한다. 사용자는 watch.py/chat.py로 재접속 가능."""
    return {"start_new_session": True}


def _drain(path, count: int, color: bool):
    """chat.md의 새 줄을 읽어 (렌더된 줄 리스트, 갱신된 count)를 반환한다."""
    raw, count = chat_view.read_new_lines(str(path), count)
    rendered = []
    for ln in raw:
        r = chat_view.render_chat_line(ln, color=color)
        if r:
            rendered.append(r)
    return rendered, count


def _banner(phase: str, color: bool):
    title = f"💼 팀 라이브 — {phase}   (하네스는 뒤에서 돌고, 대화만 흐릅니다)"
    print(f"\033[1;36m{title}\033[0m\n" if color else title + "\n", flush=True)


def _footer(phase: str, rc: int, color: bool):
    if rc == 0:
        msg = f"✅ phase '{phase}' 완료 (exit 0)"
        col = "\033[1;32m"
    else:
        msg = f"⚠ phase '{phase}' 종료 (exit {rc}) — 자세한 로그: phases/{phase}/harness.log"
        col = "\033[1;33m"
    print(f"\n{col}{msg}\033[0m" if color else "\n" + msg, flush=True)


def main():
    if len(sys.argv) < 2:
        print("사용법: python3 scripts/run.py <phase-dir>", file=sys.stderr)
        sys.exit(1)
    phase = sys.argv[1]
    phase_dir = ROOT / "phases" / phase
    if not phase_dir.is_dir():
        print(f"ERROR: {phase_dir} 없음", file=sys.stderr)
        sys.exit(1)

    chat = phase_dir / "chat.md"
    log = phase_dir / "harness.log"
    color = _use_color()

    # 1) 하네스를 백그라운드 자식 프로세스로 — 콘솔은 로그 파일로 숨긴다.
    with open(log, "w", encoding="utf-8") as logf:
        proc = subprocess.Popen(_harness_cmd(phase), cwd=str(ROOT),
                                stdout=logf, stderr=subprocess.STDOUT,
                                **_spawn_kwargs())
        _banner(phase, color)

        # 2) chat.md를 tail → 실시간 컬러 렌더. 하네스가 끝나면 종료.
        count = 0
        try:
            while True:
                rendered, count = _drain(chat, count, color)
                for r in rendered:
                    print(r, flush=True)
                if proc.poll() is not None:
                    time.sleep(0.3)  # 종료 직전 잔여분 flush
                    rendered, count = _drain(chat, count, color)
                    for r in rendered:
                        print(r, flush=True)
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            proc.terminate()
            print("\n중단됨.", flush=True)
            return

    _footer(phase, proc.returncode, color)
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
