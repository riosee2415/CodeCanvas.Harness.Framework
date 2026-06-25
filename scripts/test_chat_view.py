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


def test_meta_line_renders_dim_and_indented():
    out = cv.render_chat_line("[Max·meta] files=greet.py | pytest→exit 0", color=True, width=72)
    assert "\033[2m" in out            # dim 적용
    assert "⟨Max·메타⟩" in out          # 메타 라벨(한글화)
    assert "files=greet.py" in out
    assert "│" not in out              # 대화 배지가 아님


def test_handoff_line_renders_dim_arrow():
    out = cv.render_chat_line("[Max→Patrick] 넘김: greet(name)->str", color=True, width=72)
    assert "\033[2m" in out
    assert "↪ Max→Patrick:" in out
    assert "넘김: greet(name)->str" in out
    assert "│" not in out


def test_verify_meta_label_is_korean():
    out = cv.render_chat_line("[검수·meta] AC: pytest→exit 0 | round=1/3 PASS", color=True, width=72)
    assert "⟨검수·메타⟩" in out
    assert "round=1/3 PASS" in out


def test_normal_dialogue_unchanged_after_meta_support():
    # 대화 줄은 메타 분기 도입 후에도 배지 형식 그대로
    out = cv.render_chat_line("[Patrick] 멱등 처리했어", color=True, width=72)
    assert "🟠" in out and "Patrick" in out and "│" in out


def test_long_meta_wraps_and_keeps_indent():
    body = "files=" + ",".join(f"f{i}.py" for i in range(20))
    out = cv.render_chat_line(f"[Max·meta] {body}", color=False, width=50)
    lines = out.split("\n")
    assert len(lines) >= 2                       # 폭 초과 → wrap
    assert all(l.startswith(" ") for l in lines) # 모든 줄 들여쓰기 유지
