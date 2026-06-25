---
name: frontend-design
description: 웹/모바일 UI를 디자인·구현할 때 따른다. "AI가 만든 듯한" generic 디자인(AI slop)을 피하고, 의도적 타입스케일·여백·접근성(WCAG AA)·4가지 상태를 지킨다. Esther(UI/UX)가 UI step을 시작하기 전에 읽는다.
---

# 프론트엔드 디자인 (안티슬롭)

> "AI가 만든 듯한" 디폴트를 피하고, **의도적이고 브랜드 특화된** UI를 만든다.
> 좋은 레퍼런스/컴포넌트에서 시작해 내 것으로 만든다 — 제약이 디자인을 만든다.

---

## 블록1 — 언제 이 스킬을 쓰나

- 화면·컴포넌트를 새로 디자인하거나 구현할 때(웹·모바일 UI).
- 받은 시안이 "AI가 만든 듯"한지 슬롭을 점검할 때.
- 색·간격·타이포 토큰을 정의하거나 하드코딩을 정리할 때.
- 접근성(대비·포커스·키보드·상태)을 점검할 때.
- 재사용 컴포넌트의 책임·합성·상태 소유를 설계할 때.

---

## 블록2 — 핵심 원칙

### AI 슬롭 안티패턴 (쓰지 마라)

- **보라/바이올렛 → 시안 그라데이션** (AI 팔레트 1순위 tell), 버튼·텍스트·배경 가리지 않고.
- **제목·수치의 그라데이션 텍스트** (장식일 뿐, 가독성 저하).
- **카드 한 모서리의 두꺼운 컬러 accent border** (둥근 모서리와 충돌하는 대표 tell).
- **장식용 글래스모피즘 / 떠다니는 그라데이션 orb** (레이어 문제 해결이 아니라 장식).
- **카드 안의 카드**(중첩 컨테이너) — 노이즈·가짜 깊이.
- **아이콘 타일 위 제목**의 feature 카드가 동일 그리드로 반복 (만능 AI 템플릿).
- **모든 요소 균일한 과한 radius**(24px+)로 다 같은 blob, **납작한 타입 위계**.
- **디폴트 폰트 남용**(Inter/Geist/Space Grotesk를 어디에나, 개성 없음).
- **히어로 클리셰**: eyebrow pill chip + 과대 문장형 헤드라인 + 대문자 kicker + 01/02/03 마커.
- **바운스/탄성 이징 + 전부 애니메이션**(의미 없는 모션), **이모지를 아이콘 대용**.

### 긍정 원칙 (이렇게 하라)

- **의도적 타입스케일**: 크기는 적게, 대비는 크게(≥1.25 비율). 개성 있는 display 폰트 + 정제된 body 폰트.
- **진짜 여백 시스템**: 그룹은 촘촘히, 섹션은 넉넉히. 테두리·컬러 컨테이너 안쪽 패딩 ≥12~16px.
- **중첩 대신** 여백·타입·구분선으로 구조를 만든다.
- **개성 있고 절제된 팔레트**(훈련데이터 디폴트에서 벗어나기). 효과(blur·shadow)는 **정보 설계에 봉사할 때만**.
- **부드러운 ease-out** 모션, transform/opacity만 애니메이트. 본문 폭 65~75ch.
- **브랜드 특화 카피**: 실제로 무엇을 하는지 구체적 동사+명사로.

### 접근성 (WCAG 2.2 AA — 검증 가능)

- 대비 ≥ **4.5:1**(본문) / **3:1**(큰 글자·아이콘·입력 테두리).
- 모든 인터랙티브 요소에 **보이는 포커스 링**(≥2px, 대비 ≥3:1), **완전한 키보드 조작** + skip-to-content, 포커스 트랩 금지.
- **시맨틱 HTML/랜드마크**(`<nav><main><button><a href>`), `<h1>` 하나, 헤딩 레벨 건너뛰기 금지.
- **ARIA는 필요할 때만**(네이티브 요소 재발명 금지), 필드 에러는 `aria-describedby`로 연결, target ≥ 24px.
- **`prefers-reduced-motion` 존중**, 정보 이미지 alt, 상태를 **색만으로** 전달하지 않기.

### 4가지 상태 (모든 데이터 뷰 — UI Stack)

- **로딩**: 기대치 설정(스피너보다 skeleton). **빈 상태**: 이유 + 다음 행동 하나, 긍정적으로.
- **에러**: 코드 말고 평이한 말로 문제를 짚고 교정 행동 제시. **정상**: 가장 공들이는 성공 상태 — 나머지 셋도 이 수준으로 다듬는다.

---

## 블록3 — 출처

- impeccable / frontend-design (AI 슬롭 카탈로그): https://impeccable.style/slop/
- The A11Y Project 체크리스트: https://www.a11yproject.com/checklist/ · WCAG 2.2: https://www.w3.org/TR/WCAG22/
- Scott Hurff, "The UI Stack" (4가지 상태): https://www.scotthurff.com/posts/why-your-user-interface-is-awkward-youre-ignoring-the-ui-stack/
- 안티도트 컴포넌트: shadcn/ui (https://ui.shadcn.com) · Radix UI (https://www.radix-ui.com)

---

## 블록4 — 심화 참조

> **토큰 우선순위**: 프로젝트에 `docs/UI_GUIDE.md`가 **있으면 우선**, 없으면 `reference/design-tokens.md`가 기본이다(자기완결).

| 막히는 상황 | 참조 파일 |
|---|---|
| **슬롭 의심 시** — 명명된 슬롭 텔 각각의 나쁜 예 → 교정(그라디언트·gradient-text·글래스모피즘·이모지 불릿·통통 easing·과한 그림자) | [`reference/anti-slop-catalog.md`](reference/anti-slop-catalog.md) |
| **토큰 정의 시** — 기본 디자인 토큰 시스템(색 역할·spacing·type scale·radius·shadow), CSS 변수 + Tailwind config 매핑 | [`reference/design-tokens.md`](reference/design-tokens.md) |
| **접근성 점검 시** — WCAG 2.2 AA(대비·포커스·키보드·target ≥24px), 4가지 상태(empty·loading·error·ideal), ARIA do/don't | [`reference/accessibility.md`](reference/accessibility.md) |
| **컴포넌트 설계 시** — 단일책임, 구성>설정(props 폭발 회피), shadcn/Radix 프리미티브, 제어/비제어 | [`reference/component-patterns.md`](reference/component-patterns.md) |

---

## 블록5 — 완료 전 체크리스트

- [ ] 안티슬롭 텔(그라디언트 남용·글래스모피즘·이모지 불릿·통통 easing 등)이 0개다
- [ ] 텍스트 대비 ≥ 4.5:1, focus ring이 보이고 키보드로 완결된다
- [ ] empty·loading·error·ideal 4가지 상태를 모두 처리했다
- [ ] 색·간격·타이포를 디자인 토큰으로 썼다 (하드코딩 없음)
- [ ] target 크기 ≥ 24px, 시맨틱 태그/ARIA가 적절하다

하나라도 ✗면 완료 아님.
