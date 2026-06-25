# 컴포넌트 패턴 — 단일책임 · 구성>설정 · 프리미티브 · 제어/비제어

> 예시 스택: React+TS+Tailwind+shadcn·Radix. 원칙은 스택 불문 — 네 스택에 맞춰 적용.
> (Vue·Svelte·Solid 어디든 동일: 컴포넌트는 한 가지 일을, props 폭발 대신 합성으로,
>  접근성 있는 프리미티브 위에 빌드하고, 상태는 제어/비제어를 의식적으로 고른다.)

---

## 이 스킬이 잡아야 할 대표 상황

| 상황 | 무엇이 문제인가 |
|---|---|
| **`<Card>`가 헤더·바디·푸터·아바타·뱃지를 boolean props로 다 받는다** | props 폭발(설정 과잉). 합성(children/슬롯)으로 쪼갠다. |
| **한 컴포넌트가 fetch·상태·렌더·포맷을 다 한다** | 단일책임 위반. 데이터/표현을 분리한다. |
| **드롭다운·모달·탭을 `div`로 직접 만들어 키보드가 안 된다** | 접근성을 재발명. Radix/shadcn 프리미티브 위에 빌드한다. |
| **인풋 값을 부모가 못 읽거나, 반대로 매 키 입력마다 리렌더가 과하다** | 제어/비제어 선택 실수. 필요에 맞게 명시적으로 고른다. |

**철칙: 한 컴포넌트는 한 가지 일. 합성 > 설정. 접근성은 프리미티브에서 가져온다.**

---

## 1. 단일책임 (Single Responsibility)

한 컴포넌트는 한 가지 이유로만 바뀌어야 한다. 데이터 가져오기 / 상태 관리 / 표현을 한 덩어리에 섞지 않는다.

**나쁜 예** — 컨테이너가 fetch·상태·포맷·렌더를 다 함.
```tsx
function UserCard({ userId }: { userId: string }) {
  const [user, setUser] = useState(null);
  useEffect(() => { fetch(`/api/users/${userId}`).then(/* … */); }, [userId]);
  return <div>{user && `${user.name} · ${new Date(user.joined).toLocaleDateString()}`}</div>;
}
```

**교정** — 데이터(훅)와 표현(presentational)을 분리.
```tsx
function useUser(userId: string) { /* fetch/캐싱 책임만 */ }

function UserCard({ user }: { user: User }) {           // 표현 책임만 — 순수·테스트 쉬움
  return <Card><CardTitle>{user.name}</CardTitle><CardMeta>{formatDate(user.joined)}</CardMeta></Card>;
}
```

## 2. 구성 > 설정 (Composition over Configuration)

기능을 boolean/enum props로 계속 더하면 props가 폭발하고 분기가 얽힌다. 대신 **children·슬롯·합성**으로 조립한다.

**나쁜 예** — props로 모든 변형을 제어(설정 과잉).
```tsx
<Card title="제목" subtitle="부제" hasAvatar avatarUrl="…" badge="NEW" footerButton="저장" footerOnClick={fn} />
```

**교정** — 합성 가능한 하위 컴포넌트(shadcn `Card` 패턴)로 조립.
```tsx
<Card>
  <CardHeader>
    <Avatar src="…" />
    <div><CardTitle>제목</CardTitle><CardDescription>부제</CardDescription></div>
    <Badge>NEW</Badge>
  </CardHeader>
  <CardContent>{/* … */}</CardContent>
  <CardFooter><Button>저장</Button></CardFooter>
</Card>
```
> 변형은 **소수의 의미 있는 variant prop**으로만 남긴다(예: `<Button variant="primary" size="sm">`). cva 같은 variant 도구로 토큰과 묶는다.

## 3. 접근성 프리미티브 위에 빌드 (Radix / shadcn)

드롭다운·다이얼로그·탭·툴팁·콤보박스 등 상호작용 위젯을 **직접 만들지 않는다**. Radix 프리미티브가 키보드·포커스 관리·ARIA·`prefers-reduced-motion`을 내장한다. shadcn/ui는 그 위에 토큰 기반 스타일을 입힌 복사-가능 컴포넌트다.

```tsx
import * as Dialog from "@radix-ui/react-dialog";
// 포커스 트랩·Esc 닫기·aria-modal·스크롤 잠금이 전부 내장 — 직접 구현 ✗
<Dialog.Root>
  <Dialog.Trigger asChild><Button>열기</Button></Dialog.Trigger>
  <Dialog.Portal>
    <Dialog.Overlay className="fixed inset-0 bg-foreground/40" />
    <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-card p-6 shadow-md">
      <Dialog.Title>확인</Dialog.Title>
      {/* … */}
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>
```
- 스타일은 토큰(`bg-card`/`border-border`/`shadow-md`)으로(`reference/design-tokens.md`).
- `asChild`로 트리거를 우리 `<Button>`에 합성한다(엘리먼트를 중첩하지 않음).

## 4. 제어 / 비제어 (Controlled / Uncontrolled)

상태를 누가 소유하는지 **의식적으로** 고른다.

| | 비제어(uncontrolled) | 제어(controlled) |
|---|---|---|
| 값 소유 | 컴포넌트 내부(`defaultValue`) | 부모(`value` + `onChange`) |
| 언제 | 부모가 값을 실시간으로 알 필요 없을 때(단순 폼 입력) | 검증·연동·표시를 부모가 해야 할 때 |
| 비용 | 리렌더 적음 | 키 입력마다 부모 리렌더 → 큰 폼은 최적화 필요 |

```tsx
// 비제어 — 제출 시에만 값을 읽음
<input name="email" defaultValue="" />

// 제어 — 부모가 매 입력을 관찰/검증
const [email, setEmail] = useState("");
<input value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={!isValid} />
```
- **둘을 섞지 않는다**(같은 입력에 `value`와 `defaultValue`를 동시에 주면 경고/버그).
- 재사용 컴포넌트는 둘 다 지원할 수 있다: `value`가 오면 제어, 없으면 내부 `defaultValue`로 비제어(Radix·shadcn 패턴).

## 5. 추가 규율 (간단히)

- **props는 좁고 명시적으로**: `any` 금지, 유니온/리터럴로 변형을 타입에 가둔다.
- **스타일은 토큰만**: 컴포넌트에 raw hex·임의 px를 박지 않는다(`reference/design-tokens.md`).
- **상태 4종을 컴포넌트가 책임진다**: 리스트/뷰 컴포넌트는 empty·loading·error·ideal을 모두 렌더한다(`reference/accessibility.md`).
- **부수효과 분리**: fetch·구독은 훅으로, 표현 컴포넌트는 순수하게 유지(테스트·스토리북 용이).

## 출처
- shadcn/ui(합성·토큰·복사 가능 컴포넌트): https://ui.shadcn.com
- Radix UI Primitives(접근성·제어/비제어): https://www.radix-ui.com/primitives
- React 공식 — controlled vs uncontrolled: https://react.dev/learn/sharing-state-between-components
