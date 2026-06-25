# 테스트 설계 — 악취와 좋은 원칙

> 예시 스택: pytest (Python) / vitest (TypeScript). 원칙은 스택 불문 — 네 스택에 맞춰 적용.

---

## 이 스킬이 잡아야 할 대표 상황

| 상황 | 왜 설계가 중요한가 |
|---|---|
| **테스트가 통과하는데 버그가 잡힌다** | 단언이 없거나 약한 것. 테스트가 존재해도 실제 동작을 검증하지 않는다. |
| **구현을 조금만 바꿔도 테스트가 우수수 깨진다** | 구현 세부를 직접 테스트한 것. 리팩토링 내성이 없다. |
| **테스트 셋업이 코드보다 길다** | mock이 과도한 것. 설계 자체가 복잡하다는 신호. |

---

## 테스트 악취 3종

### 악취 1 — 아무것도 단언 안 함 (Pass-Without-Asserting)

**나쁜 예:**
```python
def test_send_email():
    service = EmailService()
    service.send("user@example.com", "Hello")
    # assert 없음 — 예외만 안 나면 green
```

왜 나쁜가: 이 테스트는 예외가 없으면 항상 통과한다. 실제로 이메일이 전송됐는지, 올바른 주소로 갔는지 전혀 검증하지 않는다.

**좋은 예:**
```python
def test_send_email_calls_transport_once():
    transport = FakeTransport()
    service = EmailService(transport=transport)
    service.send("user@example.com", "Hello")
    assert transport.sent_count == 1
    assert transport.last_recipient == "user@example.com"
```

핵심: 단언은 **관찰 가능한 결과**(반환값, 상태 변화, 부작용)를 구체적 값으로 검증한다.

---

### 악취 2 — 구현 세부 테스트 (Testing Implementation Details)

**나쁜 예:**
```python
def test_uses_regex_for_validation():
    validator = EmailValidator()
    # 내부 정규식 패턴 객체를 직접 검사
    assert validator._pattern.pattern == r"^[^@]+@[^@]+\.[^@]+$"
```

왜 나쁜가: 내부 구현(`_pattern`)이 바뀌면 테스트가 깨진다. 리팩토링할 때마다 테스트도 고쳐야 하므로 TDD의 안전망 역할을 못한다.

**좋은 예:**
```python
@pytest.mark.parametrize("address,expected", [
    ("user@example.com", True),
    ("userexample.com", False),
    ("user@", False),
    ("", False),
])
def test_email_validation(address, expected):
    validator = EmailValidator()
    assert validator.is_valid(address) is expected
```

핵심: 공개 인터페이스(행동)를 테스트한다. 내부 구현은 어떻게 바뀌든 상관없다.

---

### 악취 3 — 과도한 mock (Over-Mocking)

**나쁜 예:**
```typescript
// vitest 예시
test("사용자 생성 성공", async () => {
  const mockDb = vi.fn();
  const mockValidator = vi.fn().mockReturnValue(true);
  const mockHasher = vi.fn().mockReturnValue("hashed");
  const mockEmailer = vi.fn();
  const mockLogger = vi.fn();
  const mockAudit = vi.fn();

  const service = new UserService(mockDb, mockValidator, mockHasher, mockEmailer, mockLogger, mockAudit);
  await service.create({ name: "Alice", email: "alice@example.com" });

  expect(mockDb).toHaveBeenCalledWith(expect.objectContaining({ name: "Alice" }));
});
```

왜 나쁜가: mock이 6개. 셋업이 서비스 코드보다 길다. 이 테스트는 "mock을 올바르게 연결했는가"를 검증할 뿐, 실제 동작을 검증하지 않는다. 결합도가 높다는 설계 경고다.

**좋은 예:**
```typescript
test("사용자 생성 — 저장된 사용자 반환", async () => {
  const repo = new InMemoryUserRepository();  // 가벼운 페이크
  const service = new UserService(repo);

  const user = await service.create({ name: "Alice", email: "alice@example.com" });

  expect(user.id).toBeDefined();
  expect(repo.findById(user.id)?.name).toBe("Alice");
});
```

핵심: 외부 경계(HTTP, DB, 파일 시스템)만 페이크/스텁으로 교체한다. 내부 협력자는 실제 객체를 쓴다. mock이 많을수록 의존성 주입 재검토 신호.

---

## 좋은 설계 원칙

### AAA 패턴 (Arrange · Act · Assert)

```python
def test_discount_applied_for_premium_user():
    # Arrange — 테스트 대상과 데이터를 준비
    cart = Cart(user_tier="premium")
    cart.add_item(price=100)

    # Act — 단 하나의 행동
    total = cart.calculate_total()

    # Assert — 결과를 검증
    assert total == 90  # 10% 할인 적용
```

각 구역 사이에 빈 줄을 넣어 시각적으로 분리한다.

---

### 1행동 · 1테스트 원칙

**나쁜 예:**
```python
def test_user_registration_and_login_and_profile():
    user = create_user("alice", "pw")
    token = login("alice", "pw")
    profile = get_profile(token)
    assert user.id is not None    # 등록
    assert token is not None      # 로그인
    assert profile.name == "alice"  # 프로필
```

**좋은 예:**
```python
def test_create_user_returns_id():
    user = create_user("alice", "pw")
    assert user.id is not None

def test_login_returns_token():
    create_user("alice", "pw")
    token = login("alice", "pw")
    assert token is not None

def test_get_profile_returns_name():
    create_user("alice", "pw")
    token = login("alice", "pw")
    profile = get_profile(token)
    assert profile.name == "alice"
```

실패하면 정확히 **무엇이** 깨졌는지 테스트 이름만으로 알 수 있다.

---

### 경계값 · 에러 경로 테스트

정상 경로만 테스트하면 실제 버그의 80%를 놓친다. 반드시 함께 테스트한다.

```python
class TestEmailValidator:
    # 정상 경로
    def test_valid_email_accepted(self):
        assert is_valid_email("user@example.com") is True

    # 경계값
    def test_single_char_local_part(self):
        assert is_valid_email("a@b.co") is True

    def test_subdomain_accepted(self):
        assert is_valid_email("user@mail.example.com") is True

    # 에러 경로
    def test_empty_string_rejected(self):
        assert is_valid_email("") is False

    def test_none_raises(self):
        with pytest.raises(TypeError):
            is_valid_email(None)

    def test_unicode_domain_rejected(self):
        assert is_valid_email("user@exämple.com") is False
```

체크리스트: 테스트를 작성할 때마다 "빈 값 · None · 경계값 · 잘못된 타입 · 예외 경로"를 자문한다.
