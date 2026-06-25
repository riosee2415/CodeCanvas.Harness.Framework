# 쿼리 성능 — EXPLAIN 읽기·인덱스 전략·N+1·페이지네이션

> 예시 스택: Postgres. 원칙은 스택 불문 — 네 스택에 맞춰 적용.
> (MySQL `EXPLAIN ANALYZE`·SQL Server 실행계획·BigQuery 쿼리플랜도 동일 원칙:
> 실제 플랜을 측정하고, 조회 경로에 인덱스를 맞추고, N+1을 배치로 없앤다.)

---

## 이 스킬이 잡아야 할 대표 상황

| 상황 | 무엇이 문제인가 |
|---|---|
| **테이블이 커지자 특정 쿼리가 갑자기 느려졌다** | 인덱스 없이 Seq Scan. 데이터가 작을 땐 안 보이다가 커지며 터진다. |
| **목록 화면이 한 페이지에 쿼리 수백 개를 날린다** | N+1. 루프 안에서 행마다 추가 쿼리. 조인·배치로 한 번에. |
| **페이지 뒤로 갈수록 목록이 느려진다** | 큰 OFFSET. 건너뛴 행을 전부 스캔한다. keyset으로 바꾼다. |
| **인덱스를 만들었는데 안 쓰인다** | 컬럼 순서·함수 래핑·타입 불일치로 플래너가 못 쓴다. EXPLAIN으로 확인한다. |

**철칙: 측정 없이 최적화하지 않는다.** 추측으로 인덱스를 추가/삭제하지 말고, 항상 `EXPLAIN (ANALYZE, BUFFERS)`로 실제 플랜과 비용을 근거로 본다.

---

## 1. `EXPLAIN (ANALYZE, BUFFERS)` 읽는 법

- `EXPLAIN` 만: 플래너의 **추정** 계획(쿼리 실행 안 함).
- `EXPLAIN (ANALYZE)`: **실제로 실행**하고 진짜 시간·행수를 보여준다(쓰기 쿼리는 트랜잭션으로 감싸 롤백).
- `BUFFERS` 추가: 읽은 **블록 수**(캐시 hit vs 디스크 read)까지 — I/O 병목을 본다.

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders WHERE customer_id = 42 ORDER BY placed_at DESC LIMIT 20;
```

**읽을 때 보는 신호**:
- **`Seq Scan` on 큰 테이블** + 선택적 WHERE → 인덱스 부재 신호. 작은 테이블이면 정상(풀스캔이 더 쌈).
- **`rows=추정` vs `actual rows=실제` 가 크게 벌어짐** → 통계가 낡음. `ANALYZE <table>;`로 갱신, 그래도 어긋나면 플랜이 틀어질 수 있음.
- **`actual time=`** 가 큰 노드가 병목. 가장 안쪽(들여쓰기 깊은) 노드부터 위로 읽는다.
- **`Buffers: shared read=`** 가 크면 디스크 I/O 많음(캐시 미스). `hit`이면 메모리 캐시.
- **`Rows Removed by Filter:`** 가 크면 인덱스로 거르지 못하고 읽은 뒤 버린 것 → 인덱스/조건 재검토.
- **`Nested Loop` 가 큰 행수**에 걸리면 N+1성 패턴·조인 인덱스 부재 신호.

목표: 큰 테이블 조회가 `Index Scan`/`Index Only Scan`으로 잡히고, removed-by-filter가 작고, 추정≈실제인 상태.

---

## 2. 인덱스 전략 — 복합·부분·커버링

### 복합 인덱스 (좌측 접두 규칙)

`(a, b)` 인덱스는 `WHERE a=?`·`WHERE a=? AND b=?`·`ORDER BY a,b`에 쓰이지만 `WHERE b=?` 단독엔 **안 쓰인다**. 순서가 핵심.

```sql
-- 고객별 + 최신순 조회를 한 인덱스로 (등치 컬럼 먼저, 정렬/범위 컬럼 뒤)
CREATE INDEX ix_orders_customer_time ON orders (customer_id, placed_at DESC);
-- → WHERE customer_id=42 ORDER BY placed_at DESC LIMIT 20  를 인덱스만으로 처리
```

규칙: **등치 비교(`=`) 컬럼을 앞에, 범위(`<`,`>`,`BETWEEN`)·정렬 컬럼을 뒤에.**

### 부분 인덱스 (partial)

전체가 아니라 자주 조회하는 **부분 집합**만 인덱싱 → 작고 빠르고 싸다.

```sql
-- 살아있는(soft-delete 안 된) 행만 조회한다면
CREATE INDEX ix_users_active ON users (created_at) WHERE deleted_at IS NULL;
```

### 커버링 인덱스 (Index Only Scan)

쿼리가 필요로 하는 컬럼을 **인덱스에 모두 포함**시키면 테이블을 안 읽고 인덱스만으로 답한다.

```sql
-- INCLUDE 로 인덱스에 추가 컬럼을 실어 Index Only Scan 유도
CREATE INDEX ix_orders_cover ON orders (customer_id, placed_at DESC) INCLUDE (status, total_cents);
```

### 인덱스가 안 쓰이는 흔한 원인

- 컬럼을 함수로 감쌈: `WHERE lower(email) = ?` → 일반 인덱스 못 씀. **표현식 인덱스**(`CREATE INDEX ... ON users (lower(email))`)를 만든다.
- 타입 불일치: `WHERE id = '42'`(text vs bigint) → 캐스팅으로 인덱스 무효화.
- 선두 와일드카드 `LIKE '%foo'` → B-tree 못 씀(전문검색·trigram 인덱스 고려).
- 너무 많은 행을 가져옴(테이블의 큰 비율) → 플래너가 Seq Scan이 더 싸다고 판단(정상).

---

## 3. N+1 탐지·해소

**N+1**: 목록 N건을 가져온 뒤, 각 건마다 연관 데이터를 1쿼리씩 추가로 날려 1+N 쿼리가 되는 패턴. 가장 흔한 성능 버그.

**나쁜 예 (ORM 의사코드)**:
```python
orders = Order.objects.filter(status="paid")     # 1쿼리
for o in orders:
    print(o.customer.name)                        # 행마다 +1쿼리 → 총 1+N
```

**해소 1 — eager 로딩(조인)**:
```python
orders = Order.objects.filter(status="paid").select_related("customer")  # 1쿼리(JOIN)
```

**해소 2 — 배치 IN 조회**:
```sql
-- 루프 대신 한 번에
SELECT * FROM customers WHERE id IN (1, 2, 3, ...);
```

**탐지 방법**:
- 쿼리 로그/APM에서 **동일 형태 쿼리가 수십~수백 번** 반복되면 N+1.
- 테스트에서 **쿼리 카운트 단언**(`assertNumQueries`)으로 회귀를 막는다.
- ORM은 명시적으로: SQLAlchemy `selectinload`/`joinedload`, Django `select_related`/`prefetch_related`, ActiveRecord `includes`.

---

## 4. 페이지네이션 — keyset(추천) vs OFFSET

### OFFSET의 함정

```sql
-- 1000페이지째: 앞의 20000행을 스캔해서 버리고 20행 반환 → 뒤로 갈수록 느림
SELECT * FROM orders ORDER BY placed_at DESC LIMIT 20 OFFSET 20000;
```
OFFSET은 건너뛸 행을 **전부 읽은 뒤 버린다**. 깊은 페이지일수록 선형으로 느려지고, 그 사이 행이 삽입/삭제되면 중복/누락도 생긴다.

### keyset(seek) 페이지네이션

마지막으로 본 행의 **정렬 키를 커서로** 삼아, 그 지점부터 인덱스로 바로 점프한다. 페이지 깊이와 무관하게 일정한 속도.

```sql
-- 첫 페이지
SELECT id, placed_at, total_cents
FROM orders
ORDER BY placed_at DESC, id DESC
LIMIT 20;

-- 다음 페이지: 직전 페이지 마지막 행의 (placed_at, id)를 커서로 전달
SELECT id, placed_at, total_cents
FROM orders
WHERE (placed_at, id) < (:last_placed_at, :last_id)   -- 복합 비교로 동률 안전 처리
ORDER BY placed_at DESC, id DESC
LIMIT 20;
```

- **정렬 키에 인덱스**가 있어야 한다(`(placed_at DESC, id DESC)`). 그래야 인덱스 seek로 O(log n).
- **타이브레이커로 유니크 컬럼(`id`)을 포함**해 동일 `placed_at`에서 중복/누락을 막는다.
- 무한 스크롤·"더 보기"·API 커서에 적합. 임의 페이지 점프("100페이지로")가 꼭 필요할 때만 OFFSET을 고려한다.

---

## 5. 무거운 집계 — 분리하고 갱신 전략을 명시

- 대시보드·리포트의 무거운 `GROUP BY`/`JOIN`은 매 요청마다 재계산하지 않는다.
- **머티리얼라이즈드 뷰** 또는 **요약 테이블**로 사전 집계하고, 갱신 전략(주기·트리거·증분)을 **명시**한다.

```sql
CREATE MATERIALIZED VIEW mv_daily_sales AS
SELECT date_trunc('day', placed_at) AS day,
       count(*)        AS order_count,
       sum(total_cents) AS revenue_cents
FROM orders
WHERE status = 'paid'
GROUP BY 1;

-- 갱신(스케줄러로 주기 실행). CONCURRENTLY는 읽기를 막지 않음(유니크 인덱스 필요).
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_sales;
```
