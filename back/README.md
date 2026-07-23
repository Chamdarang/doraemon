# Doraemon 백엔드

사용자의 요구사항을 LLM으로 정리하고, 승인된 계획을 바탕으로 로컬 프로젝트를 생성하고
실행하는 FastAPI 백엔드입니다.

처음 실행할 때 백엔드 폴더에서 가상환경과 의존성을 준비합니다.

```powershell
cd back
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m uvicorn app.main:app --reload
```

API 문서는 `http://localhost:8000/docs` 에서 확인할 수 있습니다. 공급자, 모델, API 키는
루트 `.env` 또는 설정 UI에서 관리합니다.

## 코드 구조

```text
app/
  main.py              # FastAPI 생성과 시작·종료 수명 주기
  api/                 # 라우터와 의존성 주입
  schemas/             # Pydantic 요청·응답·영속 모델
  repositories/        # 파일 저장소와 상태 I/O
  services/            # 기획·생성·개선 등 유스케이스
  runtime/             # 프로세스·로그·실행 어댑터
  integrations/llm/    # LLM 공급자 통신
  core/                # 설정, 프로젝트 잠금, ApplicationContainer
```

라우터는 저장소를 직접 조합하지 않고 서비스를 호출합니다. 서비스는 HTTP 객체를 알지
않으며, 런타임과 외부 연동은 각각의 패키지 경계를 통해 사용합니다.

`core/container.py`는 애플리케이션의 조립 지점(composition root)입니다. 저장소와
서비스를 한 번 생성해 연결하고, FastAPI 의존성 함수는 `app.state.container`에서 필요한
서비스만 꺼냅니다. `main.py`의 `lifespan`은 컨테이너 생성과 종료만 담당합니다.

## 데이터 구조

```text
pocket/<service-id>/
  pocket.json          # 서비스 메타데이터와 실행 설정
  .env                 # 서비스별 환경변수
  .pocket/jobs/        # 생성 작업 기록
  .pocket/logs/        # 백엔드와 프런트엔드 실행 로그
  back/                # 생성 서비스의 서버 영역
  front/               # 생성 서비스의 클라이언트 영역
```

백엔드 검사와 테스트도 `back` 폴더에서 직접 실행할 수 있습니다.

```powershell
.venv\Scripts\python -m ruff check app tests
.venv\Scripts\python -m mypy app/schemas app/runtime/plugins app/repositories/errors.py app/runtime/command.py
.venv\Scripts\python -m pytest -q
```
