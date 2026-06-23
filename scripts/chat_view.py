"""팀 대화창 렌더링 — 에이전트들의 실시간 대화를 채팅처럼 보여준다.

execute.py(실행 중 인라인 기본값)와 watch.py(별도 뷰어)가 공유한다.
chat.md의 각 줄은 `[speaker] message` 형식이며, speaker는 리드/Max/Joy/Esther.
"""

import unicodedata
from pathlib import Path

RESET = "\033[0m"
DIM = "\033[2m"

# speaker -> (emoji, 배지 ANSI(글자색;배경색), 표시이름).
# 사람마다 '배경색 이름 배지'로 구분한다 — 한눈에 누가 말하는지 보이게.
# 배경색은 .claude/agents 정의의 color와 맞춘다(리드=cyan/Max=blue/Joy=pink/Esther=yellow).
SPEAKERS = {
    "리드":   ("🧭", "\033[1;30;46m", "리드"),    # cyan 배경 · 검정 글자 (오케스트레이터)
    "Max":    ("🔵", "\033[97;44m",   "Max"),     # blue 배경 · 흰 글자
    "Joy":    ("🩷", "\033[97;45m",   "Joy"),      # magenta(pink) 배경 · 흰 글자
    "Esther": ("🟡", "\033[30;43m",   "Esther"),  # yellow 배경 · 검정 글자
}


def _disp_width(s: str) -> int:
    """문자열의 터미널 표시 폭 (CJK·전각은 2칸). 배지 정렬용."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def render_chat_line(raw: str, color: bool = True) -> str:
    """원시 대화 로그 한 줄을 채팅 형식으로 렌더한다.

    "[Max] 안녕"  ->  "🔵 [파랑 배경] Max    [reset] │ 안녕" (이름에 배경색 배지)
    빈 줄 -> "" (생략), 구분선/기타 -> dim 처리.
    """
    line = raw.rstrip("\n")
    if not line.strip():
        return ""

    if line.startswith("[") and "]" in line:
        speaker, _, msg = line[1:].partition("]")
        speaker = speaker.strip()
        msg = msg.lstrip(": ").rstrip()
        if speaker in SPEAKERS:
            emoji, badge, name = SPEAKERS[speaker]
            inner = name + " " * (6 - _disp_width(name))  # 이름 표시폭을 6으로 패딩
            if color:
                return f"{emoji} {badge} {inner} {RESET} │ {msg}"
            return f"{emoji} {inner} │ {msg}"

    # 구분선(=== Step N ===) 또는 형식 외 줄
    if color:
        return f"{DIM}{line}{RESET}"
    return line


def read_new_lines(path, count: int):
    """path의 '완성된(개행으로 끝난) 줄' 중 count번째 이후를 반환한다.

    반환: (새 줄 리스트, 갱신된 count). 파일이 없으면 ([], count).
    미완성(마지막 개행 없는) 줄은 다음 호출로 미룬다 — 부분 기록 중 깨진 줄 방지.
    """
    p = Path(path)
    if not p.exists():
        return [], count
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], count
    # split("\n")의 마지막 요소는 항상 '마지막 개행 이후'(완성 시 빈 문자열, 미완성 시 부분 줄)
    complete = text.split("\n")[:-1]
    if count > len(complete):  # 파일이 교체/축소됨 -> 처음부터
        count = 0
    new = complete[count:]
    return new, count + len(new)


def follow(path, stop_event, emit, interval: float = 0.5, start_count: int = 0):
    """stop_event가 set될 때까지 path의 새 줄을 polling하여 emit(line)을 호출한다.

    start_count: 이 값 이후의 줄만 emit (실행 중 인라인 뷰어가 '이번 step'만 보이게 할 때 사용).
    """
    count = start_count
    while True:
        lines, count = read_new_lines(path, count)
        for ln in lines:
            emit(ln)
        if stop_event.wait(interval):
            break
    lines, count = read_new_lines(path, count)  # 종료 직전 잔여분 flush
    for ln in lines:
        emit(ln)
