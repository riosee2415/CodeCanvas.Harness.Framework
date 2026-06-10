# 아키텍처

## 디렉토리 구조
```
src/
├── app/               # 페이지 + API 라우트
├── components/        # UI 컴포넌트
├── types/             # TypeScript 타입 정의
├── lib/               # 유틸리티 + 헬퍼
└── services/          # 외부 API 래퍼
```

## 패턴
{사용하는 디자인 패턴 (예: Server Components 기본, 인터랙션이 필요한 곳만 Client Component)}

## 데이터 흐름
```
{데이터가 어떻게 흐르는지 (예:
사용자 입력 → Client Component → API Route → 외부 API → 응답 → UI 업데이트
)}
```

## 상태 관리
{상태 관리 방식 (예: 서버 상태는 Server Components, 클라이언트 상태는 useState/useReducer)}

## 의존성 규칙
레이어 간 import 방향을 고정한다. 역방향 의존은 금지. (각 step이 독립 세션에서 실행되므로, 이 규칙이 없으면 세션마다 다른 구조가 나온다.)

```
app  →  components  →  lib
 │           │
 └───────────┴──────→  services  →  types
```

- CRITICAL: {예: `lib/`, `services/`는 `components/`나 `app/`를 import하지 않는다 (하위 레이어는 상위를 모른다)}
- CRITICAL: {예: 외부 API 호출은 `services/`에서만. 컴포넌트에서 직접 fetch 금지}

## 에러 처리 전략
- {예: 서비스 레이어는 예외를 던지지 않고 `Result<T, E>` 형태로 반환}
- {예: 사용자에게 보이는 에러는 한 곳(ErrorBoundary / 전역 핸들러)에서 처리}
- {예: 로그는 console이 아니라 {로깅 유틸}을 통한다}

## 테스트 전략
- {예: 비즈니스 로직(lib/, services/)은 단위 테스트 필수}
- {예: 컴포넌트는 핵심 인터랙션만 테스트, 스냅샷 테스트는 지양}
- {테스트 파일 위치 규칙 (예: 대상 파일 옆 `*.test.ts`)}

## 네이밍 컨벤션
- 파일/디렉토리: {예: kebab-case}
- 컴포넌트: {예: PascalCase}
- 함수/변수: {예: camelCase}
- 타입/인터페이스: {예: PascalCase, 접두사 없음}
- 상수: {예: UPPER_SNAKE_CASE}

## 보안 / 데이터 무결성
- {예: 사용자 입력은 신뢰하지 않는다 — 경계(API route)에서 검증}
- {예: 시크릿은 환경변수로만, 클라이언트 번들에 포함 금지}
- {예: 쓰기 작업은 멱등성을 보장한다}

## 상태 관리
{상태 관리 방식 (예: 서버 상태는 Server Components, 클라이언트 상태는 useState/useReducer)}
