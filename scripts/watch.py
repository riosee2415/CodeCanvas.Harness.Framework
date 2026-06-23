#!/usr/bin/env python3
"""팀 대화창 뷰어 — phase의 chat.md를 채팅처럼 실시간으로 본다 (별도 터미널용).

사용법:
    python3 scripts/watch.py [phase-dir]

phase-dir 생략 시 phases/index.json에서 status=running인 phase를 자동 감지한다.
기존 대화를 모두 출력한 뒤 새 메시지를 따라 출력한다. Ctrl-C로 종료.
"""

import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chat_view

ROOT = Path(__file__).resolve().parent.parent


def _detect_running_phase():
    """phases/index.json에서 running phase를, 없으면 마지막 phase를 반환."""
    top = ROOT / "phases" / "index.json"
    if not top.exists():
        return None
    try:
        data = json.loads(top.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    phases = data.get("phases", [])
    for p in phases:
        if p.get("status") == "running":
            return p.get("dir")
    return phases[-1].get("dir") if phases else None


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    phase = arg or _detect_running_phase()
    if not phase:
        print("phase를 찾을 수 없습니다. 사용법: python3 scripts/watch.py <phase-dir>",
              file=sys.stderr)
        sys.exit(1)

    chat = ROOT / "phases" / phase / "chat.md"
    color = sys.stdout.isatty()
    print(f"💬 팀 대화창 — {phase}  (Ctrl-C 종료)\n")

    stop = threading.Event()

    def emit(line):
        rendered = chat_view.render_chat_line(line, color=color)
        if rendered:
            print(rendered)

    try:
        chat_view.follow(str(chat), stop, emit, start_count=0)
    except KeyboardInterrupt:
        stop.set()
        print("\n(종료)")


if __name__ == "__main__":
    main()
