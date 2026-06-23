#!/usr/bin/env python3
"""상시(always-on) 팀 대화창 — 한 번 띄워두면 어떤 phase의 하네스가 돌든 그 대화가 흐른다.

사용법:
    python3 scripts/chat.py        # 띄워두면 끝. 활성 phase를 자동으로 따라간다.

phase에 묶이지 않는다 (run.py/watch.py는 phase 하나에 고정). 동작:
- `phases/*/chat.md` 중 **지금 가장 최근에 쓰이는** 파일(=활성 하네스)을 따라간다.
- 하네스를 새로 돌리면(어떤 phase든) 그 대화로 **자동 전환** — 전환 시 배너 표시.
- 하네스가 끝나도 뷰어는 살아있다 — 다음 하네스를 계속 기다린다 (Ctrl-C로 종료).

핵심 규칙: **시작 시점에 이미 있던 줄은 '본 것'으로 간주**한다(옛 기록 덤프 방지).
그 뒤로 chat.md에 쌓이는 새 줄만 라이브로, 배경색 배지 + 줄바꿈으로 보여준다.

전제: 한 번에 하네스 하나만 돈다(execute.py가 phase별 git 브랜치로 전환하므로).
따라서 '가장 최근에 쓰인 chat.md = 유일한 활성 대화'로 모호함이 없다.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chat_view

ROOT = Path(__file__).resolve().parent.parent
PHASES = ROOT / "phases"


def _use_color(stream=None) -> bool:
    """tty이거나 FORCE_COLOR가 설정되면 컬러를 켠다 (파이프 실행 대응)."""
    stream = stream or sys.stdout
    return bool(os.environ.get("FORCE_COLOR")) or stream.isatty()


def _all_chats(phases_dir):
    """phases/*/chat.md 목록을 (phase이름, Path)로 반환 (존재하는 것만, 이름순)."""
    p = Path(phases_dir)
    if not p.is_dir():
        return []
    out = []
    for d in sorted(p.iterdir()):
        if d.is_dir():
            c = d / "chat.md"
            if c.exists():
                out.append((d.name, c))
    return out


def _freshest_chat(phases_dir):
    """phases/*/chat.md 중 mtime이 가장 최신인 (phase이름, Path). 없으면 (None, None)."""
    best = None  # (mtime, name, path)
    for name, path in _all_chats(phases_dir):
        try:
            m = path.stat().st_mtime
        except OSError:
            continue
        if best is None or m > best[0]:
            best = (m, name, path)
    if best is None:
        return None, None
    return best[1], best[2]


class Follower:
    """활성 chat.md를 따라가며 '새로 쌓인 줄'만 렌더해 내보내는 상태기.

    poll()을 주기적으로 호출하면, 그 사이 활성 대화에 추가된 줄을 렌더한 문자열
    리스트를 돌려준다. 활성 파일이 바뀌면 맨 앞에 전환 배너를 끼운다.
    """

    def __init__(self, phases_dir, color=True):
        self.phases_dir = Path(phases_dir)
        self.color = color
        self.seen = {}      # str(path) -> 이미 내보낸 줄 수
        self.current = None  # str(path) — 마지막으로 줄을 내보낸 파일
        # 시작 시점에 이미 존재하는 chat.md의 모든 줄은 '본 것'으로 표시 → 옛 기록 덤프 방지.
        for _, path in _all_chats(self.phases_dir):
            _, n = chat_view.read_new_lines(str(path), 0)
            self.seen[str(path)] = n

    def _banner(self, name):
        msg = f"┄┄┄ 📥 '{name}' 하네스에 연결됨 ┄┄┄"
        return f"\033[1;36m{msg}\033[0m" if self.color else msg

    def poll(self):
        """활성 chat.md의 새 줄을 렌더해 리스트로 반환 (전환 시 배너 포함, 없으면 [])."""
        name, path = _freshest_chat(self.phases_dir)
        if path is None:
            return []
        sp = str(path)
        if sp not in self.seen:           # 시작 후 새로 생긴 파일 = 전부 새 내용
            self.seen[sp] = 0
        raw, n = chat_view.read_new_lines(sp, self.seen[sp])
        self.seen[sp] = n
        rendered = [r for r in (chat_view.render_chat_line(ln, color=self.color)
                                for ln in raw) if r]
        if not rendered:                  # 죽은/유휴 phase로 헛전환하지 않는다
            return []
        out = []
        if sp != self.current:            # 활성 대화가 다른 파일로 옮겨갈 때만 알림
            out.append(self._banner(name))
            self.current = sp
        out.extend(rendered)
        return out


def main():
    color = _use_color()
    title = "💬 팀 상시 대화창 — 활성 하네스를 기다리는 중… (Ctrl-C로 종료)"
    print(f"\033[1;36m{title}\033[0m\n" if color else title + "\n", flush=True)

    follower = Follower(PHASES, color=color)
    try:
        while True:
            for line in follower.poll():
                print(line, flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n대화창을 닫습니다.", flush=True)


if __name__ == "__main__":
    main()
