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
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chat_view

ROOT = Path(__file__).resolve().parent.parent
HEARTBEAT_STALE_SECONDS = 120  # 하트비트(60초 주기)가 이보다 멈춰 있으면 죽은 phase로 본다


def _heartbeat_fresh(hb_str, now) -> bool:
    """heartbeat_at가 신선한지. 없거나 파싱 불가면 status를 신뢰(True)."""
    if not hb_str:
        return True
    try:
        hb = datetime.strptime(hb_str, "%Y-%m-%dT%H:%M:%S%z")
    except (ValueError, TypeError):
        return True
    return (now - hb).total_seconds() <= HEARTBEAT_STALE_SECONDS


def _freshest_chat_dir():
    """phases/*/chat.md 중 mtime이 가장 최신인 phase 디렉토리명 (없으면 None)."""
    phases_dir = ROOT / "phases"
    best, best_m = None, -1.0
    if phases_dir.is_dir():
        for d in sorted(phases_dir.iterdir()):
            try:
                m = (d / "chat.md").stat().st_mtime
            except OSError:
                continue
            if m > best_m:
                best, best_m = d.name, m
    return best


def _detect_running_phase(now=None):
    """running phase를 반환하되, 하트비트가 멈춘 '죽은 running'은 신뢰하지 않는다.

    우선순위: ① 하트비트 신선한 running → ② 가장 최근에 쓰인 chat.md → ③ 마지막 phase.
    """
    top = ROOT / "phases" / "index.json"
    if not top.exists():
        return None
    try:
        data = json.loads(top.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    phases = data.get("phases", [])
    if not phases:
        return None
    if now is None:
        now = datetime.now(timezone(timedelta(hours=9)))
    for p in phases:
        if p.get("status") == "running" and _heartbeat_fresh(p.get("heartbeat_at"), now):
            return p.get("dir")
    return _freshest_chat_dir() or phases[-1].get("dir")


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
