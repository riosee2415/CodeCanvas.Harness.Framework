# 디자인 토큰 — 기본 토큰 시스템 (자기완결)

> 예시 스택: React+TS+Tailwind+shadcn·Radix. 원칙은 스택 불문 — 네 스택에 맞춰 적용.
> (CSS 변수·SCSS map·Style Dictionary·디자인 툴 변수 어디든 동일: 색은 **역할**로,
>  간격·타입·radius·그림자는 **스케일**로 명명하고, 하드코딩 대신 토큰을 참조한다.)

---

## 이 스킬이 잡아야 할 대표 상황

| 상황 | 무엇이 문제인가 |
|---|---|
| **프로젝트에 `docs/UI_GUIDE.md`가 없다** | 토큰 기준이 없는 것. 이 파일의 기본 토큰을 그대로 깔면 자기완결로 시작된다. |
| **컴포넌트마다 `#6b7280`·`16px`가 흩어져 있다** | 하드코딩. 색은 역할 토큰, 간격은 스케일 토큰으로 바꾼다. |
| **다크모드를 켜니 색이 깨진다** | 색을 역할(`background`/`foreground`)이 아니라 raw hex로 쓴 것. 역할 토큰을 테마별로 재정의한다. |
| **간격·글자 크기가 제각각이다** | 스케일이 없는 것. spacing·type scale를 정해 그 안에서만 고른다. |

**이 파일은 `docs/UI_GUIDE.md`가 없어도 자기완결이다 — 아래 토큰을 그대로 붙여 시작하라.**
프로젝트에 `docs/UI_GUIDE.md`가 있으면 그쪽이 우선이고, 이 파일은 폴백 기본값이다.

---

## 0. 원칙

- **색은 역할로** 명명한다(`background`/`foreground`/`primary`/`muted`/`border`). raw hex를 컴포넌트에 직접 쓰지 않는다 → 테마·다크모드가 자동으로 따라온다.
- 모든 시각 속성(색·간격·타입·radius·그림자)은 **스케일 안에서만** 고른다. 임의값(`17px`)을 만들지 않는다.
- 토큰은 **CSS 변수(런타임 테마)** 로 정의하고 Tailwind config에 매핑한다 → 클래스(`bg-background`)로 소비.
- 색은 `hsl` 채널값으로 저장(`240 6% 10%`)해 `hsl(var(--x) / <alpha>)`로 투명도까지 한 토큰으로 제어.

---

## 1. 색 — 역할 토큰 (CSS 변수)

```css
/* globals.css */
:root {
  --background: 0 0% 100%;        /* 페이지 바탕 */
  --foreground: 240 10% 4%;       /* 기본 텍스트 (대비 ≥ 4.5:1) */

  --card: 0 0% 100%;              /* surface 바탕 */
  --card-foreground: 240 10% 4%;

  --primary: 240 60% 50%;         /* 브랜드/주요 액션 */
  --primary-foreground: 0 0% 100%;/* primary 위 텍스트 */

  --muted: 240 5% 96%;            /* 약한 바탕(보조 영역) */
  --muted-foreground: 240 4% 40%; /* 보조 텍스트 (대비 ≥ 4.5:1) */

  --border: 240 6% 90%;           /* 테두리·구분선 */
  --input: 240 6% 90%;            /* 입력 테두리 */
  --ring: 240 60% 50%;            /* 포커스 링 */

  --destructive: 0 72% 45%;       /* 위험/에러 액션 */
  --destructive-foreground: 0 0% 100%;
}

.dark {
  --background: 240 10% 4%;
  --foreground: 0 0% 98%;
  --card: 240 8% 8%;
  --card-foreground: 0 0% 98%;
  --primary: 240 60% 62%;
  --primary-foreground: 240 10% 4%;
  --muted: 240 5% 16%;
  --muted-foreground: 240 5% 65%;
  --border: 240 5% 20%;
  --input: 240 5% 20%;
  --ring: 240 60% 62%;
  --destructive: 0 62% 50%;
  --destructive-foreground: 0 0% 98%;
}
```

> **대비 검증**: `foreground`/`background`, `muted-foreground`/`background`, `primary-foreground`/`primary` 쌍은 본문 ≥ 4.5:1, 큰 텍스트·아이콘 ≥ 3:1을 만족해야 한다(`reference/accessibility.md`). 토큰을 바꾸면 다시 잰다.

## 2. 간격 — spacing scale

4px 기반. 이 스텝 안에서만 고른다.

| 토큰 | 값 | 용도 |
|---|---|---|
| `space-1` | 4px | 아이콘-텍스트 간격 |
| `space-2` | 8px | 인라인 그룹 |
| `space-3` | 12px | 컨테이너 안쪽 최소 패딩 |
| `space-4` | 16px | 카드 기본 패딩 |
| `space-6` | 24px | 그룹 사이 |
| `space-8` | 32px | 컴포넌트 블록 사이 |
| `space-12` | 48px | 섹션 사이 |
| `space-16` | 64px | 큰 섹션 사이 |

> Tailwind 기본 스페이싱(`p-4`=16px)이 이 스케일과 일치하므로 그대로 쓴다. 테두리/컬러 컨테이너 안쪽 패딩은 **≥ `space-3`(12px)**.

## 3. 타입 — type scale (1.25 비율)

```css
:root {
  --text-xs:  0.75rem;   /* 12px — 캡션 */
  --text-sm:  0.875rem;  /* 14px — 보조 */
  --text-base:1rem;      /* 16px — 본문(기본) */
  --text-lg:  1.25rem;   /* 20px — 강조 본문 */
  --text-xl:  1.5rem;    /* 24px — 소제목 */
  --text-2xl: 1.875rem;  /* 30px — 제목 */
  --text-3xl: 2.25rem;   /* 36px — 큰 제목 */
  --text-4xl: 3rem;      /* 48px — 디스플레이 */
}
```
- 본문 줄높이 1.5~1.6, 제목 1.1~1.25, `tracking-tight`는 큰 제목에만.
- 굵기는 2~3단(`400`/`500`/`600`). 본문 폭 65~75ch.

## 4. radius

```css
:root {
  --radius-sm: 0.25rem; /* 4px — 작은 칩·뱃지 */
  --radius:    0.5rem;  /* 8px — 기본(버튼·인풋·카드) */
  --radius-lg: 0.75rem; /* 12px — 큰 surface */
}
```
> 모든 요소에 균일한 과대 radius(24px+)를 쓰지 않는다(슬롭 텔). 위계에 따라 스케일을 고른다.

## 5. shadow

```css
:root {
  --shadow-sm: 0 1px 2px 0 hsl(240 10% 4% / 0.05);
  --shadow:    0 1px 3px 0 hsl(240 10% 4% / 0.10), 0 1px 2px -1px hsl(240 10% 4% / 0.10);
  --shadow-md: 0 4px 6px -1px hsl(240 10% 4% / 0.10), 0 2px 4px -2px hsl(240 10% 4% / 0.10);
}
```
> 그림자는 깊이 위계가 있을 때만 1~2단계. 색 그림자(`shadow-violet`)·`2xl` 남용 금지(슬롭 텔).

---

## 6. Tailwind config 매핑

CSS 변수를 Tailwind 토큰으로 노출해 `bg-background`·`text-muted-foreground`·`rounded-lg` 등으로 소비한다.

```ts
// tailwind.config.ts
import type { Config } from "tailwindcss";

export default {
  darkMode: ["class"],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
      },
      borderRadius: {
        lg: "var(--radius-lg)",
        DEFAULT: "var(--radius)",
        sm: "var(--radius-sm)",
      },
      boxShadow: {
        sm: "var(--shadow-sm)",
        DEFAULT: "var(--shadow)",
        md: "var(--shadow-md)",
      },
    },
  },
} satisfies Config;
```

이후 컴포넌트는 토큰만 쓴다 — `className="bg-card text-card-foreground border border-border rounded-lg p-4 shadow-sm"`. raw hex·임의 px가 보이면 토큰으로 되돌린다.

> 이 매핑은 shadcn/ui의 토큰 규약과 호환된다 — shadcn 컴포넌트를 깔면 같은 변수 이름을 그대로 쓴다.

## 출처
- shadcn/ui theming(역할 토큰·CSS 변수 규약): https://ui.shadcn.com/docs/theming
- Tailwind CSS theme/config: https://tailwindcss.com/docs/theme
- type scale 계산: https://typescale.com
