# 워크스루: 체계적 디버깅 실전 예제

> 예시 스택: Python 3.11 · pytest 8 · SQLite (경량 REST API)
> 원칙은 스택 불문 — 네 스택에 맞춰 적용하라.

---

## 배경: 어떤 버그인가

`GET /api/users/{id}` 엔드포인트가 **특정 사용자에게만 간헐적으로 500을 반환**한다.
로컬에서는 재현되지 않는다는 보고가 들어왔다.

---

## 단계 0: 증거 수집 (추측 금지)

먼저 로그·스택트레이스·에러 메시지를 **끝까지** 읽는다. 건너뛰지 않는다.

```
ERROR 2025-06-10 14:32:01 [app.users] Unhandled exception in GET /api/users/42
Traceback (most recent call last):
  File "app/routes/users.py", line 28, in get_user
    return serialize_user(db.get(user_id))
  File "app/serializers.py", line 14, in serialize_user
    return {"id": user.id, "email": user.email, "joined": user.joined_at.isoformat()}
AttributeError: 'NoneType' object has no attribute 'id'
```

**관찰**: `db.get(user_id)`가 `None`을 반환 → `serialize_user`가 `None`을 받아 터짐.

---

## 단계 1: 가설 수립 (글로 적는다)

> **가설**: `db.get(user_id)`는 존재하지 않는 ID에 대해 `None`을 반환한다.
> `serialize_user`는 이를 처리하지 않는다.
> 왜 "특정 사용자"에게만? → 해당 계정이 삭제됐거나 ID 42가 실제로 없는 케이스다.

가설은 **하나**. 한 번에 한 변수만.

---

## 단계 2: 결정론적 재현 (최소 케이스 확보)

"로컬에서 안 된다"는 보고를 그대로 믿지 않는다. 최소 케이스를 직접 만든다.

```python
# tests/test_users.py — 기존 테스트에 추가 (아직 실패해야 정상)
def test_get_nonexistent_user_returns_404(client):
    """존재하지 않는 user_id는 404를 반환해야 한다."""
    response = client.get("/api/users/99999")
    assert response.status_code == 404
```

실행:
```bash
pytest tests/test_users.py::test_get_nonexistent_user_returns_404 -v
# FAILED — AttributeError: 'NoneType' object has no attribute 'id'
```

재현 성공. 이제 고치기 전에 **원인을 확인**한다.

---

## 단계 3: 이분 탐색으로 격리

스택트레이스가 짧으므로 두 지점을 확인한다.

1. `db.get(99999)` — `None` 반환 확인
2. `serialize_user(None)` — 예외 발생 확인

```python
# 빠른 검증 (REPL / 임시 print)
user = db.get(99999)
print(user)  # → None  (DB 레이어는 None 반환이 의도된 동작)
```

근본 원인: `routes/users.py`의 `get_user` 핸들러가 `None` 반환 시 **404 처리 없이** 바로 `serialize_user`에 넘긴다.

```python
# app/routes/users.py:28 — 현재 코드 (버그)
def get_user(user_id: int):
    return serialize_user(db.get(user_id))   # None 검사 없음
```

---

## 단계 4: 근본 원인 지목

> **근본 원인**: `get_user` 핸들러가 `db.get()` 결과를 None 검사 없이
> `serialize_user`에 전달한다. 이것이 증상(`AttributeError`)이 아닌 실제 버그다.
> (왜 그 지점인가: serialize_user는 None을 받을 것을 설계상 가정하지 않는다 —
> DB 레이어의 명세는 "없으면 None 반환"이므로 핸들러가 None을 가드해야 한다.)

---

## 단계 5: 수정 (최소 변경)

```python
# app/routes/users.py — 수정 후
def get_user(user_id: int):
    user = db.get(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return serialize_user(user)
```

**한 번에 한 곳만** 바꿨다.

---

## 단계 6: 재현 케이스로 통과 확인

```bash
pytest tests/test_users.py::test_get_nonexistent_user_returns_404 -v
# PASSED

pytest tests/test_users.py -v
# 기존 테스트 전체 통과 확인 — 회귀 없음
```

수정이 재현 케이스를 해소했고, 다른 테스트가 깨지지 않았다.

---

## 단계 7: 회귀 테스트 추가 (이미 위에서 작성)

`test_get_nonexistent_user_returns_404`가 그 자체로 회귀 테스트다.
CI에 포함시켜 영구히 보호한다.

```bash
# CI에서 이 테스트가 실행되는지 확인
grep "test_get_nonexistent_user" .github/workflows/*.yml || echo "CI 파이프라인에 pytest 있으면 자동 포함"
```

---

## 이 스킬이 잡아야 할 대표 상황

| 상황 | 패턴 | 첫 행동 |
|---|---|---|
| **간헐 실패** (flaky test, 특정 환경에서만) | 타이밍·공유 상태·외부 의존성 문제 | 실패 로그 확보 → 결정론적 재현 케이스 만들기 (seed 고정, mock 교체) |
| **잘못된 출력** (숫자·날짜·텍스트가 틀림) | 변환·직렬화·타임존·인코딩 버그 | 기대값과 실제값 나란히 놓고 "어디서 갈라지나" 이분 탐색 |
| **회귀** (이전엔 됐는데 지금은 안 됨) | 최근 커밋·의존성 버전업 | `git bisect` 또는 최근 변경 diff 먼저, 작동하는 버전과 비교 |

> 간헐 실패는 재현이 가장 어렵다. 먼저 환경(OS·타임존·병렬 워커 수·랜덤 시드)을 고정하고,
> 실패 로그를 반복 실행으로 축적해 패턴을 찾는다.
