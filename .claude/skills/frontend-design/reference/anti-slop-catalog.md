# 안티슬롭 카탈로그 — 명명된 슬롭 텔, 나쁜 예 → 교정

> 예시 스택: React+TS+Tailwind+shadcn·Radix. 원칙은 스택 불문 — 네 스택에 맞춰 적용.
> (Vue·Svelte·플레인 CSS·SwiftUI 어디든 동일: "AI가 기본값으로 뱉는 장식"을
>  걷어내고, 효과는 정보 설계에 봉사할 때만 남긴다. 클래스/속성 이름만 스택에 맞춘다.)

---

## 이 스킬이 잡아야 할 대표 상황

| 상황 | 무엇이 슬롭인가 |
|---|---|
| **첫 시안이 보라→시안 그라디언트로 도배됐다** | 훈련데이터 디폴트 팔레트. 브랜드가 없는 "AI가 만든 듯한" 1순위 텔. |
| **헤드라인·수치에 gradient-text가 들어갔다** | 가독성을 깎는 장식. 위계는 크기·굵기·여백으로 만든다. |
| **카드마다 글래스모피즘 blur + 떠다니는 orb** | 레이어 문제를 푸는 게 아니라 분위기만 내는 장식. |
| **불릿이 전부 이모지(✨🚀🔥)다** | 의미 없는 장식 아이콘. 시맨틱·접근성·일관성을 다 깬다. |
| **모든 전환이 통통 튀는 bouncy easing이다** | 의미 없는 모션. UI가 장난감처럼 느껴지고 reduced-motion도 무시한다. |
| **그림자가 깊고 사방에 깔렸다** | 가짜 깊이. 깊이는 위계가 있을 때만, 한두 단계로. |

**철칙: 효과(gradient·blur·shadow·motion)는 정보 설계에 봉사할 때만 남긴다. 장식이면 지운다.**

---

## 슬롭 텔 1 — 보라→시안 그라디언트 (1순위 텔)

훈련데이터에서 가장 흔한 팔레트. 버튼·텍스트·배경 가리지 않고 보라/바이올렛에서 시안으로 흐르면 즉시 "AI가 만든 듯"해진다.

**나쁜 예**
```tsx
<button className="bg-gradient-to-r from-violet-500 to-cyan-400 text-white">
  시작하기
</button>
```

**교정** — 단색 브랜드 컬러 + 토큰. 그라디언트가 정말 필요하면 같은 색의 명도 차로만.
```tsx
<button className="bg-primary text-primary-foreground hover:bg-primary/90">
  시작하기
</button>
```
> 색은 `reference/design-tokens.md`의 역할 토큰(`primary`)에서 가져온다. 하드코딩한 `violet-500`이 아니라.

---

## 슬롭 텔 2 — gradient-text (제목·수치)

제목·KPI 숫자에 `bg-clip-text`로 그라디언트를 입히는 것. 장식일 뿐 가독성·대비를 깎고, 다크/라이트 전환에서 깨진다.

**나쁜 예**
```tsx
<h1 className="bg-gradient-to-r from-purple-600 to-cyan-500 bg-clip-text text-transparent">
  매출 ₩12.4M
</h1>
```

**교정** — 단색 + 굵기/크기로 위계를 만든다. 강조는 한 단어에만 색을 준다.
```tsx
<h1 className="text-foreground text-4xl font-semibold tracking-tight">
  매출 <span className="text-primary">₩12.4M</span>
</h1>
```

---

## 슬롭 텔 3 — 장식용 글래스모피즘 / 떠다니는 orb

`backdrop-blur` + 반투명 카드 + 배경에 흐릿한 그라데이션 원. 레이어 문제(겹친 콘텐츠 위 가독성 확보)를 푸는 게 아니라 분위기만 내면 슬롭이다.

**나쁜 예**
```tsx
<div className="relative">
  <div className="absolute -z-10 size-72 rounded-full bg-violet-500/40 blur-3xl" />
  <div className="rounded-2xl border border-white/20 bg-white/10 backdrop-blur-xl p-6">
    …
  </div>
</div>
```

**교정** — 불투명 surface + 토큰 border. blur는 진짜로 겹치는 오버레이(모달 뒤 backdrop 등)에만.
```tsx
<div className="rounded-lg border border-border bg-card text-card-foreground p-6 shadow-sm">
  …
</div>
```

---

## 슬롭 텔 4 — 이모지 불릿 / 이모지 아이콘 대용

리스트 불릿이나 버튼 아이콘 자리에 이모지(✨🚀🔥💡)를 쓰는 것. 폰트마다 렌더가 다르고, 스크린리더가 엉뚱하게 읽고, 일관된 사이즈·색 제어가 안 된다.

**나쁜 예**
```tsx
<ul>
  <li>🚀 빠른 배포</li>
  <li>🔒 안전한 인증</li>
</ul>
```

**교정** — 아이콘 라이브러리(lucide 등)를 쓰고, 장식 아이콘은 `aria-hidden`.
```tsx
import { Rocket, Lock } from "lucide-react";
<ul className="space-y-2">
  <li className="flex items-center gap-2">
    <Rocket className="size-4 text-muted-foreground" aria-hidden /> 빠른 배포
  </li>
  <li className="flex items-center gap-2">
    <Lock className="size-4 text-muted-foreground" aria-hidden /> 안전한 인증
  </li>
</ul>
```
> 이모지가 정보를 담을 때(예: 상태 표시)는 텍스트 라벨을 함께 둔다 — 색·이모지만으로 의미를 전달하지 않는다(`reference/accessibility.md`).

---

## 슬롭 텔 5 — 통통 bouncy easing / 전부 애니메이션

모든 전환에 탄성(`cubic-bezier` 오버슈트)·bounce를 넣고, 안 움직여도 될 것까지 움직이는 것. UI가 장난감처럼 느껴지고 `prefers-reduced-motion`을 무시한다.

**나쁜 예**
```css
* { transition: all .4s cubic-bezier(.68,-0.55,.27,1.55); } /* 전역 bounce */
```

**교정** — 짧은 ease-out, transform/opacity만, 의미 있는 전환에만. reduced-motion 존중.
```css
.btn { transition: transform .15s ease-out, opacity .15s ease-out; }
@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
```

---

## 슬롭 텔 6 — 과한 그림자 / 가짜 깊이

깊은 그림자(`shadow-2xl`)를 모든 카드에 깔아 가짜 깊이를 만드는 것. 깊이는 위계가 있을 때만, 한두 단계로 충분하다.

**나쁜 예**
```tsx
<div className="shadow-2xl shadow-violet-500/50 rounded-3xl p-8"> … </div>
```

**교정** — 토큰화한 그림자 1~2단계(`shadow-sm`/`shadow-md`), 색 그림자 지양. 구조는 border·여백으로.
```tsx
<div className="rounded-lg border border-border bg-card p-6 shadow-sm"> … </div>
```
> 그림자 스케일은 `reference/design-tokens.md`의 `--shadow-*` 토큰을 쓴다.

---

## 보너스 텔 (같은 원리로 교정)

- **카드 한 모서리의 두꺼운 컬러 accent border** — 둥근 모서리와 충돌. 강조는 배경·타이포로.
- **카드 안의 카드**(중첩 컨테이너) — 가짜 깊이·노이즈. 여백·구분선(`divide-border`)으로 구조를 만든다.
- **균일한 과대 radius(24px+)로 다 같은 blob** — 위계가 사라진다. radius 토큰 스케일을 쓴다.
- **디폴트 폰트 남용**(Inter/Geist/Space Grotesk를 어디에나) — 개성 없음. display/body를 의도적으로 고른다.
- **히어로 클리셰**: eyebrow pill chip + 과대 문장형 헤드라인 + 대문자 kicker + 01/02/03 마커.

---

## 점검 루프 (시안을 받으면)

1. 위 6개 + 보너스 텔을 하나씩 대조한다 — **0개**여야 한다.
2. 발견하면 각 항목의 "교정"으로 바꾼다. 색·간격·radius·그림자는 토큰으로(`reference/design-tokens.md`).
3. 장식이라 판단되면 묻는다: **"이 효과가 없으면 정보 전달이 나빠지는가?"** 아니면 지운다.

## 출처
- impeccable / frontend-design (AI 슬롭 카탈로그): https://impeccable.style/slop/
- shadcn/ui: https://ui.shadcn.com · Radix UI: https://www.radix-ui.com
