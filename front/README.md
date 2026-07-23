# Doraemon 프런트엔드

Doraemon의 로컬 프로젝트를 기획, 생성, 개선, 실행, 복구하는 UI입니다. React,
TypeScript, vinext/Vite로 구성되며 백엔드 주소는 `NEXT_PUBLIC_POCKET_API_URL`로
전달합니다.

## 구조

- `app/features/`: 기획, 개선, 오류 수정, 실행, 설정 화면.
- `app/hooks/`: 프로젝트 작업 공간과 비동기 액션 상태.
- `app/lib/`: API 통신과 공통 기반 코드.
- `app/studio.tsx`: 화면 조합과 주요 사용자 작업 흐름.
- `tests/`: SSR 계약, API 연동, 사용자 흐름 테스트.
- `worker/`, `build/`, `.openai/`: vinext 빌드 및 호스팅 진입점.

## 명령

프런트엔드 폴더에서 실행합니다.

```powershell
cd front
npm install
npm run dev
npm run test:unit
npm run test:integration
```

전체 프런트엔드 검증은 `npm run lint`, `npm run typecheck`, `npm test` 순서로 실행합니다.
