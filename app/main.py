import asyncio
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictBool

from . import __version__
from .config import Settings
from .jobs import JobManager
from .media import MediaError, health_report

STATIC = Path(__file__).resolve().parent.parent / "static"
SESSION_COOKIE = "streamsave_session"


class LeasedFileResponse(FileResponse):
    def __init__(self, *args, release, **kwargs):
        super().__init__(*args, **kwargs)
        self.release = release

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Includes invalid ranges, disconnects and errors, all of which may
            # skip FileResponse's optional background callback.
            self.release()


class InspectRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class JobRequest(BaseModel):
    inspection_id: str = Field(min_length=32, max_length=32)
    option_id: str = Field(min_length=1, max_length=50)
    authorized: StrictBool


class BodyLimitMiddleware:
    """Read small JSON request bodies with a hard limit, including chunked requests."""
    def __init__(self, app, limit=4096):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.limit:
                return await JSONResponse({"detail": "Request is too large."}, status_code=413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        sent = False
        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        await self.app(scope, replay, send)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    manager = JobManager(settings)

    @asynccontextmanager
    async def lifespan(_app):
        manager.start()
        yield
        manager.close()

    app = FastAPI(title="StreamSave", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.manager = manager
    app.add_middleware(BodyLimitMiddleware)

    @app.middleware("http")
    async def browser_security(request: Request, call_next):
        owner = request.cookies.get(SESSION_COOKIE, "")
        new_session = not re.fullmatch(r"[a-f0-9]{64}", owner)
        if new_session:
            owner = secrets.token_hex(32)
        request.state.owner = owner
        origin = request.headers.get("origin")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin:
            expected = urlsplit(settings.public_url or str(request.base_url))
            submitted = urlsplit(origin)
            if (submitted.scheme, submitted.netloc) != (expected.scheme, expected.netloc):
                return JSONResponse({"detail": "Use this app from its own website."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https://i.ytimg.com; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if new_session:
            response.set_cookie(SESSION_COOKIE, owner, httponly=True, secure=settings.secure_cookies,
                                samesite="strict", max_age=86400, path="/")
        return response

    @app.exception_handler(MediaError)
    async def media_error(_request, exc):
        headers = {"Retry-After": "60"} if exc.status == 429 else None
        return JSONResponse({"detail": str(exc)}, status_code=exc.status, headers=headers)

    @app.get("/api/health")
    def health():
        result = health_report(settings)
        return JSONResponse(result, status_code=200 if result["status"] == "ok" else 503)

    @app.get("/api/config")
    def config():
        return {"max_duration_seconds": settings.max_duration, "max_file_mb": round(settings.max_file_bytes / (1024 * 1024)),
                "file_ttl_seconds": settings.file_ttl, "max_resolution": 1080, "engine": "cobalt"}

    @app.post("/api/inspect")
    async def inspect_video(request: Request, body: InspectRequest):
        manager.rate_limit(request.client.host if request.client else "unknown")
        return await asyncio.to_thread(manager.inspect, request.state.owner, body.url)

    @app.post("/api/jobs", status_code=202)
    def start_job(request: Request, body: JobRequest):
        manager.rate_limit(request.client.host if request.client else "unknown")
        return manager.submit(request.state.owner, body.inspection_id, body.option_id, body.authorized)

    @app.get("/api/jobs/{job_id}")
    def job_status(request: Request, job_id: str):
        return manager.status(request.state.owner, job_id)

    @app.delete("/api/jobs/{job_id}")
    def cancel_job(request: Request, job_id: str):
        return manager.cancel_job(request.state.owner, job_id)

    @app.get("/api/jobs/{job_id}/file")
    def job_file(request: Request, job_id: str):
        path, filename = manager.claim_file(request.state.owner, job_id)
        types = {"mp4": "video/mp4", "webm": "video/webm", "mp3": "audio/mpeg", "m4a": "audio/mp4"}
        return LeasedFileResponse(path, filename=filename, media_type=types.get(path.suffix[1:], "application/octet-stream"),
                                  headers={"Cache-Control": "no-store"}, release=lambda: manager.release_file(job_id))

    @app.api_route("/", methods=["GET", "HEAD"])
    def home():
        return FileResponse(STATIC / "index.html", media_type="text/html")

    @app.get("/source")
    def source_code():
        path = Path(os.getenv("SOURCE_ARCHIVE", str(settings.download_dir.parent / "streamsave-source.zip")))
        with manager.lock:
            if not path.is_file():
                from scripts.source_bundle import make_bundle
                make_bundle(STATIC.parent, path)
        return FileResponse(path, filename="StreamSave-source.zip", media_type="application/zip")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
