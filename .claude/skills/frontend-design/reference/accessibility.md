# 접근성 — WCAG 2.2 AA · 4가지 상태 · ARIA do/don't

> 예시 스택: React+TS+Tailwind+shadcn·Radix. 원칙은 스택 불문 — 네 스택에 맞춰 적용.
> (어떤 프레임워크든 동일: 시맨틱 HTML을 먼저, 대비·포커스·키보드를 검증하고,
>  ARIA는 네이티브로 안 될 때만. Radix/shadcn은 이 동작을 프리미티브로 제공한다.)

---

## 이 스킬이 잡아야 할 대표 상황

| 상황 | 무엇이 문제인가 |
|---|---|
| **`muted-foreground` 텍스트가 흐려 안 읽힌다** | 대비 < 4.5:1. 토큰 명도를 올려 본문 ≥ 4.5:1을 맞춘다. |
| **Tab으로 버튼에 갔는데 어디 있는지 안 보인다** | 포커스 링이 없거나 대비 부족. 보이는 ring(≥2px, 대비 ≥3:1). |
| **`<div onClick>`으로 만든 버튼이 키보드로 안 눌린다** | 시맨틱이 아닌 것. `<button>`을 쓰면 키보드·포커스·역할이 공짜. |
| **모바일에서 아이콘 버튼이 너무 작아 눌리지 않는다** | target < 24px. 터치 타깃을 ≥24px(권장 44px)로. |
| **목록이 비었을 때 빈 화면만 나온다** | empty 상태 미처리. 4가지 상태(empty·loading·error·ideal)를 모두 설계한다. |
| **에러를 빨간 테두리로만 표시한다** | 색만으로 의미 전달. 텍스트 메시지 + `aria-describedby`로 연결한다. |

**철칙: 시맨틱 우선 → 대비·포커스·키보드 검증 → ARIA는 최후의 보강.**

---

## 1. 대비 (Contrast)

- **본문 텍스트 ≥ 4.5:1** (16px 이하 일반 텍스트).
- **큰 텍스트 ≥ 3:1** (≥24px 일반 또는 ≥18.66px bold), **UI 컴포넌트·아이콘·입력 테두리 ≥ 3:1**.
- 검증: 토큰 쌍(`foreground`/`background`, `muted-foreground`/`background`, `primary-foreground`/`primary`)을 대비 계산기로 잰다. 디자인 토큰을 바꾸면 다시 잰다(`reference/design-tokens.md`).
- 상태를 **색만으로** 전달하지 않는다 — 텍스트·아이콘·패턴을 함께 쓴다(색맹 사용자).

```
대비 측정 도구: WebAIM Contrast Checker, 브라우저 DevTools(Accessibility 패널),
axe DevTools / Lighthouse(자동 스캔).
```

## 2. 포커스 (Focus)

- 모든 인터랙티브 요소에 **보이는 포커스 링** — 두께 ≥ 2px, 대비 ≥ 3:1. `outline: none`만 두고 대체를 안 주면 위반.
- 키보드 사용자에게만 링을 보이려면 `:focus-visible`을 쓴다.
- 논리적 포커스 순서(DOM 순서 = 시각 순서). **포커스 트랩 금지**(모달은 닫으면 트리거로 포커스 복귀).

```tsx
// 토큰 ring 사용 (reference/design-tokens.md의 --ring)
<button className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
  저장
</button>
```

## 3. 키보드 완결 (Keyboard)

- 마우스로 되는 모든 동작은 **키보드만으로** 가능해야 한다(Tab/Shift+Tab 이동, Enter/Space 활성화, Esc 닫기, 화살표로 메뉴/탭 이동).
- 페이지 맨 앞에 **skip-to-content** 링크를 둔다.
- 커스텀 위젯(메뉴·탭·다이얼로그·콤보박스)을 직접 만들지 말고 **Radix 프리미티브**를 쓴다 — 키보드 상호작용·포커스 관리·ARIA가 내장(`reference/component-patterns.md`).

```tsx
<a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:p-2 focus:bg-background">
  본문으로 건너뛰기
</a>
```

## 4. 터치 타깃 (Target Size — WCAG 2.2)

- 인터랙티브 타깃 **≥ 24×24px** (AA, 2.5.8). 권장은 ≥ 44×44px.
- 작은 아이콘 버튼은 패딩·`min-h`/`min-w`로 타깃을 키운다(시각 아이콘은 작아도 hit area는 크게).

```tsx
<button className="inline-flex items-center justify-center min-h-[44px] min-w-[44px]">
  <X className="size-4" aria-hidden /> <span className="sr-only">닫기</span>
</button>
```

## 5. 시맨틱 HTML / 랜드마크

- 랜드마크: `<header><nav><main><aside><footer>`. `<main>`은 페이지당 하나.
- `<h1>` 하나, 헤딩 레벨을 건너뛰지 않는다(h2 다음 h4 ✗).
- 버튼은 `<button>`, 이동 링크는 `<a href>`. `<div onClick>`으로 재발명하지 않는다(키보드·역할이 공짜).
- 이미지: 정보 이미지는 `alt`, 장식 이미지는 `alt=""`(또는 `aria-hidden`).

## 6. 4가지 상태 (UI Stack — 모든 데이터 뷰)

모든 데이터 뷰는 아래 **4가지를 전부** 설계한다. 하나라도 빠지면 미완성.

| 상태 | 패턴 |
|---|---|
| **empty(빈)** | 왜 비었는지 + **다음 행동 하나**를 긍정적으로. "데이터 없음"만 ✗. CTA를 둔다. |
| **loading(로딩)** | 기대치를 설정한다 — 무한 스피너보다 **skeleton**(레이아웃 유지). `aria-busy`/live region로 안내. |
| **error(에러)** | 코드 말고 **평이한 말**로 문제를 짚고 **교정 행동**(재시도 등). 색만으로 표시하지 않는다. |
| **ideal(정상)** | 가장 공들이는 성공 상태. 나머지 셋도 이 수준으로 다듬는다. |

```tsx
function ItemList({ status, items, onRetry }: Props) {
  if (status === "loading") return <Skeleton aria-busy rows={5} />;          // loading
  if (status === "error")
    return (
      <div role="alert" className="text-foreground">
        목록을 불러오지 못했습니다.
        <button onClick={onRetry} className="text-primary underline">다시 시도</button>
      </div>
    );                                                                        // error
  if (items.length === 0)
    return (
      <div className="text-center text-muted-foreground">
        <p>아직 항목이 없어요.</p>
        <Button>첫 항목 추가</Button>
      </div>
    );                                                                        // empty
  return <ul>{items.map(/* … */)}</ul>;                                       // ideal
}
```

## 7. ARIA — do / don't

> **첫 번째 ARIA 규칙: ARIA를 안 쓰는 것이다.** 네이티브 요소로 되면 그것을 써라.

**do (이렇게)**
- 시맨틱 요소를 먼저 쓴다(`<button>`/`<nav>`/`<label>`). 역할·키보드·포커스가 내장.
- 폼 에러는 `aria-describedby`로 입력과 메시지를 연결하고, 라이브 영역(`role="alert"`)으로 알린다.
- 아이콘 전용 버튼엔 `<span className="sr-only">`로 접근명을 준다(또는 `aria-label`).
- 장식 아이콘·이미지는 `aria-hidden`/`alt=""`로 보조기술에서 숨긴다.
- 상태 변화(로딩·토스트)는 `aria-live`/`role="status"`로 알린다.

**don't (이러지 마)**
- `<div role="button">`로 네이티브를 재발명하지 않는다(키보드·포커스를 직접 다 구현해야 함).
- 시맨틱 요소에 **불필요한 role**을 덧붙이지 않는다(`<nav role="navigation">` 중복).
- 보이는 라벨이 있는데 `aria-label`로 덮어쓰지 않는다(스크린리더와 화면이 어긋남).
- `aria-hidden`을 포커스 가능한 요소에 걸지 않는다(포커스는 가는데 안 읽힘).

## 출처
- WCAG 2.2: https://www.w3.org/TR/WCAG22/ (대비 1.4.3·포커스 2.4.7·타깃 크기 2.5.8)
- The A11Y Project 체크리스트: https://www.a11yproject.com/checklist/
- ARIA Authoring Practices(APG): https://www.w3.org/WAI/ARIA/apg/
- Scott Hurff, "The UI Stack"(4가지 상태): https://www.scotthurff.com/posts/why-your-user-interface-is-awkward-youre-ignoring-the-ui-stack/
