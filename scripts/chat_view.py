"""팀 대화창 렌더링 — 에이전트들의 실시간 대화를 채팅처럼 보여준다.

execute.py(실행 중 인라인 기본값)와 watch.py(별도 뷰어)가 공유한다.
chat.md의 각 줄은 `[speaker] message` 형식이며, speaker는 리드/Max/Joy/Esther.
"""

from pathlib import Path

RESET = "\033[0m"
DIM = "\033[2m"

# speaker -> (emoji, ANSI color, 표시이름). 색은 에이전트 정의(.claude/agents)의 color와 맞춘다.
SPEAKERS = {
    "리드": ("🧭", "\033[1;36m", "리드"),    # cyan bold (오케스트레이터)
    "Max": ("🔵", "\033[34m", "Max"),        # blue
    "Joy": ("🩷", "\033[35m", "Joy"),        # magenta(pink)
    "Esther": ("🟡", "\033[33m", "Esther"),  # yellow
}


def render_chat_line(raw: str, color: bool = True) -> str:
    """원시 대화 로그 한 줄을 채팅 형식으로 렌더한다.

    "[Max] 안녕"  ->  "🔵 Max    │ 안녕"
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
            emoji, col, name = SPEAKERS[speaker]
            label = f"{emoji} {name.ljust(6)}"
            if color:
                return f"{col}{label}{RESET} │ {msg}"
            return f"{label} │ {msg}"

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
