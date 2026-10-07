"""Cloud-ready Python app. GET requests and prompt previews never call the LLM."""

import asyncio
import json
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from .config import ROOT, Settings
from .gateway import Gateway, GatewayError
from .prompts import PROMPT_VERSION, build_prompt
from .schemas import EmailInput

basic_auth = HTTPBasic(auto_error=False)


def create_app(settings: Settings | None = None, gateway: Gateway | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    model_gateway = gateway or Gateway(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.model_lock = asyncio.Lock()
        yield

    app = FastAPI(title="FINCODE Email Lab", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    async def require_access(credentials: HTTPBasicCredentials | None = Depends(basic_auth)):
        if len(config.access_password) < 12:
            raise HTTPException(503, "서버에 12자 이상의 LAB_ACCESS_PASSWORD를 설정해 주세요.")
        username_ok = secrets.compare_digest(
            (credentials.username if credentials else "").encode(), b"lab"
        )
        password_ok = secrets.compare_digest(
            (credentials.password if credentials else "").encode(), config.access_password.encode()
        )
        if not (username_ok and password_ok):
            raise HTTPException(401, "팀 계정으로 로그인해 주세요.", headers={"WWW-Authenticate": 'Basic realm="FINCODE Lab", charset="UTF-8"'})

    protected = [Depends(require_access)]

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": "본문은 1~20,000자, 제목과 발신자는 각각 300자 이내로 입력해 주세요."})

    @app.get("/healthz")
    async def health():
        # Liveness only: do not call BAZE from a cloud health check.
        return {"status": "ok"}

    @app.get("/", dependencies=protected)
    async def index():
        return FileResponse(ROOT / "app/static/index.html")

    @app.get("/api/config", dependencies=protected)
    async def public_config():
        blocked = config.blocked_reasons()
        return {
            "model": config.model or None,
            "requested_model": "Google Gemini 3.5 Flash Lite",
            "ready": not blocked,
            "blocked_reasons": blocked,
            "prompt_version": PROMPT_VERSION,
            "live_calls_enabled": config.live_calls_enabled,
        }

    @app.get("/api/samples", dependencies=protected)
    async def samples():
        return json.loads((ROOT / "data/sample_emails.json").read_text(encoding="utf-8"))

    @app.post("/api/prompt", dependencies=protected)
    async def preview(email: EmailInput):
        return {"prompt_version": PROMPT_VERSION, "prompt": build_prompt(email)}

    @app.post("/api/summarize", dependencies=protected)
    async def summarize(email: EmailInput, request: Request):
        # Prevent browser-origin cross-site requests against Basic-auth sessions.
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "같은 사이트에서 요청해 주세요.")
        if config.blocked_reasons():
            raise HTTPException(503, " ".join(config.blocked_reasons()))
        lock = request.app.state.model_lock
        if lock.locked():
            raise HTTPException(429, "다른 요약을 처리 중입니다. 완료 후 다시 시도해 주세요.")
        async with lock:
            try:
                return await model_gateway.summarize(email)
            except GatewayError as exc:
                raise HTTPException(exc.status_code, exc.message) from None

    app.mount("/static", StaticFiles(directory=ROOT / "app/static"), name="static")
    return app


app = create_app()
