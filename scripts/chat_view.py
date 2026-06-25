"""팀 대화창 렌더링 — 에이전트들의 실시간 대화를 채팅처럼 보여준다.

execute.py(실행 중 인라인 기본값)와 watch.py(별도 뷰어)가 공유한다.
chat.md의 각 줄은 `[speaker] message` 형식이며, speaker는 리드/Max/Joy/Esther/Patrick
(한글 별칭 허용 — [패트릭] 등). 미등록 화자도 plain이 아니라 중립 배지로 렌더한다.
"""

import re
import shutil
import unicodedata
from pathlib import Path

RESET = "\033[0m"
DIM = "\033[2m"

# speaker -> (emoji, 배지 ANSI(글자색;배경색), 표시이름).
# 사람마다 '배경색 이름 배지'로 구분한다 — 한눈에 누가 말하는지 보이게.
# 배경색은 .claude/agents 정의의 color와 맞춘다(리드=cyan/Max=blue/Patrick=orange/Joy=pink/Esther=yellow).
SPEAKERS = {
    "리드":   ("🧭", "\033[1;30;46m", "리드"),    # cyan 배경 · 검정 글자 (오케스트레이터)
    "Max":    ("🔵", "\033[97;44m",   "Max"),     # blue 배경 · 흰 글자
    "Joy":    ("🩷", "\033[97;45m",   "Joy"),      # magenta(pink) 배경 · 흰 글자
    "Esther": ("🟡", "\033[30;43m",   "Esther"),  # yellow 배경 · 검정 글자
    "Patrick": ("🟠", "\033[30;48;5;208m",  "Patrick"), # orange(256) 배경 · 검정 글자
}

# 한글로 적힌 화자 라벨도 같은 배지로 매핑한다 (리드가 [패트릭]처럼 한글로 쓰는 경우 대비).
ALIASES = {"맥스": "Max", "패트릭": "Patrick", "조이": "Joy", "에스더": "Esther"}

# 미등록 화자도 plain 대괄호로 빠지지 않게 쓰는 중립 배지 (회색 배경 · 흰 글자).
UNKNOWN_BADGE = ("💬", "\033[97;100m")

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _char_width(c: str) -> int:
    """한 글자의 터미널 표시 폭 (CJK·전각·이모지는 2칸)."""
    if ord(c) >= 0x1F000 or unicodedata.east_asian_width(c) in ("W", "F"):
        return 2
    return 1


def _disp_width(s: str) -> int:
    """문자열의 터미널 표시 폭. 배지 정렬·줄바꿈 계산용."""
    return sum(_char_width(c) for c in s)


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _term_width(default: int = 100) -> int:
    """현재 터미널 폭(칼럼). 파이프 등 알 수 없으면 default."""
    try:
        cols = shutil.get_terminal_size((default, 24)).columns
        return cols if cols and cols > 0 else default
    except Exception:
        return default


def _wrap(text: str, width: int) -> list:
    """text를 표시폭 width 기준 여러 줄로 나눈다 (CJK 폭 인지, '...' 잘림 없음).

    가능하면 직전 공백에서 끊고, 한 덩어리가 width보다 길면 글자 단위로 끊는다.
    """
    if width <= 0 or _disp_width(text) <= width:
        return [text]
    out, line, lw, last_space = [], "", 0, -1
    for ch in text:
        cw = _char_width(ch)
        if lw + cw > width:
            if 0 <= last_space < len(line):
                out.append(line[:last_space])
                line = line[last_space + 1:]
                lw = _disp_width(line)
            else:
                out.append(line)
                line, lw = "", 0
            last_space = -1
        if ch == " ":
            last_space = len(line)
        line += ch
        lw += cw
    if line:
        out.append(line)
    return out


META_INDENT = 13   # 대화 배지 head 표시폭 — 보조 줄을 메시지 시작 열에 맞춘다


def _render_aux(prefix, body, color=True, width=None):
    """메타·핸드오프 보조 줄: dim + 대화 메시지 열 들여쓰기 + 폭 맞춰 wrap (대화 배지 아님)."""
    cols = width if width is not None else _term_width()
    avail = max(8, cols - META_INDENT - _disp_width(prefix) - 1)
    chunks = _wrap(body, avail)
    pad = " " * META_INDENT
    cont = " " * (META_INDENT + _disp_width(prefix) + 1)
    text = f"{pad}{prefix} {chunks[0]}"
    for c in chunks[1:]:
        text += "\n" + cont + c
    return f"{DIM}{text}{RESET}" if color else text


def render_chat_line(raw: str, color: bool = True, width=None) -> str:
    """원시 대화 로그 한 줄을 채팅 형식으로 렌더한다.

    "[Max] 안녕"  ->  "🔵 [파랑배경] Max    [reset] │ 안녕" (이름에 배경색 배지)
    긴 메시지는 터미널 폭에 맞춰 **'...' 잘림 없이 여러 줄로 wrap**되고,
    이어지는 줄은 메시지 열에 맞춰 들여쓴다 (작은 모니터 대응).
    빈 줄 -> "" (생략), 구분선/기타 -> dim 처리.
    """
    line = raw.rstrip("\n")
    if not line.strip():
        return ""

    if line.startswith("[") and "]" in line:
        speaker, _, msg = line[1:].partition("]")
        speaker = speaker.strip()
        msg = msg.lstrip(": ").rstrip()
        if speaker.endswith("·meta"):                                  # 메타 줄: dim 보조 렌더
            return _render_aux(f"⟨{speaker.replace('·meta', '·메타')}⟩", msg, color, width)
        if "→" in speaker:                                             # 핸드오프 줄: dim 보조 렌더
            return _render_aux(f"↪ {speaker}:", msg, color, width)
        speaker = ALIASES.get(speaker, speaker)            # (기존) 한글 라벨 정규화
        if speaker in SPEAKERS:
            emoji, badge, name = SPEAKERS[speaker]
        else:
            emoji, badge = UNKNOWN_BADGE                   # 미등록 화자도 중립 배지(plain 방지)
            name = speaker
        inner = name + " " * max(0, 7 - _disp_width(name))  # 이름 표시폭을 7로 패딩(Patrick 수용)
        if color:
            head = f"{emoji} {badge} {inner} {RESET} │ "
        else:
            head = f"{emoji} {inner} │ "
        pw = _disp_width(_strip_ansi(head))            # 메시지 열의 들여쓰기 폭
        cols = width if width is not None else _term_width()
        chunks = _wrap(msg, max(8, cols - pw))
        indent = " " * pw
        rendered = head + chunks[0]
        for c in chunks[1:]:
            rendered += "\n" + indent + c
        return rendered

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
    if count > len(complete):
        # 파일이 축소/교체됨(truncate·branch swap) → 옛 줄을 재생하지 않고 현재 끝으로 resync.
        count = len(complete)
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
