# 설계: Max·Joy·Esther 3-에이전트 협업 하네스

- **작성일**: 2026-06-23
- **상태**: 승인 대기 (사람 리뷰 → 구현 계획 단계로)
- **근거**: ultracode 루프-엔지니어링 검토(7개 렌즈 · 개선안 33건 제안 → 29건 채택 · 4건 과설계로 거절). 종합 판정 **suited-with-improvements / 72점** — 방향은 옳고, 아래 개선으로 정확성·경제성 결함을 닫는다.

---

## 1. 목표

기존 하네스의 "step당 단일 헤드리스 세션" 모델을, **팀 리드가 Max·Esther·Joy를 지휘하는 협업 루프**로 교체한다. 모든 작업에서 세 에이전트가 한국어로 대화하며 일하고, **act(Max) → verify(Joy, ground-truth 결박) → correct** 사이클이 결정적으로 종료·수렴하게 만든다.

**이 프레임워크의 핵심 경험(정체성)**: Phase를 구성하고 하네스를 실행하면, 사용자는 터미널에서 AI '직원'들(🔵 Max · 🩷 Joy · 🟡 Esther)이 **각자 페르소나 말투로** 일하며 — 실제 작업 내용을 이야기하고 가끔(~5%) 실없는 농담도 섞으며 — 대화하는 모습을 **실시간 채팅창**으로 계속 본다. 마치 회사를 이끄는 듯한 시각적 경험. 단순 부가 기능이 아니라 정체성이다(§9).

**핵심 불변식(보존):** execute.py의 결정적 바깥 안전망 — 바운드된 재시도 루프, 2단계 커밋(브랜치), 60초 하트비트(top-index 단독 writer), 규칙신선도, PreToolUse 안전훅(`rm -rf`/force-push/hard-reset/`DROP TABLE`), index.json status 프로토콜 — 은 **손대지 않는다.** 팀 루프는 한 step 실행 *내부*에 중첩되는 새 레이어다.

**최우선 제약 — 재사용성(reusability):** 이 레포는 프로젝트가 아니라, **새 프로젝트를 킥오프할 때마다 복사해 쓰는 재사용 스캐폴드**다. 따라서 추가·수정하는 모든 것(에이전트 정의·커맨드·execute.py·훅·CLAUDE.md)은 **특정 프로젝트에 비종속(project-agnostic)**이어야 한다.
- 에이전트는 기술 스택·빌드 커맨드를 하드코딩하지 않고, 각 다운스트림 프로젝트의 `CLAUDE.md`/`.claude/rules/`/`docs/`/step의 AC를 **런타임에 읽어** 따른다.
- 하네스 *자체 개발*(이 레포)과 *다운스트림 사용*(복사된 곳)을 혼동하지 않는다. 이 둘을 혼동한 결정은 재사용성을 깬다(예: Stop 훅을 pytest로 하드코딩 — §11 참조).

---

## 2. 아키텍처 — 하나의 팀, 두 표면

- **하네스 표면(자동):** `execute.py`가 띄운 각 step의 헤드리스 세션이 **팀 리드**가 되어, Task 도구로 서브에이전트(`.claude/agents/`)를 호출해 루프를 돈다. 끝에 index.json status를 1회 갱신 — 기존 결정적 프로토콜 그대로.
- **인터랙티브 표면:** 같은 3개 에이전트를 일반 세션에서도 `/team` 커맨드 + CLAUDE.md의 간결한 규칙으로 사용. 실질 개발은 기본 팀으로 수행(사소한 단순 질의는 제외).
- **메커니즘:** 네이티브 서브에이전트(헤드리스에서 자동 인식, 별도 플래그 불필요). 새 파이썬 오케스트레이션 엔진을 만들지 않는다. 모든 변경은 `<repo>/.claude/` 내부 — 글로벌 미변경.

---

## 3. 에이전트 3명 (`.claude/agents/`)

| 에이전트 | 모델 | 색상 | 역할 | 도구 |
|---|---|---|---|---|
| **Max** | `claude-opus-4-8` | `blue` | 개발/엔지니어 — 구현·TDD·가드레일 준수 | Read/Edit/Write/Bash/Grep/Glob |
| **Joy** | `claude-opus-4-8` | `pink` | 기획/검수 — git diff + AC 재실행으로 **통과/개선 판정**, 개선 시 구체 지시 | Read/Bash/Grep/Glob (읽기·실행) |
| **Esther** | `claude-opus-4-8` | `yellow` | UI/UX — 웹/모바일 디자인 구현 + 오픈소스·스킬·플러그인 리서치 활용 극대화, UI_GUIDE 안티슬롭 준수 | Read/Edit/Write/Bash + WebSearch/WebFetch/context7/Skill |

> **모델 결정:** 세 에이전트 모두 `claude-opus-4-8`. 검증자(Joy)를 구현자보다 약한 구버전에 고정하지 않고, 동급 모델로 둔다. → 프로비저닝 실패 모드 제거, 검증 능력 최대. (cross-model 다양성은 같은 계열 4.7/4.8 간엔 작아 포기.) 따라서 모델-폴백·모델-불일치-경고 기계장치는 두지 않는다.

---

## 4. step 1회 흐름 (하드닝된 루프)

```
execute.py
  └─ claude -p  (헤드리스 = 팀 리드)   ← preamble: 팀 협업 프로토콜(아래) + 가드레일(1회) + step
       ├─ Task→ Max(4.8): step 구현 → 한국어 보고
       ├─ (UI 신호면) Task→ Esther(4.8): 디자인·리서치·UI 구현 → 한국어 보고
       ├─ 리드: 해당 step의 AC를 직접 실행해 결과(커맨드+exit code) 확보
       ├─ Task→ Joy(4.8): git diff + (리드가 넘긴) AC 결과로 검수
       │     → 마지막 줄에 ASCII 센티넬 `VERDICT: PASS` | `VERDICT: IMPROVE`
       │     └─ IMPROVE면 Task→ Max(Joy의 X-때문에-Y 지시) → Joy 재검수 … INNER_ROUNDS(=3)회
       ├─ chat.md에 [리드]/[Max]/[Joy]/[Esther] 대화체 메시지 실시간 append (코드 없이; execute.py가 채팅으로 라이브 출력)
       ├─ 리드: phase-index에 team_round 마커("2/3 IMPROVE") 기록 (자기 소유 파일만)
       └─ index.json status 갱신(completed/error/blocked + summary)
  └─ execute.py: status 읽고 재시도/커밋/하트비트 (바깥 안전망)
```

**Esther 게이팅:** 리드가 step 내용/파일 경로/AC의 UI·디자인 신호로 자동 판단(순수 백엔드면 미투입 — 토큰 절약). **Joy는 매 step 투입(사용자 명시 설계)** — 단 리드가 AC를 이미 돌렸으면 결과를 Joy에 넘겨 재실행을 생략한다.

---

## 5. Joy 검증 프로토콜 (ground-truth 결박) — P1

루프 엔지니어링의 핵심: 검증자가 **자기 서사가 아니라 실행된 exit code**로 판정한다.

1. **ASCII 센티넬 문법.** Joy는 한국어 검수 보고 끝에 **마지막 비어있지 않은 줄**로 정확히 하나를 찍는다: `VERDICT: PASS` 또는 `VERDICT: IMPROVE` (ASCII 토큰 — 한국어 문장부호에 파싱이 의존하지 않게). 리드는 **그 마지막 센티넬 줄만** 파싱한다.
2. **Fail-safe.** 센티넬이 없거나 둘 다거나 변형되면 → **그 라운드를 IMPROVE로 처리(절대 자동 PASS 금지)** 하고 라운드를 1회 소모. 마지막 라운드였으면 step을 `error`(파싱 안 된 꼬리를 error_message)로. (별도 재질의 라운드를 추가하지 않는다 — 3번째 루프 레이어 금지.)
3. **Ground-truth 결박.** 실행 가능한 AC가 있는 step은, Joy가 센티넬 바로 위에 **실제 커맨드와 exit code**를 붙인다(예: `AC: pytest -> exit 0`). 리드는 **exit 0 블록이 있을 때만 PASS를 유효**로 인정하고, PASS-인데-비0이면 IMPROVE로 강등. 커맨드 없는 docs-only step은 체크리스트 근거를 명시(커맨드 날조 금지).
4. **diff 기반 판정 + 테스트 보호.** Joy는 Max의 보고를 *검증 대상 주장*으로만 보고 **git diff + AC 재실행**으로 판정한다. 개선지시 각 불릿은 구체적 실패(실패한 AC 커맨드·정확한 stderr 줄·`file:영역`)와 요구 변경을 인용한다(harness.md 규칙 6의 X-금지-이유-Y). 체크리스트에 **"이 diff에서 테스트가 삭제·약화되지 않았다"**를 추가(Max가 실패 테스트를 지워 통과하지 못하게).
5. **검증자 실패 = 사람/바깥으로 fail-safe.** Joy의 Task가 죽거나·행·센티넬 무파싱이면 리드는 **스스로 PASS를 만들지 않는다.** step을 `error`("verifier unavailable")로, dialogue에 기록, execute.py 바깥 재시도/사람에게 위임. (리드-직접처리 폴백은 생산자 Max·Esther에만 적용.)

> 위는 전부 **프롬프트 규약**이다. execute.py에 새 파서를 넣지 않는다(기존 구조화 status 읽기만 사용).

> **재사용성 관점:** 루프의 진짜 ground-truth 게이트는 **Joy가 실행하는 step AC(각 프로젝트가 step.md에 정의한 실행 커맨드)**이며, 이는 project-agnostic하다. 하네스를 어떤 프로젝트에 복사해도 그 프로젝트의 AC로 검증된다. 이것이 `.claude/settings.json`의 Stop 훅(다운스트림이 채우는 풀 스위트)과 **독립적**으로 동작하는 이유다.

---

## 6. 재시도 2층 정합 — P1

현재 내부 3회 × 외부 3회 = 최악 ~9 producer 패스. 이를 분리·단축한다.

- **상수 분리:** `MAX_RETRIES=3`을 둘로 — `INNER_ROUNDS=3`(리드의 내부 Max↔Joy 루프, 프로토콜에 문서화) + **바깥 재시도 1회(신규 컨텍스트 재시작, 총 2회 호출)**. 최악 = `INNER_ROUNDS × 바깥호출 ≈ 6`을 명명 상수로.
- **단락(short-circuit):** 내부 루프가 *미해결(비-blocked)* 으로 소진되면 리드가 `error` + 구조화 필드 **`no_retry=true`**(매직 문자열 아님, 기존 구조화-status 관용 재사용). execute.py는 `no_retry=true`인 error step을 현재 바깥 패스 후 **재시도 없이 종료**. 진짜 프로세스 실패(크래시/타임아웃/"status 미갱신")엔 풀 바깥 재시도 유지.
- **신호 브리지:** 내부 소진 시 리드가 Joy의 **마지막 구체 개선지시 top-3**를 `error_message`에 기록(`Joy unresolved directive (round 3): …`). execute.py는 이미 `error_message`를 다음 프롬프트의 `prev_error`로 먹임 → **코드 변경 0**. (단, 비-Joy 사유로 error면 진짜 실패 원인을 기록.)
- **실패 신호 포착:** `_invoke_claude`는 이미 `out`(exitCode/stdout/stderr)을 **반환하지만 호출부가 버린다.** 이를 받아서, status 미설정 분기(`'Step did not update status'`)거나 `out['exitCode'] != 0`이면 **`out['stderr']` 꼬리(~1500자) + exit code를 err_msg에 주입**. 가장 흔한 실제 실패(프로세스 사망)가 모호한 nudge가 아니라 구체 신호가 되게.

---

## 7. 종료 안전성 — P0 (가장 큰 구멍)

한 세션이 이제 3라운드 팀루프를 품으므로 **타임아웃이 가장 흔한 실패**가 된다. 현재 `_invoke_claude`의 `subprocess.run`은 타임아웃 시 `TimeoutExpired`가 **잡히지 않고 터져** step을 비-terminal 상태(라이브 하트비트 필드가 멈춘 채)로 크래시시킨다.

- `subprocess.run(..., timeout=…)`을 `except subprocess.TimeoutExpired`로 감싼다. 타임아웃을 기존 per-attempt 루프에 흘려 **재시도 1회처럼 소비**하고, 마지막 시도면 기존 max-retries terminal 경로(`status='error'`, `error_message='session timed out after Ns'`, `failed_at`, 커밋, `_update_top_index('error')`)로 보낸다. 그 경로가 라이브 필드(`running_step`/`attempt`/`elapsed_seconds`/`heartbeat_at`)를 정리하는지 확인하고, 아니면 명시적으로 정리.
- 하드코딩 `1800`을 `TIMEOUT_SECONDS` 상수로 올리고 단일 구체값(예: **3600**)으로 상향.
- **테스트:** `TimeoutExpired`가 terminal error로 귀결하고 예외를 던지지 않음을 단언.

---

## 8. 경제성 (토큰) — P1 ("경제성 weak" 해소)

- **가드레일 1회 주입.** 전체 가드레일 번들(CLAUDE.md + 모든 rules + docs)은 **팀 리드 preamble에만** 넣는다. 각 Task 서브에이전트엔 **짧은 포인터**만: "시작 전 CLAUDE.md, `.claude/rules/` 전체, 네 작업에 관련된 `docs/*.md`를 직접 읽어라." ⚠ 서브에이전트엔 **CLAUDE.md만 자동 로드**되고 `.claude/rules/*.md`·`docs/*.md`는 안 됨 → 포인터를 명시하지 않으면 가드레일이 조용히 사라진다. Joy의 CRITICAL-규칙 점검(Joy가 직접 rules를 읽음)을 backstop으로 유지. UI_GUIDE는 `esther.md` 안에 둔다(백엔드 에이전트에 먹이지 않음).
- **AC 중복 실행 제거.** 리드가 AC를 돌려 green이면 결과를 Joy에 넘겨 재실행 생략(Joy는 체크리스트만).

> **사용자 의도 우선:** ultracode 리뷰는 "일상 step에선 Joy 서브에이전트 자체를 생략"을 권했으나, 사용자가 *"Max가 매 step Joy에게 보고 → Joy 판정"*을 명시했으므로 **Joy는 매 step 유지**한다. 경제성은 위(가드레일 1회·AC 재실행 생략) + Esther 게이팅 + compact ledger로 확보. (원하면 Joy 게이팅은 나중에 토글로 추가 가능 — §14.)

---

## 9. 관찰성 & 위생 — P2 (저비용)

- **실시간 팀 대화창 (chat.md — 프레임워크 핵심).** 진행하며 팀이 `phases/{phase}/chat.md`에 `[리드]/[Max]/[Joy]/[Esther]` **페르소나 말투의 대화체 한 줄**을 즉시 append한다(코드·diff 금지; 가끔 ~5% 실없는 농담 포함 — 사람이 채팅처럼 읽음). 각 서브에이전트가 자기 말투로 직접 발언하고 리드는 `[리드]`·step 헤더를 쓴다. `execute.py`가 실행 중 이 파일을 색깔 채팅으로 **실시간 터미널 출력**(기본값, 스피너 대체)하고, 별도 터미널 뷰어 `scripts/watch.py <phase>`도 제공한다(렌더링은 `scripts/chat_view.py` 공유). 리드는 제어흐름을 **Joy의 센티넬에서만** 끌어온다(chat은 프롬프트에 주입 안 됨 → context rot 없음).
- **내부 라운드 진행 노출(단일 writer 불변식 보존).** 리드는 top-index를 쓰지 않는다. 대신 (a) ledger 1줄 append, (b) 자기 소유인 **phase-level index.json**에 작은 마커 `team_round: "2/3 IMPROVE"`만, (c) 기존 파이썬 하트비트 스레드가 그 필드를 읽어 자기가 쓰는 top-index에 복사. 한 줄, 트랜스크립트 없음.
- **안티-진동 *조언*.** 같은 실패 AC 신호가 라운드 간 좁혀지지 않고 반복되면 리드가 내부 루프를 일찍 끝내도록 *권고*(하드 2-라운드 킬 아님 — 거친 신호 `fail(build)`는 실제 진전 중에도 반복될 수 있으므로). 3-라운드 캡이 진짜 경계.

---

## 10. execute.py 수정 명세 (요약)

| 위치 | 변경 | 테스트 |
|---|---|---|
| `_invoke_claude` | `TimeoutExpired` 포착 → terminal error 경로; `1800`→`TIMEOUT_SECONDS=3600` | 타임아웃이 terminal error, 미예외 |
| `_execute_single_step` | `out=_invoke_claude(...)` 포착; status 미설정/exit≠0 시 stderr 꼬리+exit code를 err_msg에 주입 | 포착된 stderr/exitCode가 prev_error에 등장 |
| 상수 | `MAX_RETRIES` → `INNER_ROUNDS=3` + 바깥 재시도 1; 최악 ~6 명명 | error+no_retry는 1패스 종료 / 일반 error는 재시도 |
| `no_retry` 처리 | `error` + `no_retry=true`면 바깥 재시도 소비 없이 종료 | 양쪽 분기 |
| `_build_preamble` | "팀 협업 프로토콜"(§4–6,8,9) 주입; 대화록 경로·`INNER_ROUNDS` 상수 노출 | 프로토콜·에이전트명·센티넬 문법·대화록 경로·한국어 지시 포함 |
| 하트비트 스레드 | phase-index의 `team_round`를 top-index로 복사 | 마커 전파, 단독 writer 유지 |

그 외 execute.py 로직(재시도 골격·커밋·하트비트·신선도)은 불변.

---

## 11. 생성 / 수정 파일

**생성**
- `.claude/agents/max.md`, `joy.md`, `esther.md` (모델 4.8, 색상 blue/pink/yellow)
- `.claude/commands/team.md` (인터랙티브 진입점)
- `scripts/chat_view.py` (대화창 렌더링/팔로우 — execute.py·watch.py 공유)
- `scripts/watch.py` (별도 터미널 실시간 대화창 뷰어)
- 본 스펙 문서

> 에이전트 정의(`.claude/agents/`)에는 **페르소나/말투**가 포함된다 — Max(차분·겸손한 남성), Joy(밝고 활기찬 인싸 여성), Esther(따뜻하지만 디자인엔 자신 있는 여성), 각자 ~5% 실없는 농담. 페르소나는 *말투일 뿐* 기능 규칙(특히 Joy 검증 엄격성)은 불변.

**수정**
- `scripts/execute.py` (§10)
- `scripts/test_execute.py` (§10의 테스트들 + 프리앰블 팀 프로토콜 단언)
- `.claude/settings.json` — **Stop 훅은 다운스트림 프로젝트의 검증 커맨드 placeholder로 유지**한다(이 레포가 복사되면 그 프로젝트의 lint/build/test가 됨). 템플릿 기본값 `npm run lint && build && test`를 **그대로 두고**, "다운스트림은 자기 테스트 커맨드로 교체"임을 한 줄 주석/문서로 명시. ⚠ **pytest로 하드코딩하지 않는다** — 그러면 모든 다운스트림(주로 Node) 프로젝트가 자기 앱이 아니라 하네스 자체 테스트를 돌리게 되어 재사용성이 깨진다. 이 레포(하네스 자체 개발)에서의 ground-truth 검증은 `pytest`이며, gitignore되는 `settings.local.json` 개인 override 또는 CI/수동으로 돌린다. PreToolUse 안전훅은 generic이므로 그대로 둔다.
- `.claude/commands/harness.md` (워크플로우에 팀 문서화)
- `CLAUDE.md` (간결한 "팀 협업" 섹션 — 린하게, behavior를 바꾸는 줄만)

---

## 12. 범위 밖 / 과설계로 거절 (적대적 검증이 걸러냄)

- ❌ execute.py가 dialogue.md의 ROUND 마커를 세는 사후 검사 — 타임아웃+재시도+status가 이미 경계를 소유. 제어흐름을 한국어 서사 파일에 결합.
- ❌ 두 루프를 1 내부 라운드로 합치기 — 제안 전체의 핵심(in-session 독립 검증)을 도려냄.
- ❌ Joy 라운드 판정을 index.json status로 라우팅 — terminal 의미 파괴(중간 'completed'가 조기 커밋), 검증자에 쓰기 권한 필요.
- ❌ execute.py에 doc→agent 매핑 필터 — 잘못된 레이어. UI_GUIDE는 esther.md에 두면 됨.
- ❌ 새 파이썬 오케스트레이션 엔진 / 새 MCP 서버 / 글로벌 변경.

---

## 13. 사람 결정 / 열린 옵션

- ✅ **모델 = 세 에이전트 모두 `claude-opus-4-8`** (결정됨, §3).
- ✅ **Joy 매 step 투입** (사용자 명시 설계 — 유지, §8).
- ◻ (옵션, 미채택) Joy를 UI/no-AC/AC-fail/review-heavy step에만 투입하는 경제 게이팅 — 원하면 토글로 추가. 기본은 매 step.

---

## 14. 테스트 계획

- 기존 `scripts/test_execute.py`는 전부 green 유지.
- 신규 단언: 타임아웃 terminal화 · stderr/exit code의 prev_error 주입 · `no_retry` 양분기 · 프리앰블의 팀 프로토콜/센티넬 문법/대화록 경로/한국어 지시 · 하트비트 team_round 전파.
- 하네스 자체 검증 커맨드: `python3 -m pytest scripts/test_execute.py -q`. (다운스트림 프로젝트의 Stop 훅은 *그 프로젝트의* 테스트 커맨드 — 본 레포의 pytest와 별개다.)
