# 데이터 검증·계약 — 멱등 파이프라인·dead-letter

> 예시 스택: Postgres + Python(Great Expectations / Pandera) + dbt tests. 원칙은 스택 불문 — 네 스택에 맞춰 적용.
> (Spark·Flink·Airflow·dlt·Soda 등 어떤 파이프라인이든 동일 원칙: 경계에서 검증하고,
> 계약을 명시하고, 깨진 행은 격리하고, 재실행을 멱등하게 만든다.)

---

## 이 스킬이 잡아야 할 대표 상황

| 상황 | 무엇이 문제인가 |
|---|---|
| **업스트림이 컬럼을 빼/이름 바꿔도 파이프라인이 조용히 통과한다** | 스키마 계약·검증이 없는 것. 경계에서 스키마를 강제해야 깨짐을 즉시 잡는다. |
| **한 행이 깨졌다고 전체 배치가 죽는다** | 격리(dead-letter)가 없는 것. 나쁜 행은 따로 빼고 좋은 행은 통과시킨다. |
| **잡을 재시도하니 데이터가 중복 적재됐다** | 멱등하지 않은 것. upsert·자연키·idempotency key로 재실행을 안전하게. |
| **"데이터가 이상하다"는 신고가 사후에 들어온다** | 기대치(expectation) 테스트가 없는 것. null율·범위·행수 같은 불변식을 자동 검증한다. |

**철칙: 검증은 경계에서. 들어오는 데이터를 신뢰하지 않는다.**

---

## 1. 데이터 계약 (Data Contract)

계약 = **스키마 + 제약 + 기대치**를 명시적으로 합의·문서화한 것. 생산자와 소비자 사이의 인터페이스다.

세 층으로 구성한다:
1. **스키마**: 컬럼명·타입·nullable·순서. (예: `customer_id: bigint, NOT NULL`)
2. **제약**: 도메인 규칙. (`total_cents >= 0`, `status ∈ {pending,paid,...}`, `email` UNIQUE)
3. **기대치(statistical expectations)**: 분포·불변식. (`null율(email) < 1%`, `행수가 전일 대비 ±20% 이내`, `id 유일`)

계약은 **버전**을 갖고, 변경 시 **하위호환**을 고려한다(컬럼 추가는 안전, 삭제·타입변경·의미변경은 breaking → expand-contract처럼 단계적으로). 깨지는 변경은 소비자에 사전 통지한다.

---

## 2. 검증 도구 패턴

### Pandera — 데이터프레임 스키마 (코드로 강제)

```python
import pandera as pa
from pandera.typing import Series

class OrdersSchema(pa.DataFrameModel):
    order_id: Series[int]   = pa.Field(unique=True, ge=1)
    customer_id: Series[int] = pa.Field(ge=1, nullable=False)
    status: Series[str]     = pa.Field(isin=["pending", "paid", "shipped", "cancelled", "refunded"])
    total_cents: Series[int] = pa.Field(ge=0)
    email: Series[str]      = pa.Field(str_matches=r".+@.+\..+", nullable=False)

    class Config:
        strict = True   # 정의 안 된 컬럼이 들어오면 실패 → 스키마 드리프트 즉시 감지

# 경계에서 검증 — lazy=True 로 모든 위반을 한 번에 수집
validated = OrdersSchema.validate(df, lazy=True)
```

### Great Expectations — 기대치 스위트(분포·불변식)

```python
# 의사코드: 통계적 기대치를 선언적으로 명시
batch.expect_column_values_to_not_be_null("customer_id")
batch.expect_column_values_to_be_between("total_cents", min_value=0)
batch.expect_column_values_to_be_in_set("status", ["pending", "paid", "shipped", "cancelled", "refunded"])
batch.expect_column_proportion_of_unique_values_to_be_between("order_id", 1.0, 1.0)  # 완전 유일
batch.expect_table_row_count_to_be_between(min_value=1)
# → 결과를 게이트로: 실패 시 다운스트림 적재를 막는다.
```

### dbt tests — 웨어하우스 모델 검증

```yaml
# models/schema.yml — 변환 모델에 테스트를 붙인다(dbt test 로 실행)
models:
  - name: orders
    columns:
      - name: order_id
        tests: [unique, not_null]
      - name: customer_id
        tests:
          - not_null
          - relationships:        # FK 무결성(참조 깨짐 감지)
              to: ref('customers')
              field: id
      - name: status
        tests:
          - accepted_values:
              values: ['pending', 'paid', 'shipped', 'cancelled', 'refunded']
```

**고르는 기준**: 데이터프레임(pandas/Spark) 단계 → Pandera. 적재 게이트·풍부한 리포트 → Great Expectations. 웨어하우스/ELT 모델 → dbt tests. SQL 정적 점검 → sqlglot(`mcp-and-tools.md`).

---

## 3. dead-letter — 깨진 행 격리

한 행이 깨졌다고 파이프라인 전체를 멈추지 않는다. **좋은 행은 통과**시키고 **나쁜 행은 사유와 함께 따로** 빼서 사람이 나중에 조사한다.

```python
good_rows, dead_letters = [], []
for row in incoming:
    try:
        good_rows.append(validate_and_transform(row))   # 스키마·제약 검증
    except ValidationError as e:
        dead_letters.append({
            "raw": row,
            "error": str(e),
            "received_at": now_utc(),
            "source": source_id,
        })

load(good_rows)                        # 정상 행 적재
if dead_letters:
    write_dead_letter_table(dead_letters)  # 격리 테이블/큐로 — 손실 없이 보존
    alert_if_threshold_exceeded(len(dead_letters), len(incoming))  # 비율 임계 초과 시 경보
```

원칙:
- 나쁜 행을 **버리지 않는다** — dead-letter 테이블/큐에 원본+사유+시각을 보존한다.
- dead-letter **비율을 모니터**하고 임계(예: 5%) 초과 시 경보·파이프라인 중단을 검토한다.
- 격리된 행은 **재처리 경로**를 둔다(고친 뒤 다시 흘려보내기).

---

## 4. 멱등성 — 재실행해도 안전하게

**멱등**: 같은 입력으로 여러 번 실행해도 결과가 한 번 실행과 같다. 재시도·중복 전달·부분 실패 복구가 일상이므로 파이프라인은 멱등해야 한다.

### 패턴 1 — upsert (자연키/PK 충돌 시 갱신)

```sql
INSERT INTO orders (id, customer_id, status, total_cents)
VALUES (:id, :customer_id, :status, :total_cents)
ON CONFLICT (id) DO UPDATE
SET status = EXCLUDED.status,
    total_cents = EXCLUDED.total_cents;
-- → 같은 id로 두 번 적재해도 행이 중복되지 않고 최신값으로 수렴.
```

### 패턴 2 — idempotency key (처리 여부 기록)

```sql
-- 메시지/이벤트마다 유니크 키. 이미 처리한 키면 건너뛴다.
INSERT INTO processed_events (event_id, processed_at)
VALUES (:event_id, now())
ON CONFLICT (event_id) DO NOTHING
RETURNING event_id;
-- → RETURNING 이 비면 "이미 처리됨" → 부작용을 다시 실행하지 않는다.
```

### 패턴 3 — 결정적 배치(파티션 덮어쓰기)

```sql
-- 날짜 파티션을 통째로 다시 계산해 덮어쓴다(append 누적 금지).
DELETE FROM daily_sales WHERE day = :target_day;
INSERT INTO daily_sales SELECT ... WHERE date_trunc('day', placed_at) = :target_day;
-- → 같은 날을 몇 번 돌려도 그 날 결과는 항상 동일.
```

**자문 한 줄**: "이 잡을 지금 다시 돌리면 데이터가 중복되거나 어긋나는가?" 그렇다면 아직 멱등하지 않다.

---

## 5. 검증을 어디에 거나 (방어선 정리)

| 위치 | 무엇을 검증 | 도구 |
|---|---|---|
| **수집 경계(ingest)** | 스키마·타입·필수·범위. 나쁜 행 dead-letter | Pandera / 앱 검증 |
| **적재 게이트(load)** | 기대치·행수·null율 불변식 | Great Expectations |
| **DB 제약** | PK·FK·UNIQUE·CHECK·NOT NULL (마지막 방어선) | Postgres 제약 (`schema-design.md`) |
| **변환 후(transform)** | 모델 무결성·참조·accepted values | dbt tests |

여러 층을 겹친다 — 어느 한 층이 빠뜨려도 다음 층이 잡는다. DB 제약은 우회 불가능한 최종 방어선이므로 절대 생략하지 않는다.
