"""chat_view 배지 렌더 테스트 — 패트릭(🟠) 추가 및 배지 정렬."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import chat_view as cv


def test_patrick_registered():
    assert "Patrick" in cv.SPEAKERS
    emoji, badge, name = cv.SPEAKERS["Patrick"]
    assert emoji == "🟠"
    assert "208" in badge      # 256색 오렌지(48;5;208)
    assert name == "Patrick"


def test_patrick_line_renders_with_orange_badge():
    out = cv.render_chat_line("[Patrick] 마이그레이션 down도 짰어", color=True, width=80)
    assert "Patrick" in out
    assert "마이그레이션" in out
    assert "208" in out         # 오렌지 ANSI 포함


def test_all_badges_align_to_same_column():
    # 모든 화자의 이름 배지가 같은 표시폭이어야 메시지 열(│)이 일치한다.
    widths = set()
    for sp in ("리드", "Max", "Joy", "Esther", "Patrick"):
        out = cv.render_chat_line(f"[{sp}] x", color=False, width=80)
        head = out.split("│", 1)[0]
        widths.add(cv._disp_width(head))
    assert len(widths) == 1     # 전원 동일 폭
