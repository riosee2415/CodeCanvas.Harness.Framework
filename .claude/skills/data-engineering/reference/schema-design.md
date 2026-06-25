# 스키마 설계 — 정규화·제약·인덱스·네이밍

> 예시 스택: Postgres. 원칙은 스택 불문 — 네 스택에 맞춰 적용.
> (MySQL·SQLite·SQL Server·BigQuery 등도 동일 원칙: 정규화로 진실의 단일 출처를 만들고,
> 무결성은 DB 제약으로 강제하고, 조회 경로에 인덱스를 건다. DDL 문법만 방언에 맞춘다.)

---

## 이 스킬이 잡아야 할 대표 상황

| 상황 | 왜 설계가 중요한가 |
|---|---|
| **같은 사실이 여러 테이블에 중복 저장된다** | 갱신 불일치(update anomaly). 한 곳만 고치면 데이터가 어긋난다. 정규화로 진실의 출처를 하나로. |
| **앱 코드에만 검증이 있고 DB는 무엇이든 받는다** | 경합·우회·버그·수동 INSERT로 깨진 데이터가 들어온다. 무결성은 DB 제약으로 강제한다. |
| **`status`·`type` 컬럼에 오타·미정의 값이 섞인다** | enum/CHECK 제약이 없는 것. 허용값을 DB가 강제하지 않으면 쓰레기가 쌓인다. |
| **외래 관계가 컬럼 이름 규약뿐, FK가 없다** | 고아 행(orphan)·참조 무결성 깨짐. FK로 cascade·restrict를 명시한다. |

---

## 1. 정규화 — 3NF를 기본으로

목표는 **각 사실을 정확히 한 곳에** 저장하는 것이다. 1NF→2NF→3NF를 거치며 중복과 이상(anomaly)을 제거한다.

- **1NF**: 원자값만. 한 컬럼에 콤마로 여러 값(`"red,green,blue"`)을 넣지 않는다. 반복 그룹은 별도 행으로.
- **2NF**: 복합 PK의 **일부**에만 의존하는 컬럼을 분리한다.
- **3NF**: 비키 컬럼이 **다른 비키 컬럼**에 의존(이행 종속)하면 분리한다. 예: `orders`에 `customer_email`을 두지 말고 `customers`를 참조한다(이메일은 customer의 사실이지 order의 사실이 아니다).

**판별 한 줄**: "이 컬럼은 이 행의 PK가 가리키는 그 엔티티의 직접적 사실인가?" 아니면 다른 테이블로.

### 언제 비정규화하나 — 의도적으로만

정규화는 기본값이다. 비정규화는 **측정된 읽기 병목**이 있을 때만, 그 대가(쓰기 복잡·불일치 위험)를 알고 한다.

- 허용되는 경우: 무거운 집계의 캐시(`order_count`), 읽기 전용 리포팅 테이블, 시계열 롤업.
- 반드시: **왜 비정규화했는지 컬럼/테이블 주석**으로 남기고, 동기화 책임(트리거·배치·앱 코드 중 무엇)을 명시한다.
- 비정규화 값은 **파생값**임을 표시한다 — 진실의 출처가 아니라 캐시다.

```sql
-- 의도적 비정규화: customers.order_count 는 orders 집계의 캐시다.
-- 진실의 출처는 orders 테이블. 동기화는 아래 트리거가 담당한다(읽기 핫패스 최적화).
ALTER TABLE customers ADD COLUMN order_count integer NOT NULL DEFAULT 0;
```

---

## 2. 제약 — 무결성은 DB에서 강제한다

앱 레벨 검증만 믿지 않는다. 동시 요청·재시도·다른 클라이언트·수동 쿼리가 우회한다. DB 제약은 마지막 방어선이자 데이터 계약의 일부다.

| 제약 | 무엇을 보장 | 예 |
|---|---|---|
| **PRIMARY KEY** | 행의 유일 식별·NOT NULL | `id bigint GENERATED ALWAYS AS IDENTITY` |
| **FOREIGN KEY** | 참조 무결성(고아 방지) | `REFERENCES customers(id) ON DELETE RESTRICT` |
| **NOT NULL** | 필수값 누락 방지 | `email text NOT NULL` |
| **UNIQUE** | 중복 방지(자연키·이메일 등) | `UNIQUE (email)` |
| **CHECK** | 도메인 규칙(범위·enum·관계) | `CHECK (total_cents >= 0)` |
| **DEFAULT** | 누락 시 안전한 기본값 | `created_at timestamptz NOT NULL DEFAULT now()` |

- **대리키(surrogate key) 기본** — `bigint IDENTITY` 또는 `uuid`. 자연키(이메일·주민번호)는 바뀌거나 노출 위험이 있어 PK로 부적합. 단, 자연키에는 **UNIQUE 제약**을 별도로 건다.
- **시간은 항상 `timestamptz`(UTC)** 로 저장하고, 표시할 때만 타임존 변환한다 (이유: 타임존 버그·DST 사고 방지).
- **금액은 정수 최소단위**(`total_cents bigint`)나 `numeric`으로. `float`/`double`은 반올림 오차로 금지.
- **enum성 컬럼**은 `CHECK (status IN (...))` 또는 Postgres `ENUM` 타입으로 허용값을 강제한다.
- `ON DELETE`는 의도적으로 선택한다: `RESTRICT`(기본·삭제 막음)·`CASCADE`(자식도 삭제)·`SET NULL`. 무심코 CASCADE를 깔지 않는다.

---

## 3. 인덱스 — 조회 경로에 건다

인덱스는 읽기를 빠르게 하지만 쓰기를 느리게 하고 공간을 쓴다. **실제 쿼리 패턴**에 맞춰 건다(상세: `query-performance.md`).

- 항상 인덱스 대상: **FK 컬럼**(조인·`ON DELETE` 검사), **WHERE/JOIN/ORDER BY**에 자주 쓰는 컬럼.
- PK·UNIQUE는 자동으로 인덱스가 생긴다(추가로 만들지 말 것).
- **복합 인덱스는 좌측 접두(leftmost prefix) 규칙**: `(a, b, c)` 인덱스는 `(a)`·`(a,b)`·`(a,b,c)` 쿼리에 쓰이지만 `(b)`·`(c)` 단독엔 안 쓰인다. 컬럼 순서 = 선택도 높은(등치 비교) 것 먼저, 범위 비교는 뒤로.
- **부분 인덱스**(partial): 일부 행만 자주 조회하면 `WHERE` 조건을 단 인덱스로 크기·비용을 줄인다. 예: `WHERE deleted_at IS NULL`.
- **카디널리티 낮은 단독 인덱스 지양**: `gender`·`is_active` 같은 2~3값 컬럼 단독 인덱스는 효과가 작다(복합의 일부로는 유용).

---

## 4. 네이밍 규약 — 일관성이 곧 예측 가능성

규약은 무엇이든 **하나로 정하고 일관**되게 쓰는 게 핵심이다. 아래는 Postgres에서 흔한 기본값이다.

- 테이블: **복수형 snake_case** — `users`, `order_items`.
- 컬럼: **단수 snake_case** — `created_at`, `customer_id`.
- FK 컬럼: `<참조테이블단수>_id` — `customer_id`, `product_id`.
- 불리언: `is_`/`has_` 접두 — `is_active`, `has_paid`.
- 시간: `_at` 접미(시각·timestamptz) — `created_at`, `deleted_at`. 날짜만이면 `_on`.
- 인덱스: `ix_<테이블>_<컬럼들>`, 유니크 인덱스 `ux_`, 제약 `ck_`/`fk_`/`uq_`.
- 예약어(`user`, `order`)는 따옴표 필요를 피하려면 회피하거나 일관되게 인용한다.

---

## 5. 구체 Postgres DDL 템플릿 — users · orders · order_items

복붙해서 시작하는 참조 템플릿. PK·FK·NOT NULL·UNIQUE·CHECK·DEFAULT·인덱스를 모두 포함한다.

```sql
-- ============================================================
-- users — 대리키 PK, 자연키(email) UNIQUE, soft-delete, UTC 시각
-- ============================================================
CREATE TABLE users (
    id            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email         text        NOT NULL,
    display_name  text        NOT NULL,
    status        text        NOT NULL DEFAULT 'active',
    is_active     boolean     NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    deleted_at    timestamptz,                              -- soft delete (NULL = 살아있음)

    CONSTRAINT uq_users_email      UNIQUE (email),
    CONSTRAINT ck_users_status     CHECK (status IN ('active', 'suspended', 'closed')),
    CONSTRAINT ck_users_email_fmt  CHECK (position('@' IN email) > 1)
);

-- 살아있는 행만 자주 조회 → 부분 인덱스
CREATE INDEX ix_users_active ON users (created_at) WHERE deleted_at IS NULL;

-- ============================================================
-- orders — users 참조(FK), 금액은 정수 cents, 상태 enum, 양수 CHECK
-- ============================================================
CREATE TABLE orders (
    id            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id   bigint      NOT NULL,
    status        text        NOT NULL DEFAULT 'pending',
    total_cents   bigint      NOT NULL DEFAULT 0,
    currency      char(3)     NOT NULL DEFAULT 'USD',
    placed_at     timestamptz NOT NULL DEFAULT now(),
    created_at    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT fk_orders_customer
        FOREIGN KEY (customer_id) REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT ck_orders_status
        CHECK (status IN ('pending', 'paid', 'shipped', 'cancelled', 'refunded')),
    CONSTRAINT ck_orders_total_nonneg CHECK (total_cents >= 0)
);

-- FK 컬럼 인덱스(조인·삭제검사 가속) + 고객별 최신순 조회용 복합 인덱스
CREATE INDEX ix_orders_customer       ON orders (customer_id);
CREATE INDEX ix_orders_customer_time  ON orders (customer_id, placed_at DESC);

-- ============================================================
-- order_items — 복합 자연키(order_id, product_id) UNIQUE, 수량 양수
-- ============================================================
CREATE TABLE order_items (
    id              bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id        bigint      NOT NULL,
    product_id      bigint      NOT NULL,
    quantity        integer     NOT NULL,
    unit_price_cents bigint     NOT NULL,

    CONSTRAINT fk_items_order
        FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE CASCADE,
    CONSTRAINT uq_items_order_product UNIQUE (order_id, product_id),  -- 같은 상품 중복행 방지
    CONSTRAINT ck_items_qty_pos       CHECK (quantity > 0),
    CONSTRAINT ck_items_price_nonneg  CHECK (unit_price_cents >= 0)
);

CREATE INDEX ix_items_order ON order_items (order_id);
```

**이 템플릿이 보여주는 결정들**:
- `users.id`는 대리키 PK, `email`은 자연키라서 PK가 아니라 **UNIQUE 제약**.
- `orders.customer_id`는 FK이고 별도 인덱스를 직접 건다(FK는 자동 인덱스를 만들지 않는다).
- `order_items`는 `ON DELETE CASCADE`(주문 삭제 시 항목도 삭제)이지만 `orders.customer_id`는 `RESTRICT`(고객을 함부로 못 지움) — cascade 방향을 **의도적으로** 선택했다.
- 모든 시각은 `timestamptz`, 금액은 정수 cents, 상태는 CHECK enum, 수량·금액은 양수 CHECK로 도메인을 강제한다.
