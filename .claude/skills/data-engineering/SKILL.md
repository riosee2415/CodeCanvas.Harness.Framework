---
name: data-engineering
description: 데이터베이스 설계·운영·서빙·데이터 정형화를 할 때 따른다. 스키마 정규화·제약·인덱싱, 되돌릴 수 있는 무중단 마이그레이션, 쿼리 성능(EXPLAIN·N+1 차단), 데이터 검증·계약(멱등 파이프라인), 그리고 권장 오픈소스·MCP 도구의 프로젝트 스코프 셋업. Patrick(데이터)이 데이터 step을 시작하기 전에 읽는다.
---

# 데이터 엔지니어링 craft (Patrick)

데이터 작업의 craft 규율. 검증 가능한 imperative 위주로 린하게 따른다.

## 0. 원칙
- 데이터는 코드보다 오래 산다. 되돌릴 수 없는 변경(drop·타입변경·삭제)은 분리하고 백업·백필 계획을 먼저 세운다.
- 측정 없이 최적화하지 않는다 — EXPLAIN/ANALYZE로 실제 플랜을 근거로 본다.
- 검증은 경계에서. 들어오는 데이터를 신뢰하지 않는다.

## 1. 스키마 설계
- 3NF를 기본으로, 읽기 성능을 위해 **의도적으로만** 비정규화한다(왜 그랬는지 주석).
- 무결성 제약을 DB에 건다: FK·UNIQUE·NOT NULL·CHECK. 앱 레벨 검증만 믿지 않는다(경합·우회 발생).
- 대리키(surrogate key) 기본. 시간은 UTC·`timestamptz`로 저장하고 표시할 때만 변환한다.
- 인덱스는 조회·조인·정렬·FK 컬럼에 건다. 카디널리티 낮은 컬럼 단독 인덱스는 지양. 복합 인덱스는 좌측 접두(leftmost prefix) 규칙을 따른다.

## 2. 안전한 마이그레이션
- 모든 마이그레이션은 **되돌릴 수 있게**(up/down 둘 다) 작성하고, 멱등하게 만든다(`IF NOT EXISTS` 등).
- 파괴적 변경(drop·rename·타입변경)은 단독 마이그레이션으로 분리한다.
- 무중단(온라인) 패턴: **add(nullable) → backfill(배치) → 앱 스위치/이중쓰기 → constraint 추가 → old drop**. 한 번에 lock을 오래 잡지 않는다.
- 큰 백필은 배치로 끊어 트랜잭션·락 시간을 짧게 유지한다.

## 3. 쿼리·서빙 성능
- 의심되는 쿼리는 `EXPLAIN (ANALYZE)`로 실제 플랜을 확인한다. 대형 테이블 Seq Scan = 인덱스 점검 신호.
- N+1을 차단한다: 조인·IN·배치 로드. ORM은 eager/`select_related` 등으로 명시적으로.
- 모든 목록 API는 페이지네이션한다(keyset 선호, 대형 OFFSET 지양).
- 무거운 집계는 뷰·머티리얼라이즈드 뷰·요약 테이블로 분리하고 갱신 전략을 명시한다.

## 4. 데이터 정형화·검증·계약
- 입력 데이터는 경계에서 스키마로 검증한다(타입·범위·필수·enum). 깨진 행은 격리(dead-letter)하고 파이프라인을 멈추지 않게 한다.
- 파이프라인은 **멱등**하게 만든다(같은 입력 재실행 → 같은 결과). 자연키·upsert·idempotency key를 쓴다.
- 스키마 계약을 명시한다(컬럼·타입·nullable·의미). 변경은 버전·하위호환을 고려한다.

## 5. 권장 도구·오픈소스·MCP (적극 추천·셋업)
> 이 프레임워크 레포엔 설치하지 않는다. **소비 프로젝트에서** 필요 시 사용자에게 적극 권하고, **프로젝트 스코프**로만 배선한다(글로벌 정책: `<repo>/.mcp.json` 또는 `claude mcp add <name> --scope project`, 사용자가 명시 요청·승인했을 때만).

- SQL 파싱·검증·방언 변환: **sqlglot** — 마이그레이션·쿼리 정적 점검.
- 데이터 품질·검증: **Great Expectations**, **Pandera**(데이터프레임 스키마).
- 마이그레이션 도구: 프로젝트 스택에 맞춰 **Alembic**(SQLAlchemy)·Prisma Migrate·Flyway 등.
- 변환·모델링: **dbt**(분석·웨어하우스).
- DB MCP 서버: Postgres/SQLite MCP로 스키마 조회·쿼리 실행을 에이전트가 직접. `claude mcp add <name> --scope project`로만 추가하고 자격증명은 환경변수로.
- 도구 도입 시: 무엇을·왜·어떻게 배선하는지 한국어로 설명하고, 설치는 **사용자 승인 후**에 한다.

## 출처
- Markus Winand, *Use The Index, Luke* — 인덱싱·keyset 페이지네이션.
- PostgreSQL 공식 문서 — `EXPLAIN`, 무중단 DDL.
- Online schema migration 패턴(gh-ost 등 공개 사례).
- sqlglot · Great Expectations · dbt · Alembic 공식 문서.
