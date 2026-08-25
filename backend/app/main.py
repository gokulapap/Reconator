from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.routes import health, modules, recon, results, system, targets
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import configure_logging
from app.core.metrics import PrometheusMiddleware
from app.core.middleware import (
    RequestBodyLimitMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.sentry import init_sentry
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_sentry()
    with engine.begin() as conn:
        conn.execute(text("select 1"))
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Automated reconnaissance framework — REST API",
    lifespan=lifespan,
)

# Rate limiter must be installed before route registration handlers run.
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse({"detail": f"rate limit exceeded: {exc.detail}"}, status_code=429)


app.add_middleware(RequestIDMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestBodyLimitMiddleware, max_bytes=settings.max_request_body_bytes)
if settings.metrics_enabled:
    app.add_middleware(PrometheusMiddleware)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
allowed_hosts = [host.strip() for host in settings.allowed_hosts.split(",") if host.strip()]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or ["localhost"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials="*" not in origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(targets.router, prefix=settings.api_prefix)
app.include_router(results.router, prefix=settings.api_prefix)
app.include_router(modules.router, prefix=settings.api_prefix)
app.include_router(system.router, prefix=settings.api_prefix)
app.include_router(recon.router, prefix=settings.api_prefix)


_static_root = Path(settings.static_web_dir)
_index_file = _static_root / "index.html"
_serve_static = settings.serve_static_web and _index_file.exists()

if _serve_static:
    app.mount(
        "/assets",
        StaticFiles(directory=_static_root / "assets"),
        name="assets",
    )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(_index_file)

    @app.exception_handler(StarletteHTTPException)
    async def spa_fallback(request: Request, exc: StarletteHTTPException):
        if (
            exc.status_code == 404
            and request.method == "GET"
            and not request.url.path.startswith(("/api", "/docs", "/openapi", "/redoc"))
        ):
            return FileResponse(_index_file)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
else:

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "api": settings.api_prefix,
        }
