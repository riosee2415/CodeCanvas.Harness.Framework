# 프로젝트: {프로젝트명}

> **이 파일은 매 세션·매 step에 주입되는 1차 컨텍스트다. 린(lean)하게 유지하라.**
> 작성 원칙 (Anthropic memory/best-practices 문서, ETH arXiv 2602.11988 근거):
> - **200줄 이하** 목표. 길수록 컨텍스트를 잡아먹고 지시 준수율이 떨어진다(context rot).
> - **각 줄마다 자문**: "이 줄을 지우면 에이전트가 실수하게 되는가?" 아니면 삭제.
> - **검증 가능할 만큼 구체적으로**: "포맷 맞춰라"(✗) → "2-space 들여쓰기"(✓).
> - **보편적으로 항상 적용**되는 규칙만 여기에. 영역 한정·상세 규칙은 `.claude/rules/rules.md`로.
> - **모순 금지**: 두 규칙이 충돌하면 에이전트가 임의로 하나를 고른다.
> - 끝없는 엣지 케이스 나열(✗) → 대표적·검증 가능한 규칙 몇 개(✓).
>
> _(실제 프로젝트에서는 이 안내 인용 블록을 삭제해도 된다.)_

## 개요
{한두 문장 — 새 팀원에게 설명하듯. 이 프로젝트가 무엇을 하는가.}

## 팀 협업 (Max·Joy·Esther)
실질적 개발 작업은 **3-에이전트 팀**으로 수행한다 (정의: `.claude/agents/`).

| 에이전트 | 역할 | 모델·색 |
|---|---|---|
| **Max** | 개발/엔지니어 — 구현·TDD | opus-4-8 · 🔵 |
| **Joy** | 검수자 — git diff + AC 재실행으로 통과/개선 판정 | opus-4-8 · 🩷 |
| **Esther** | UI/UX — 디자인·프론트엔드 (UI step만 투입) | opus-4-8 · 🟡 |

- **하네스**: `python3 scripts/run.py <task>`(권장 — 하네스는 백그라운드, 컬러 대화만 실시간) 또는 `python3 scripts/execute.py <task>`. 각 step은 팀 리드(헤드리스 세션)가 Max→(Esther)→Joy 루프로 자동 수행한다.
- **인터랙티브**: `/team <작업>`으로 같은 팀을 호출한다.
- **스킬(craft 역량)**: 각 에이전트는 시작 전 `.claude/skills/`의 자기 스킬을 로드한다 — Max: TDD·디버깅, Joy: 코드리뷰(독립검증), Esther: 프론트 안티슬롭·접근성. 프로젝트에 동봉되어 클론하면 그대로 적용된다(인덱스: `.claude/skills/README.md`).
- **실시간 대화창(기본값·프레임워크 핵심)**: 팀의 한국어 대화가 `phases/<task>/chat.md`에 흐르며 터미널에 채팅처럼 표시된다 — **배경색 이름 배지**(🔵 Max · 🩷 Joy · 🟡 Esther · 🧭 리드), 긴 줄은 폭에 맞춰 줄바꿈. 세 가지 보기 방식:
  - `python3 scripts/run.py <task>` — 한 phase: 하네스를 백그라운드로 돌리고 이 터미널에 대화만, 끝나면 자동 종료 (권장·간편).
  - `python3 scripts/chat.py` — **상시 대화창**: 한 번 띄워두면 phase에 안 묶이고, 어떤 phase의 하네스가 돌든 그 대화로 자동 연결·전환. 여러 phase를 연속으로 돌릴 때. 하네스는 옆에서 `python3 scripts/execute.py <task> --quiet`로 돌린다(`--quiet`는 하네스 자체 인라인 표시를 꺼 chat.py와 이중 표시 방지).
  - `python3 scripts/watch.py <task>` — 특정 phase 하나에 고정해 보는 뷰어.
- Joy는 보고 끝줄에 `VERDICT: PASS`/`VERDICT: IMPROVE`를 찍고, PASS는 AC `exit 0` 근거가 있을 때만 유효하다.
- 모든 팀 대화·보고는 **한국어**로 한다.

## 기술 스택
- {프레임워크 (예: Next.js 15)}
- {언어 (예: TypeScript strict mode)}
- {스타일링 (예: Tailwind CSS)}

## 명령어
```bash
npm run dev      # 개발 서버
npm run build    # 프로덕션 빌드 (컴파일 에러 0이어야 함)
npm run lint     # ESLint
npm run test     # 테스트
```

## 코드 스타일
- {예: 2-space 들여쓰기}
- {예: named export 기본, default export 지양}
- {예: 함수형 컴포넌트만 사용}

## 아키텍처 규칙
- CRITICAL: {절대 규칙 1 — 구체적·검증 가능. 예: 모든 외부 API 호출은 `services/`에서만 한다}
- CRITICAL: {절대 규칙 2. 예: 클라이언트 컴포넌트에서 직접 `fetch` 호출 금지}
- {일반 규칙. 예: 컴포넌트는 `components/`, 타입은 `types/`에 둔다}
- 영역 한정·상세 규칙은 `.claude/rules/rules.md` 참조 (CLAUDE.md 비대화 방지)

## 개발 프로세스 (TDD)
- CRITICAL: 새 기능은 테스트를 **먼저** 작성하고, 통과하는 구현을 작성한다.
- 기존 테스트를 깨뜨리지 마라.

## 커밋 / PR
- conventional commits 형식 (`feat:`, `fix:`, `docs:`, `refactor:`)
- {PR 규칙 — 예: PR 1개 = 변경 1개. 본문에 검증 커맨드 결과 첨부}

## 보안
- {예: 시크릿은 환경변수로만. 클라이언트 번들에 포함 금지}
- {예: 사용자 입력은 경계(API route)에서 검증한다}

---

## 이 파일을 신선하게 유지하기
"코드처럼 다뤄라 — 틀렸을 때 리뷰하고, 주기적으로 가지치기하고, 동작이 실제로 바뀌는지로
검증하라." (Anthropic) 자동 생성한 규칙은 성과를 **낮춘다** — 사람이 큐레이션한 규칙만
효과가 있다(ETH arXiv 2602.11988). 그래서 규칙은 사람이 검토 후 병합한다.

**아래 트리거가 발생하면 규칙을 추가/수정한다:**
- 에이전트가 같은 실수를 두 번째로 했을 때
- 코드 리뷰가 에이전트가 알았어야 할 것을 잡아냈을 때
- 이전 세션과 같은 교정을 다시 입력하고 있을 때
- 새 팀원에게 똑같이 설명해야 할 맥락일 때

운영 절차(propose → review → merge)와 staleness 점검은 `.claude/rules/rules.md`와
`/harness` 워크플로우의 "규칙 신선도" 단계를 따른다.
