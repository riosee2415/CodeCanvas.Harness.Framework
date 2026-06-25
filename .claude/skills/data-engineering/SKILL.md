---
name: data-engineering
description: 데이터베이스 설계·운영·서빙·데이터 정형화를 할 때 따른다. 스키마 정규화·제약·인덱싱, 되돌릴 수 있는 무중단 마이그레이션, 쿼리 성능(EXPLAIN·N+1 차단), 데이터 검증·계약(멱등 파이프라인), 그리고 권장 오픈소스·MCP 도구의 프로젝트 스코프 셋업. Patrick(데이터)이 데이터 step을 시작하기 전에 읽는다.
---

# 데이터 엔지니어링 craft (Patrick)

데이터 작업의 craft 규율. 검증 가능한 imperative 위주로 린하게 따르고, 깊이가 필요하면 심화 참조로 내려간다.

---

## 블록1 — 언제 이 스킬을 쓰는가

- 스키마를 설계·변경할 때(테이블·컬럼·제약·인덱스 추가/수정).
- 마이그레이션을 작성·실행할 때(특히 운영·큰 테이블).
- 느린 쿼리를 진단·최적화하거나 목록 API를 서빙할 때.
- 데이터를 수집·변환·검증·적재하는 파이프라인을 만들 때.
- 데이터 관련 오픈소스·MCP 도구 도입을 검토할 때.

---

## 블록2 — 핵심 원칙

> 데이터는 코드보다 오래 산다. 되돌릴 수 없는 변경은 분리하고, 측정으로만 최적화하며, 검증은 경계에서.

### 0. 절대 원칙

- **데이터는 코드보다 오래 산다.** 되돌릴 수 없는 변경(drop·타입변경·삭제)은 분리하고, 백업·백필 계획을 먼저 세운다.
- **측정 없이 최적화하지 않는다** — `EXPLAIN`/`ANALYZE`로 실제 플랜을 근거로 본다.
- **검증은 경계에서.** 들어오는 데이터를 신뢰하지 않는다.

### 1. 스키마 설계

- **3NF를 기본**으로, 읽기 성능을 위해 **의도적으로만** 비정규화한다(왜 그랬는지 주석).
- 무결성 제약을 DB에 건다: **PK·FK·UNIQUE·NOT NULL·CHECK**. 앱 레벨 검증만 믿지 않는다(경합·우회 발생).
- 대리키(surrogate key) 기본. 시간은 UTC·`timestamptz`로 저장하고 표시할 때만 변환한다.
- 인덱스는 조회·조인·정렬·FK 컬럼에 건다. 카디널리티 낮은 컬럼 단독 인덱스는 지양. 복합 인덱스는 **좌측 접두(leftmost prefix)** 규칙을 따른다.

### 2. 안전한 마이그레이션

- 모든 마이그레이션은 **되돌릴 수 있게**(up/down 둘 다) 작성하고, **멱등**하게(`IF NOT EXISTS` 등) 만든다.
- 파괴적 변경(drop·rename·타입변경)은 단독 마이그레이션으로 분리한다.
- 무중단(온라인) **expand-contract**: add(nullable) → backfill(배치) → 앱 스위치/이중쓰기 → constraint 추가 → old drop. 한 번에 lock을 오래 잡지 않는다.
- 큰 백필은 배치로 끊어 트랜잭션·락 시간을 짧게 유지한다.

### 3. 쿼리·서빙 성능

- 의심 쿼리는 `EXPLAIN (ANALYZE, BUFFERS)`로 실제 플랜을 본다. 대형 테이블 Seq Scan = 인덱스 점검 신호.
- **N+1을 차단**한다: 조인·IN·배치 로드. ORM은 eager/`select_related`로 명시적으로.
- 모든 목록 API는 페이지네이션한다(**keyset 선호**, 대형 OFFSET 지양).
- 무거운 집계는 뷰·머티리얼라이즈드 뷰·요약 테이블로 분리하고 갱신 전략을 명시한다.

### 4. 데이터 정형화·검증·계약

- 입력 데이터는 경계에서 스키마로 검증한다(타입·범위·필수·enum). 깨진 행은 **dead-letter**로 격리하고 파이프라인을 멈추지 않는다.
- 파이프라인은 **멱등**하게(같은 입력 재실행 → 같은 결과). 자연키·upsert·idempotency key를 쓴다.
- **스키마 계약**을 명시한다(컬럼·타입·nullable·의미). 변경은 버전·하위호환을 고려한다.

### 5. 도구·MCP

- 데이터 도구·MCP는 이 프레임워크 레포에 설치하지 않는다. **소비 프로젝트에서 project-scope**로만, 사용자 승인 후 배선한다(**글로벌 금지**, 자격증명은 환경변수).

---

## 블록3 — 출처

- Markus Winand, *Use The Index, Luke* — 인덱싱·keyset 페이지네이션: https://use-the-index-luke.com
- PostgreSQL 공식 문서 — `EXPLAIN`·무중단 DDL: https://www.postgresql.org/docs/current/
- Online schema migration 패턴(gh-ost 등 공개 사례).
- sqlglot · Great Expectations · Pandera · dbt · Alembic 공식 문서.

---

## 블록4 — 심화 참조

| 막히는 상황 | 참조 파일 |
|---|---|
| **스키마 설계 시** — 정규화·비정규화 판단, PK/FK/UNIQUE/CHECK·네이밍, 구체 Postgres DDL 템플릿 | [`reference/schema-design.md`](reference/schema-design.md) |
| **마이그레이션 시** — 되돌릴 수 있는 up/down, 무중단 expand-contract, 백필 배치·멱등성 | [`reference/migrations.md`](reference/migrations.md) |
| **느린 쿼리** — `EXPLAIN (ANALYZE, BUFFERS)` 읽기, 인덱스 전략(복합·부분·커버링), N+1, keyset 페이지네이션 | [`reference/query-performance.md`](reference/query-performance.md) |
| **검증 규칙** — 데이터 계약, Pandera/Great Expectations/dbt tests, dead-letter, 멱등성 | [`reference/data-validation.md`](reference/data-validation.md) |
| **도구·MCP 검토 시** — dbt MCP·postgres-mcp·sqlglot 추천, project-scope 설치 규칙(문서화만) | [`reference/mcp-and-tools.md`](reference/mcp-and-tools.md) |

---

## 블록5 — 완료 전 체크리스트

- [ ] 마이그레이션에 down(되돌리기)이 있고 검증했다
- [ ] 쿼리 변경은 EXPLAIN/ANALYZE로 실행계획을 확인했다
- [ ] 스키마에 PK·FK·NOT NULL·적절한 인덱스/제약을 정의했다
- [ ] 데이터 검증 규칙(계약/테스트)을 추가했다
- [ ] 재실행해도 안전한가(멱등성) 확인했다

하나라도 ✗면 완료 아님.
