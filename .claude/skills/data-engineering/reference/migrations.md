# 마이그레이션 — 되돌릴 수 있는 무중단 스키마 변경

> 예시 스택: Postgres (+ Alembic / 순수 SQL). 원칙은 스택 불문 — 네 스택에 맞춰 적용.
> (Flyway·Prisma Migrate·Rails·Django·Liquibase 등도 동일 원칙: up/down 쌍·멱등성·
> expand-contract로 락을 짧게. 도구 문법만 바꾼다.)

---

## 이 스킬이 잡아야 할 대표 상황

| 상황 | 왜 절차가 중요한가 |
|---|---|
| **마이그레이션이 운영에서 실패했는데 되돌릴 수가 없다** | down이 없거나 검증 안 된 것. 모든 마이그레이션은 되돌릴 수 있어야 한다. |
| **`ALTER TABLE`이 큰 테이블을 락 걸어 서비스가 멈췄다** | 한 트랜잭션에 무거운 변경을 몰아넣은 것. expand-contract로 락을 쪼갠다. |
| **NOT NULL 컬럼을 한 번에 추가하다 전체 rewrite·다운타임 발생** | 즉시 NOT NULL은 위험. nullable 추가→백필→제약을 분리한다. |
| **마이그레이션을 두 번 돌리니 깨졌다** | 멱등하지 않은 것. `IF NOT EXISTS`·존재 검사로 재실행 안전하게. |

---

## 1. 철의 규칙

- **모든 마이그레이션은 up/down 쌍**으로 작성한다. down을 실제로 실행해 **되돌아가는지 검증**한다(머릿속으로 믿지 않는다).
- **멱등하게** 만든다: `IF NOT EXISTS` / `IF EXISTS` / 존재 검사. 재실행해도 같은 상태.
- **파괴적 변경(drop·rename·타입변경)은 단독 마이그레이션**으로 분리한다. 다른 변경과 섞지 않는다(롤백 단위를 작게).
- **한 번에 락을 오래 잡지 않는다**. 큰 테이블의 무거운 DDL은 expand-contract로 여러 배포에 나눠 한다.
- 데이터는 코드보다 오래 산다 — drop 전에 백업·기간(예: 2 배포 주기) 유예를 둔다.

---

## 2. 되돌릴 수 있는 up/down — 순수 SQL

```sql
-- migrations/0007_add_orders_currency.up.sql
ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS currency char(3) NOT NULL DEFAULT 'USD';
```

```sql
-- migrations/0007_add_orders_currency.down.sql
ALTER TABLE orders
    DROP COLUMN IF EXISTS currency;
```

**되돌릴 수 없는 변경의 down은 어떻게?** 컬럼 drop처럼 데이터를 잃는 변경은 down으로 완전 복원이 불가능하다. 이때는:
1. up에서 즉시 drop하지 말고 **rename(보존)** → 유예 후 별도 마이그레이션에서 drop.
2. 또는 down에 "구조는 복원하되 데이터는 백업에서"라고 명시하고, 사전에 백업 단계를 둔다.

---

## 3. 되돌릴 수 있는 up/down — Alembic

```python
# alembic/versions/0007_add_orders_currency.py
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"

def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("currency", sa.CHAR(3), nullable=False, server_default="USD"),
    )

def downgrade() -> None:
    op.drop_column("orders", "currency")
```

Alembic은 `op.f()`·`if_exists` 옵션이 방언마다 다르니, 멱등성이 필요한 운영 스크립트에선 순수 SQL `IF NOT EXISTS`를 `op.execute()`로 쓰는 것도 방법이다.

---

## 4. 무중단 expand-contract — NOT NULL 컬럼 추가 (4단계)

가장 흔한 위험 변경: "`orders`에 NOT NULL `region` 컬럼 추가". 한 번에 하면 전체 rewrite + 긴 락. 아래처럼 **여러 배포로 쪼갠다**.

### 단계 A — Expand: nullable로 추가 (배포 1)

```sql
-- up: 즉시·짧은 락. NOT NULL/DEFAULT를 한 번에 강제하지 않는다.
ALTER TABLE orders ADD COLUMN IF NOT EXISTS region text;  -- nullable
```
이 시점부터 앱은 **새 행에 region을 함께 쓰기 시작**한다(이중 쓰기). 기존 행은 아직 NULL.

### 단계 B — Backfill: 배치로 채운다 (단독·멱등)

```sql
-- 한 번에 전 테이블 UPDATE 금지(긴 락·WAL 폭발). 배치로 끊는다.
-- 멱등: region IS NULL 인 행만 갱신하므로 재실행해도 안전.
UPDATE orders
SET region = 'unknown'
WHERE id IN (
    SELECT id FROM orders
    WHERE region IS NULL
    ORDER BY id
    LIMIT 5000            -- 배치 크기 — 락·트랜잭션 시간을 짧게
);
-- → 영향 행이 0이 될 때까지 반복(스크립트 루프 / 잡 스케줄러).
```

### 단계 C — Switch + Constraint: NOT NULL 강제 (배포 2)

백필이 끝나 NULL이 0임을 확인한 뒤, 제약을 추가한다. Postgres는 `NOT VALID`로 락을 줄이는 패턴을 쓸 수 있다.

```sql
-- 1) CHECK 제약을 NOT VALID로 추가(기존 행 검사 스킵 → 짧은 락)
ALTER TABLE orders
    ADD CONSTRAINT ck_orders_region_present CHECK (region IS NOT NULL) NOT VALID;

-- 2) 별도로 검증(이때만 풀스캔, 그러나 쓰기 막지 않음)
ALTER TABLE orders VALIDATE CONSTRAINT ck_orders_region_present;

-- 3) (선택) 컬럼 자체를 NOT NULL로 — 위 CHECK가 보장되면 안전
ALTER TABLE orders ALTER COLUMN region SET NOT NULL;
```

### 단계 D — Contract: 옛 경로 정리 (배포 3)

이중 쓰기/구컬럼이 있었다면 이제 제거한다. 항상 **마지막에, 단독으로**.

```sql
-- 예: 옛 컬럼 제거(유예 기간이 지난 뒤)
ALTER TABLE orders DROP COLUMN IF EXISTS old_region;
```

**왜 이렇게 쪼개나**: 각 단계는 짧은 락만 잡고 독립적으로 롤백 가능하다. 어느 단계에서 문제가 생겨도 전체를 되돌리지 않고 그 단계만 멈출 수 있다. 컬럼 rename·타입 변경도 같은 패턴: **새 컬럼 추가 → 백필 → 앱 이중쓰기 → 읽기 전환 → 구컬럼 drop**.

---

## 5. 백필 배치 — 멱등성 체크리스트

- **WHERE로 "아직 처리 안 된 행"만** 갱신한다(`region IS NULL`) → 재실행 안전.
- **LIMIT으로 배치**를 끊어 트랜잭션·락 시간을 짧게(예: 1k~10k행).
- **진행 상황을 키 순서**로(`ORDER BY id`, keyset) 추적해 재시작 가능하게.
- 배치 사이에 짧은 sleep·vacuum 여유를 둬 운영 트래픽을 막지 않는다.
- 큰 백필은 마이그레이션 도구(트랜잭션 1개)가 아니라 **별도 잡/스크립트**로 돌리는 게 안전하다(긴 트랜잭션 = 긴 락).

---

## 6. 위험 변경 빠른 표 (Postgres)

| 하려는 것 | 위험 | 안전한 방법 |
|---|---|---|
| NOT NULL 컬럼 추가 | 전체 rewrite·긴 락 | nullable 추가 → 백필 → CHECK NOT VALID → VALIDATE |
| 컬럼 타입 변경 | rewrite·락 | 새 컬럼 추가 → 백필 → 이중쓰기 → 전환 → drop |
| 컬럼 rename | 앱 배포와 원자성 안 맞음 | 새 컬럼 추가(expand) → 이중쓰기 → 전환 → 구컬럼 drop(contract) |
| 인덱스 추가 | 테이블 쓰기 락 | `CREATE INDEX CONCURRENTLY`(트랜잭션 밖) |
| 큰 테이블 DELETE/UPDATE | 긴 락·WAL | 배치로 끊어서 |
