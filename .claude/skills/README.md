# 프로젝트 스킬 라이브러리 (`.claude/skills/`)

팀 에이전트(**Max·Joy·Esther**)의 craft 역량을 프레임워크에 **동봉**한 것이다.
글로벌(`~/.claude/`)이 아니라 **저장소 안**에 두므로, 클론하면 누구나 같은 레벨업된 팀을 쓴다.

## 스킬 목록

| 스킬 | 대상 | 무엇 | 근거 |
|---|---|---|---|
| `test-driven-development/` | 🔵 Max | RED→GREEN→refactor 규율 | superpowers · Kent Beck/Fowler |
| `systematic-debugging/` | 🔵 Max | 재현·가설·근본원인 디버깅 | superpowers |
| `code-review/` | 🩷 Joy | 독립 검증·적대적 리뷰·테스트 게이밍 적발 | Google eng-practices · superpowers · EvilGenie(2511.21654) |
| `frontend-design/` | 🟡 Esther | 안티슬롭·접근성(WCAG AA)·4가지 상태 | impeccable.style · A11Y Project · WCAG 2.2 · Scott Hurff |
| `canvas-design/` | 🟡 Esther (선택) | 포스터·정적 비주얼 아트(.png/.pdf) — 디자인 철학 우선, `canvas-fonts/` 동봉 | anthropics/skills (공식, 그대로 번들) |

## 어떻게 쓰이나

- **자동 발견**: Claude Code는 `.claude/skills/<name>/SKILL.md`를 자동 인식한다(`/team` 인터랙티브 세션에서 Skill로 트리거 가능).
- **명시적 로드**: 헤드리스 하네스(`scripts/execute.py`)에서도 확실히 적용되도록, 각 에이전트 정의(`.claude/agents/*.md`)의 "시작 전(필수)"에서 자기 스킬을 **직접 읽도록** 배선돼 있다.
- **선택 스킬(예외)**: `canvas-design`은 매 step 필수가 아니라 **포스터·정적 아트(.png/.pdf) 산출물이 필요할 때만** 꺼내 쓴다. esther 정의에 필수가 아닌 "선택 스킬"로 안내돼 있고, Skill 자동발견으로도 트리거된다.

## 유지 원칙 (rules.md와 동일)

사람이 큐레이션한 컨텍스트만 에이전트 성과를 높인다 — LLM이 자동 생성한 규칙은 오히려 성공률을 낮춘다(ETH Zurich, arXiv 2602.11988). 그래서 이 스킬들은:

- **린하게**(검증 가능한 imperative 위주, 본문 <500줄), **출처 명시**, 사람이 검토 후 병합한다.
- 코드처럼 다룬다 — 틀리면 고치고, 주기적으로 가지치기하고, 동작이 실제로 바뀌는지로 검증한다.

## SKILL.md 포맷

frontmatter `name`(kebab-case `[a-z0-9-]`, ≤64자, "claude"/"anthropic" 금지) + `description`(≤1024자, "무엇을 + 언제" = 트리거). 본문은 자유 Markdown. 선택적 동봉 디렉토리: `scripts/` `references/` `assets/`.
- 공식 스펙: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
