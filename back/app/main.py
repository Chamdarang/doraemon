from contextlib import asynccontextmanager
import re

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import router
from app.core.container import ApplicationContainer
from app.core.config import settings
from app.core.locks import ProjectBusyError


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = ApplicationContainer.build(settings)
    app.state.container = container
    try:
        yield
    finally:
        await container.shutdown()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def serialize_project_mutations(request, call_next):
    match = re.match(r"^/api/projects/([a-z0-9][a-z0-9-]{0,79})(?:/|$)", request.url.path)
    if request.method not in {"GET", "HEAD", "OPTIONS"} and match:
        reject_if_busy = request.method == "POST" and bool(
            re.fullmatch(
                r"/api/projects/[a-z0-9][a-z0-9-]{0,79}/(?:messages|improvements/messages)",
                request.url.path,
            )
        )
        try:
            async with request.app.state.container.project_locks.hold(
                match.group(1), wait=not reject_if_busy
            ):
                return await call_next(request)
        except ProjectBusyError:
            return JSONResponse(
                status_code=409,
                content={"detail": "이 서비스에서 다른 요청을 처리 중입니다. 완료 후 다시 시도해 주세요. 중복 LLM 과금을 막기 위해 요청을 대기열에 넣지 않았습니다."},
            )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.api_prefix)
