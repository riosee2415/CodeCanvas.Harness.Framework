# TDD 완주 사이클 — 작동 예제

> 예시 스택: pytest (Python). 원칙은 스택 불문 — 네 스택에 맞춰 적용.

---

## 이 스킬이 잡아야 할 대표 상황

| 상황 | 왜 TDD가 필요한가 |
|---|---|
| **신규 기능** | 설계를 먼저 강제한다. 테스트가 인터페이스를 드러내고, 불필요한 코드가 자라는 것을 막는다(YAGNI). |
| **버그 재현** | "이미 수동으로 봤어"는 신뢰할 수 없다. 실패하는 테스트를 먼저 써서 버그를 고정하고, fix 이후 회귀를 막는다. |
| **리팩토링 안전망** | green 스위트 없이 리팩토링하면 뭔가 깨졌는지 알 수 없다. 모든 테스트가 green일 때만 구조를 바꾼다. |

---

## 예제: 이메일 주소 검증 함수

### Step 1 — RED: 실패하는 테스트 먼저

```python
# tests/test_email_validator.py
import pytest
from app.email_validator import is_valid_email


def test_valid_email_accepted():
    assert is_valid_email("user@example.com") is True


def test_missing_at_sign_rejected():
    assert is_valid_email("userexample.com") is False


def test_missing_domain_rejected():
    assert is_valid_email("user@") is False
```

**실행 → 실제 실패 출력:**
```
$ pytest tests/test_email_validator.py -v

FAILED tests/test_email_validator.py::test_valid_email_accepted
FAILED tests/test_email_validator.py::test_missing_at_sign_rejected
FAILED tests/test_email_validator.py::test_missing_domain_rejected

ModuleNotFoundError: No module named 'app.email_validator'

3 failed, 0 passed in 0.04s
```

핵심: `ModuleNotFoundError`(파일 없음)가 아니라 **기능이 없어서 실패**함을 확인.
파일을 만들기 전에 실패 유형이 옳은지 먼저 점검한다.

---

### Step 2 — GREEN: 통과시키는 최소 구현

```python
# app/email_validator.py
import re

_EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email))
```

**실행 → green 확인:**
```
$ pytest tests/test_email_validator.py -v

PASSED tests/test_email_validator.py::test_valid_email_accepted
PASSED tests/test_email_validator.py::test_missing_at_sign_rejected
PASSED tests/test_email_validator.py::test_missing_domain_rejected

3 passed in 0.03s
```

주의: 정규식 `[^@]+\.[^@]+` 이상의 복잡한 RFC 5321 파서는 **지금 요청된 것이 아니다(YAGNI)**. 최소만.

---

### Step 3 — REFACTOR: 중복 제거·이름 개선 (green 유지)

```python
# app/email_validator.py — 리팩토링 후
import re

# 패턴을 모듈 상수로 분리 (가독성)
_BASIC_EMAIL_PATTERN = re.compile(r"^[^@]+@[^@]+\.[^@]+$")


def is_valid_email(address: str) -> bool:
    """최소 형식의 이메일인지 확인 (RFC 완전 준수 아님)."""
    return bool(_BASIC_EMAIL_PATTERN.match(address))
```

변경 내용:
- 파라미터 이름 `email` → `address` (함수 내부에서 더 명확)
- 상수 이름 `_EMAIL_RE` → `_BASIC_EMAIL_PATTERN` (역할 명시)
- 독스트링 추가

**실행 → 여전히 green:**
```
$ pytest tests/test_email_validator.py -v

PASSED tests/test_email_validator.py::test_valid_email_accepted
PASSED tests/test_email_validator.py::test_missing_at_sign_rejected
PASSED tests/test_email_validator.py::test_missing_domain_rejected

3 passed in 0.02s
```

---

### Step 4 — 전체 스위트 green 확인

```
$ pytest --tb=short

====================== test session results =======================
3 passed in 0.04s
```

모든 테스트 green. 다음 행동을 위한 다음 실패 테스트로 사이클 반복.

---

## 버그 재현 패턴 (추가 예)

버그 리포트: "공백만 있는 문자열이 valid로 통과된다"

```python
# 1. 먼저 실패하는 회귀 테스트를 추가
def test_whitespace_only_rejected():
    assert is_valid_email("   ") is False
```

실행 → RED 확인 → fix 후 GREEN → 회귀 보호 완료.
이 순서 없이 fix만 하면 해당 케이스가 나중에 다시 깨져도 알 수 없다.
