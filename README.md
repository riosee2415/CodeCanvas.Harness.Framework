# Harness Framework — 팀 에이전트 개발 하네스

3~4명의 AI 에이전트가 한 팀이 되어 **step 단위로 자동 개발**하는 Claude Code 하네스다.
팀이 일하는 한국어 대화가 터미널에 **실시간 채팅처럼** 흐르고, 각 step은 구현 → (UI/데이터) →
독립 검수 루프로 자동 수행된다.

## 팀

| 에이전트 | 역할 | 색 |
|---|---|---|
| **Max** | 개발/엔지니어 — 구현·TDD | 🔵 |
| **Patrick** | 데이터 — DB 설계·운영·서빙·정형화 (데이터 step만 투입) | 🟠 |
| **Joy** | 검수자(QA) — git diff + AC 재실행으로 통과/개선 판정 | 🩷 |
| **Esther** | UI/UX — 디자인·프론트엔드 (UI step만 투입) | 🟡 |

정의는 `.claude/agents/`, 각자의 craft 스킬은 `.claude/skills/`에 있다.

## 요구사항 (Prerequisites)

**필수**

- **Claude Code CLI (`claude`)** — 하네스가 헤드리스로 호출한다.
  ```bash
  npm install -g @anthropic-ai/claude-code
  # 설치 안내: https://docs.claude.com/en/docs/claude-code
  ```
- **Python 3.8+** — 스크립트 실행. **런타임 의존성 없음(표준 라이브러리만 사용)** — `pip install`이 필요 없다.

**개발/테스트(선택)**

- **pytest** — 테스트 실행용.
  ```bash
  python3 -m pip install pytest
  ```

## 빠른 시작

```bash
git clone <this-repo> && cd harness_framework

# (선택) 테스트 — 표준 라이브러리만 쓰므로 pytest만 있으면 된다
python3 -m pytest scripts/ -q

# 한 phase 실행 (권장: 대화만 실시간, 하네스는 백그라운드, 끝나면 자동 종료)
python3 scripts/run.py <phase-dir>
```

실행/관전 방식 3가지:

| 명령 | 용도 |
|---|---|
| `python3 scripts/run.py <phase>` | 한 phase — 대화 실시간 + 자동 종료 (권장·간편) |
| `python3 scripts/chat.py` + `python3 scripts/execute.py <phase> --quiet` | 상시 대화창 + 옆에서 하네스 (여러 phase 연속 실행 시) |
| `python3 scripts/watch.py <phase>` | 특정 phase 하나에 고정된 뷰어 |

인터랙티브로 같은 팀을 부르려면 Claude Code 세션에서 `/team <작업 설명>`.

## 레포에 번들된 것 (별도 설치 불필요)

클론하면 `.claude/` 안의 다음이 **그대로** 적용된다. 글로벌(`~/.claude`)이 아니라
레포 안에 있으므로 추가 설치가 없다.

- `.claude/agents/` — Max·Patrick·Joy·Esther 정의
- `.claude/skills/` — craft 스킬 6개 (test-driven-development · systematic-debugging · code-review · frontend-design · **data-engineering** · canvas-design)
- `.claude/commands/` — `/team` · `/harness` · `/review`
- `.claude/settings.json` — 위험 명령 best-effort 가드 훅

## 선택·권장 도구 (MCP · 플러그인)

> **⚠ 정책 — 프로젝트 스코프로만 설치한다.** 모든 MCP·플러그인은 `--scope project`로
> 추가한다. 글로벌(`--scope user`) 설치는 머신의 다른 프로젝트를 오염시키므로 쓰지 않는다.
>
> **현재 이 레포에는 `.mcp.json`이 없고 필수 MCP/플러그인이 없다.** 아래는 작업 성격에
> 따라 **선택적으로** 추가하는 권장 항목이다.

### context7 — 라이브러리 문서 조회 MCP (권장)

에이전트가 최신 라이브러리/프레임워크의 **공식 문서**를 끌어와 정확도를 높일 때.

```bash
# stdio (npx)
claude mcp add context7 --scope project -- npx -y @upstash/context7-mcp

# 또는 HTTP
claude mcp add context7 --scope project --transport http https://mcp.context7.com/mcp
```

### 데이터 작업용 (🟠 Patrick) — 데이터 step이 있을 때 선택

Patrick의 `data-engineering` 스킬이 권하는 도구. 소비 프로젝트에 **데이터 작업이 있을 때만** 고른다.

```bash
# 파이썬 데이터 라이브러리 (스택에 맞춰 취사선택)
python3 -m pip install sqlglot great_expectations pandera alembic
python3 -m pip install dbt-core dbt-postgres        # 어댑터는 DB 벤더에 맞춰

# DB MCP 서버 (예: Postgres) — 자격증명은 환경변수로, 인자에 직접 박지 않는다
claude mcp add postgres --scope project \
  -e DATABASE_URL="postgresql://user:pass@host:5432/db" \
  -- npx -y @modelcontextprotocol/server-postgres
# ↑ 패키지는 예시(공식 레퍼런스). 벤더/스택에 맞는 최신 MCP를 선택하라 —
#   필요한 도구는 Patrick이 작업 중 적절한 것을 추천·안내한다.
```

### superpowers — 메타 워크플로우 플러그인 (선택)

브레인스토밍 → 구현 계획 → TDD → 코드리뷰 같은 **작업 절차 스킬** 묶음.

```bash
claude plugin marketplace          # 마켓플레이스 탐색/추가
claude plugin install superpowers  # 마켓플레이스에서 설치
claude plugin list                 # 설치된 플러그인 확인
```

## 개발 가이드

- **테스트**: `python3 -m pytest scripts/ -q`
- **규칙/컨텍스트**: 프로젝트 규칙은 `CLAUDE.md`, 영역 한정 규칙은 `.claude/rules/rules.md`.
- **규칙 제안**: 작업 중 새 컨벤션을 발견하면 `phases/<phase>/rules-proposals.md`에 제안만
  남긴다(직접 `CLAUDE.md`/`rules.md`를 고치지 않는다 — 사람이 검토 후 병합).
- **언어**: 사용자에게 보이는 모든 안내·대화·보고는 **한국어**.

## 라이선스

[LICENSE](LICENSE) 참조.
