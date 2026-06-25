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


def test_korean_aliases_render_as_badge():
    # 리드(LLM)가 화자 라벨을 한글로 적어도([패트릭] 등) plain으로 빠지지 않고 배지가 나와야 한다.
    for ko, en in [("맥스", "Max"), ("패트릭", "Patrick"), ("조이", "Joy"), ("에스더", "Esther")]:
        out = cv.render_chat_line(f"[{ko}] 안녕", color=True, width=80)
        assert f"[{ko}]" not in out          # 원본 대괄호 라벨이 그대로 남으면 안 됨(=매칭 실패)
        assert cv.SPEAKERS[en][0] in out     # 해당 화자 이모지 배지가 나옴
        assert "안녕" in out


def test_unknown_speaker_gets_neutral_badge_not_plain():
    # 알 수 없는 화자명이어도 plain 대괄호가 아니라 중립 배지+구분자 형식을 유지한다.
    out = cv.render_chat_line("[웬열] 테스트", color=True, width=80)
    assert "테스트" in out
    assert "│" in out                        # 배지+구분자 채팅 형식
    assert "[웬열]" not in out                # plain 대괄호로 빠지지 않음


def test_divider_stays_dim_not_badge():
    # 구분선(=== ===)은 화자 줄이 아니므로 배지화하지 않는다.
    out = cv.render_chat_line("=== Step 0: greet ===", color=True, width=80)
    assert "│" not in out
