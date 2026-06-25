이 프로젝트는 Harness 프레임워크를 사용한다. 아래 워크플로우에 따라 작업을 진행하라.

---

## 워크플로우

### A. 탐색

`/docs/` 하위 문서(PRD, ARCHITECTURE, ADR 등)를 읽고 프로젝트의 기획·아키텍처·설계 의도를 파악한다. 필요시 Explore 에이전트를 병렬로 사용한다.

### B. 논의

구현을 위해 구체화하거나 기술적으로 결정해야 할 사항이 있으면 사용자에게 제시하고 논의한다.

### C. Step 설계

사용자가 구현 계획 작성을 지시하면 여러 step으로 나뉜 초안을 작성해 피드백을 요청한다.

설계 원칙:

1. **Scope 최소화** — 하나의 step에서 하나의 레이어 또는 모듈만 다룬다. 여러 모듈을 동시에 수정해야 하면 step을 쪼갠다.
2. **자기완결성** — 각 step 파일은 독립된 Claude 세션에서 실행된다. "이전 대화에서 논의한 바와 같이" 같은 외부 참조는 금지한다. 필요한 정보는 전부 파일 안에 적는다.
3. **사전 준비 강제** — 관련 문서 경로와 이전 step에서 생성/수정된 파일 경로를 명시한다. 세션이 코드를 읽고 맥락을 파악한 뒤 작업하도록 유도한다.
4. **시그니처 수준 지시** — 함수/클래스의 인터페이스만 제시하고 내부 구현은 에이전트 재량에 맡긴다. 단, 설계 의도에서 벗어나면 안 되는 핵심 규칙(멱등성, 보안, 데이터 무결성 등)은 반드시 명시한다.
5. **AC는 실행 가능한 커맨드** — "~가 동작해야 한다" 같은 추상적 서술이 아닌 `npm run build && npm test` 같은 실제 실행 가능한 검증 커맨드를 포함한다.
6. **주의사항은 구체적으로** — "조심해라" 대신 "X를 하지 마라. 이유: Y" 형식으로 적는다.
7. **네이밍** — step name은 kebab-case slug로, 해당 step의 핵심 모듈/작업을 한두 단어로 표현한다 (예: `project-setup`, `api-layer`, `auth-flow`).

### D. 파일 생성

사용자가 승인하면 아래 파일들을 생성한다.

#### D-1. `phases/index.json` (전체 현황)

여러 task를 관리하는 top-level 인덱스. 이미 존재하면 `phases` 배열에 새 항목을 추가한다.

```json
{
  "phases": [
    {
      "dir": "0-mvp",
      "status": "pending"
    }
  ]
}
```

- `dir`: task 디렉토리명.
- `status`: `"pending"` | `"running"` | `"completed"` | `"error"` | `"blocked"`. execute.py가 실행 중 자동으로 업데이트한다.
- 타임스탬프(`completed_at`, `failed_at`, `blocked_at`)는 execute.py가 상태 변경 시 자동 기록한다. 생성 시 넣지 않는다.

**라이브 하트비트 (실행 중 진행 상태 공개):** step은 한 번에 수십 분(최대 `TIMEOUT_SECONDS`=3600초)까지 걸릴 수 있다. execute.py는 실행 중인 phase 항목에 **60초마다** 아래 라이브 필드를 갱신해, 사용자가 외부에서 진행 상황을 실시간으로 볼 수 있게 한다. 터미널 상태(completed/error/blocked)로 전이하면 이 필드들은 자동 제거된다.

| 필드 | 의미 |
|------|------|
| `status` | 실행 중에는 `"running"` |
| `running_step` | 현재 step 번호와 이름 (예: `"2 (ui)"`) |
| `progress` | 완료된 step 수 / 전체 (예: `"2/3"`) |
| `attempt` | 현재 재시도 회차 (1부터) |
| `elapsed_seconds` | 현재 step 누적 실행 시간(초) |
| `heartbeat_at` | 마지막 하트비트 기록 시각 (이 값이 60초 넘게 멈춰 있으면 프로세스 중단을 의심) |

모니터링 예시:

```bash
watch -n5 'cat phases/index.json'   # 5초마다 전체 phase 상태 출력
```

#### D-2. `phases/{task-name}/index.json` (task 상세)

```json
{
  "project": "<프로젝트명>",
  "phase": "<task-name>",
  "steps": [
    { "step": 0, "name": "project-setup", "status": "pending" },
    { "step": 1, "name": "core-types", "status": "pending" },
    { "step": 2, "name": "api-layer", "status": "pending" }
  ]
}
```

필드 규칙:

- `project`: 프로젝트명 (CLAUDE.md 참조).
- `phase`: task 이름. 디렉토리명과 일치시킨다.
- `steps[].step`: 0부터 시작하는 순번.
- `steps[].name`: kebab-case slug.
- `steps[].status`: 초기값은 모두 `"pending"`.

상태 전이와 자동 기록 필드:

| 전이 | 기록되는 필드 | 기록 주체 |
|------|-------------|----------|
| → `completed` | `completed_at`, `summary` | Claude 세션 (summary), execute.py (timestamp) |
| → `error` | `failed_at`, `error_message` | Claude 세션 (message), execute.py (timestamp) |
| → `blocked` | `blocked_at`, `blocked_reason` | Claude 세션 (reason), execute.py (timestamp) |

`summary`는 step 완료 시 산출물을 한 줄로 요약한 것으로, execute.py가 다음 step 프롬프트에 컨텍스트로 누적 전달한다. 따라서 다음 step에 유용한 정보(생성된 파일, 핵심 결정 등)를 담아야 한다.

`created_at`은 execute.py가 최초 실행 시 task 레벨에 한 번만 기록한다. step 레벨의 `started_at`도 execute.py가 각 step 시작 시 자동 기록한다. 생성 시 넣지 않는다.

#### D-3. `phases/{task-name}/step{N}.md` (각 step마다 1개)

```markdown
# Step {N}: {이름}

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md`
- {이전 step에서 생성/수정된 파일 경로}

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

{구체적인 구현 지시. 파일 경로, 클래스/함수 시그니처, 로직 설명을 포함.
코드 스니펫은 인터페이스/시그니처 수준만 제시하고, 구현체는 에이전트에게 맡겨라.
단, 설계 의도에서 벗어나면 안 되는 핵심 규칙은 명확히 박아넣어라.}

## Acceptance Criteria

```bash
# 프로젝트 스택의 실제 빌드·테스트 커맨드로 교체하라 (이 예시를 그대로 쓰지 말 것).
<build cmd>     # 예: npm run build · python -m pytest · cargo build — 빌드/컴파일 에러 0
<test cmd>      # 예: npm test · pytest -q · go test ./... — 테스트 통과
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - CLAUDE.md CRITICAL 규칙을 위반하지 않았는가?
3. 결과에 따라 `phases/{task-name}/index.json`의 해당 step을 업데이트한다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약"`
   - 수정 3회 시도 후에도 실패 → `"status": "error"`, `"error_message": "구체적 에러 내용"`
   - 사용자 개입 필요 (API 키, 외부 인증, 수동 설정 등) → `"status": "blocked"`, `"blocked_reason": "구체적 사유"` 후 즉시 중단

## 금지사항

- {이 step에서 하지 말아야 할 것. "X를 하지 마라. 이유: Y" 형식}
- 기존 테스트를 깨뜨리지 마라
```

### E. 실행

**라이브 대화창으로 보기 (권장)** — 하네스는 **백그라운드**로 돌고, 팀 대화만 컬러로 터미널에 실시간 흐른다(프레임워크의 핵심, G 참조):

```bash
python3 scripts/run.py {task-name}             # 하네스 백그라운드 + 라이브 컬러 대화 뷰어
```

**상시 대화창(여러 phase를 연속으로 돌릴 때)** — phase에 안 묶이는 뷰어를 한 번 띄워두고, 하네스는 옆에서 조용히 돌린다:

```bash
python3 scripts/chat.py                         # (터미널 1) 상시 대화창 — 어떤 phase든 자동 연결·전환
python3 scripts/execute.py {task-name} --quiet  # (터미널 2) 하네스만 — 인라인 표시 끔(chat.py가 전담)
```

**엔진 직접 실행 / push:**

```bash
python3 scripts/execute.py {task-name}         # 하네스만 순차 실행(자기 stdout에 대화 tail)
python3 scripts/execute.py {task-name} --push  # 실행 후 push
```

**여러 phase를 순차로(“n번 구동”)**: phase마다 한 번씩 실행한다(예: `run.py 0-mvp` → `run.py 1-api` …). `phases/index.json`이 전체 현황을 추적한다. (run.py/execute.py는 인자로 받은 **하나의 phase**를 끝까지 돌린다.) 상시 `chat.py`를 띄워두면 phase가 바뀔 때마다 새 하네스 대화로 자동 전환된다.

execute.py가 자동으로 처리하는 것:

- `feat-{task-name}` 브랜치 생성/checkout
- 가드레일 주입 — CLAUDE.md + `.claude/rules/*.md` + docs/*.md 내용을 매 step 프롬프트에 포함
- 컨텍스트 누적 — 완료된 step의 summary를 다음 step 프롬프트에 전달
- 팀 협업 — 각 step을 팀 리드가 Max→(Patrick)→(Esther)→Joy 루프로 수행하고, Joy 판정(통과/개선)으로 내부 최대 3회 개선 (G 참조)
- 자가 교정(2층) — 내부 팀 루프(`INNER_ROUNDS`=3) + 바깥 재시도(`OUTER_ATTEMPTS`=2, 프로세스 실패·타임아웃 복구), 이전 에러·stderr 꼬리를 다음 프롬프트에 피드백
- 2단계 커밋 — 코드 변경(`feat`)과 메타데이터(`chore`)를 분리 커밋
- 타임스탬프 — started_at, completed_at, failed_at, blocked_at 자동 기록
- 라이브 하트비트 — 실행 중인 step의 진행 상태를 60초마다 `phases/index.json`에 기록 (`team_round`로 내부 라운드 진행도 노출, 외부에서 실시간 모니터링 가능)
- 규칙 신선도 점검 — 시작 시 검토 대기 제안·staleness 경고 표면화 (F 참조)

에러 복구:

- **error 발생 시**: `phases/{task-name}/index.json`에서 해당 step의 `status`를 `"pending"`으로 바꾸고 `error_message`를 삭제한 뒤 재실행한다.
- **blocked 발생 시**: `blocked_reason`에 적힌 사유를 해결한 뒤, `status`를 `"pending"`으로 바꾸고 `blocked_reason`을 삭제한 뒤 재실행한다.

### F. 규칙 신선도 (Rules Freshness)

프로젝트가 진화하면 규칙은 낡는다(stale). 하네스는 `.claude/rules/rules.md`를 **항상 fresh하게** 유지하기 위한 루프를 갖는다.

**근거:** 사람이 큐레이션한 규칙만 에이전트 성과를 높인다. LLM이 자동 생성한 context 파일은 오히려 task 성공률을 ~3% 낮추고 추론 비용을 20%+ 올렸다 (ETH Zurich, arXiv 2602.11988). 따라서 하네스는 규칙을 **자동으로 덮어쓰지 않고**, 후보를 모아 **사람이 검토 후 병합**하게 한다.

루프 (propose → review → merge):

1. **propose (자동, 실행 중)** — **Joy(검수자)가 핵심 주체**다: 검수 중 Max·Esther의 (반복) 실수나 새 컨벤션을 발견하면 `phases/{task-name}/rules-proposals.md`에 `- 제안: <규칙> (근거: <어떤 실수를 막는지>)`를 append해 rules.md를 fresh하게 유지한다(다른 에이전트도 가능). CLAUDE.md·rules.md를 직접 수정하지 않는다 — 사람이 병합한다.
2. **review (자동, 시작 시)** — `execute.py`는 실행 시작 시 아래 신호를 경고로 표면화한다:
   - 가드레일(CLAUDE.md/.claude/rules/docs)에 미작성 템플릿 플레이스홀더 `{...}` 잔존 (안 채운 채 매 step 주입되면 LLM을 오도)
   - 검토 대기 중인 `rules-proposals.md` 존재
   - `rules.md`가 `STALE_AFTER_DAYS`(기본 14일) 이상 리뷰되지 않음 (`<!-- harness:freshness last_reviewed=YYYY-MM-DD -->` 헤더 기준)
   - 규칙/CLAUDE.md가 `package.json`에 없는 `npm run <x>`를 참조 (stale 가능 — **Node/package.json 프로젝트 전용** 점검)
3. **merge (수동, 사람)** — 사람이 제안을 취사선택해 `.claude/rules/rules.md`에 반영하고, 병합한 `rules-proposals.md`를 삭제한 뒤 `last_reviewed=`를 오늘 날짜로 갱신한다.

규칙을 추가/수정하는 트리거(Anthropic): ① 같은 실수 2번째 ② 코드 리뷰가 에이전트가 알았어야 할 것을 잡아냄 ③ 같은 교정 재입력 ④ 새 팀원이 필요로 할 맥락. 추가만큼 **가지치기**도 중요하다 — "이 줄을 지우면 에이전트가 실수하게 되는가? 아니면 삭제."

**재사용 커스터마이즈 (project-agnostic):** `.claude/settings.json`의 훅은 **스택 중립 기본값**이다 — `Stop` 훅은 no-op(`exit 0`)이니 프로젝트 빌드·테스트 체크는 `settings.local.json`에 추가하라(예: `npm run test` / `pytest -q`). `PreToolUse` Bash 가드는 흔한 파괴적 명령(`rm -rf`·`git reset --hard` 등)에 대한 **best-effort 속도방지턱일 뿐 보안 경계가 아니다**(정규식은 모든 우회를 막지 못한다) — 진짜 경계는 신뢰할 수 없는 코드를 실행하지 않는 것이다.

### G. 팀 협업 (Max·Patrick·Joy·Esther)

각 step은 단일 세션이 아니라 **팀 리드(헤드리스 세션)가 4-에이전트를 지휘**하는 루프로 수행된다. 에이전트 정의는 `.claude/agents/`에 있고(전부 project-agnostic), 인터랙티브로는 `/team <작업>`으로 같은 팀을 호출한다. 각 에이전트는 시작 전 `.claude/skills/`의 자기 craft 스킬(Max: TDD·디버깅, Patrick: 데이터(스키마·마이그레이션·검증), Joy: 코드리뷰, Esther: 프론트 안티슬롭)을 직접 읽어 적용한다 — 프로젝트 동봉이라 클론하면 그대로 레벨업된다(인덱스: `.claude/skills/README.md`).

| 에이전트 | 역할 | 모델·색 |
|---|---|---|
| **Max** | 개발/엔지니어 — 구현·TDD | opus-4-8 · 🔵 |
| **Patrick** | 데이터 — DB 설계·운영·서빙·정형화 (데이터 step만 투입) | opus-4-8 · 🟠 |
| **Joy** | 검수자 + **규칙 수호자** — git diff+AC로 통과/개선 판정, 반복 실수를 규칙으로 제안(F) | opus-4-8 · 🩷 |
| **Esther** | UI/UX — 디자인·프론트엔드 (UI step만 투입) | opus-4-8 · 🟡 |

루프 (팀 리드가 `execute.py` preamble의 "팀 협업 프로토콜"에 따라 수행):

1. **Max**가 step을 구현 → 한국어 보고.
2. 데이터·DB·스키마·마이그레이션·쿼리·ETL 신호가 있으면 **Patrick**(데이터) 투입(순수 비-데이터면 생략).
3. UI·디자인 신호가 있으면 **Esther** 투입(순수 백엔드면 생략).
4. 리드가 step의 AC를 직접 실행해 결과(커맨드 + exit code) 확보.
5. **Joy**가 git diff + AC 결과로 검수 → 보고 끝줄에 `VERDICT: PASS` 또는 `VERDICT: IMPROVE`.
6. `IMPROVE`면 Joy의 `개선지시(→Max)`로 수정→재검수, **내부 최대 3회**(`INNER_ROUNDS`).
   - **Fail-safe**: 센티넬을 못 찾으면 IMPROVE 처리(자동 PASS 금지). `PASS`는 AC `exit 0` 근거가 있을 때만 유효.
   - **검증자 실패**: Joy 무응답이면 리드가 자가 승인하지 않고 `error`(verifier unavailable).
   - **미해결**: 내부 3회로도 안 되면 `error` + `no_retry: true` + Joy의 마지막 지시를 `error_message`에.
7. 진행하며 팀의 한국어 대화를 `phases/{task}/chat.md`에 `[리드]/[Max]/[Patrick]/[Joy]/[Esther]` 대화체로 실시간 append한다(코드·diff 없이). phase-level `index.json`의 `team_round`로 진행도 노출(하트비트가 top-index로 복사).

**실시간 대화창 (프레임워크의 핵심 — 기본값)**: 팀 대화를 터미널에 채팅처럼 실시간으로 본다 — **배경색 이름 배지**(🔵 Max · 🟠 Patrick · 🩷 Joy · 🟡 Esther · 🧭 리드)로 누가 말하는지 한눈에, 긴 줄은 터미널 폭에 맞춰 **줄바꿈**되어 '...' 잘림 없이 다 보인다(작은 모니터 OK).

- **`python3 scripts/run.py <task>`** (권장): 하네스를 **백그라운드 자식 프로세스**로 돌리고(콘솔은 `phases/<task>/harness.log`로 숨김) **대화만** 컬러로 흘린다. 하네스가 끝나면 뷰어도 자동 종료. → "하네스는 백그라운드, 대화는 현재 터미널."
- **`python3 scripts/chat.py`** (상시 대화창): phase에 안 묶인다. 한 번 띄워두면 `phases/*/chat.md` 중 **지금 가장 최근에 쓰이는** 것(=활성 하네스)을 자동으로 따라가고, 다른 phase의 하네스가 새로 돌면 그 대화로 **자동 전환**(전환 배너 표시). 하네스가 끝나도 뷰어는 살아남아 다음 하네스를 기다린다(Ctrl-C 종료). 옆 터미널에서 `execute.py <task> --quiet`로 하네스를 돌리면 이중 표시 없이 chat.py가 표시를 전담한다. 시작 전 이미 쌓인 줄은 다시 토하지 않고 **그 뒤 새 줄만** 라이브로 보여준다.
- `python3 scripts/watch.py <task>`: 이미 (다른 곳에서) 도는 하네스에 붙는, **특정 phase 하나에 고정된** 전용 뷰어(무한 tail, Ctrl-C 종료).
- 렌더링은 `scripts/chat_view.py` 공유(배경색 배지 + 폭 줄바꿈). 파이프로 실행해도 컬러를 유지하려면 `FORCE_COLOR=1`.

**바깥 안전망**: 내부 루프가 끝나거나 세션이 죽으면(타임아웃 `TIMEOUT_SECONDS`=3600s 포함) `execute.py`가 status를 읽어 바깥 재시도·커밋·하트비트를 처리한다 → 2층 안전망.

**재사용성 주의 (다운스트림 복사 시):**
- 루프의 ground-truth 게이트는 **Joy가 실행하는 step AC**(각 프로젝트가 step.md에 정의)이며 project-agnostic하다.
- `.claude/settings.json`의 **Stop 훅**은 *다운스트림 프로젝트의* 검증 커맨드 placeholder(기본값 `npm run lint && build && test`)다 — 복사한 프로젝트의 lint/build/test로 교체하라. (이 하네스 레포 자체 테스트는 `python3 -m pytest scripts/test_execute.py`.)
- Joy를 다른 모델로 두려면 `joy.md`의 `model:`만 바꾸면 된다(기본은 Max와 동급인 opus-4-8).
