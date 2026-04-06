import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.metrics import (
    TOTAL_REQUESTS,
    STT_REQUESTS,
    FAILED_REQUESTS,
    PROCESSING_TIME,
    QUEUE_SIZE,
    generate_metrics,
)
from app.queue import AudioQueue
from app.rate_limit import RateLimiter
from app.storage import UserStore

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_TYPES = {"audio/wav", "audio/mpeg", "audio/mp4", "audio/ogg", "audio/x-wav",
                 "audio/wave", "audio/mp3", "audio/m4a", "audio/x-m4a"}

audio_queue = AudioQueue()
rate_limiter = RateLimiter(max_requests=5, window_seconds=60)
daily_user_limiter = RateLimiter(max_requests=5, window_seconds=24 * 60 * 60)
user_store = UserStore()
SESSION_COOKIE = os.environ.get("GUINE_SESSION_COOKIE", "guine_session")
SESSION_SECRET_KEY = os.environ.get("GUINE_SESSION_SECRET", "change-me-in-production")
SESSION_SAME_SITE = os.environ.get("GUINE_SESSION_SAME_SITE", "lax")
SESSION_HTTPS_ONLY = os.environ.get("GUINE_SESSION_HTTPS_ONLY", "false").lower() == "true"


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_task = asyncio.create_task(audio_queue.worker())
    yield
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Guine",
    description="Minimal speech-to-text API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    session_cookie=SESSION_COOKIE,
    same_site=SESSION_SAME_SITE,
    https_only=SESSION_HTTPS_ONLY,
)

FRONTEND_INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
FRONTEND_STATIC = Path(__file__).resolve().parent.parent / "frontend" / "static"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://guine.fastapicloud.dev",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_origin_regex=r"^https://([a-z0-9-]+\.)?pages\.dev$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

if FRONTEND_STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_STATIC)), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        response.headers["CDN-Cache-Control"] = "public, max-age=31536000, immutable"
    elif request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    elif request.url.path.startswith("/auth/") or request.url.path in {"/health", "/metrics"}:
        response.headers["Cache-Control"] = "no-store"
    return response


def _current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return user_store.get_user_by_id(int(user_id))


def _require_user(request: Request):
    user = _current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def _auth_payload(user):
    user_key = f"user:{user.id}"
    return {
        "user": user.to_public_dict(),
        "daily_limit": {
            "max": daily_user_limiter.max_requests,
            "remaining": daily_user_limiter.remaining(user_key),
            "retry_after_seconds": daily_user_limiter.retry_after_seconds(user_key),
        },
    }


@app.get("/auth/me")
async def auth_me(request: Request):
    user = _current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return {"authenticated": True, "user": user.to_public_dict()}


@app.post("/auth/signup")
async def auth_signup(request: Request, payload: dict = Body(...)):
    try:
        user = user_store.create_user(
            name=str(payload.get("name", "")),
            email=str(payload.get("email", "")),
            password=str(payload.get("password", "")),
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 409 if "already exists" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message)

    request.session["user_id"] = user.id
    return _auth_payload(user)


@app.post("/auth/login")
async def auth_login(request: Request, payload: dict = Body(...)):
    email = str(payload.get("email", ""))
    password = str(payload.get("password", ""))
    user = user_store.authenticate(email=email, password=password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    request.session["user_id"] = user.id
    return _auth_payload(user)


@app.post("/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/auth/quota")
async def auth_quota(request: Request):
    user = _require_user(request)
    user_key = f"user:{user.id}"
    return {
        "daily_limit": {
            "max": daily_user_limiter.max_requests,
            "remaining": daily_user_limiter.remaining(user_key),
            "retry_after_seconds": daily_user_limiter.retry_after_seconds(user_key),
        }
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "queue_size": audio_queue.queue.qsize(),
        "storage_backend": "d1" if getattr(user_store, "_use_d1", False) else "sqlite",
    }


@app.get("/")
async def root():
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)
    return {
        "status": "ok",
        "message": "Guine API is running.",
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_metrics()


@app.post("/stt")
async def speech_to_text(request: Request, file: UploadFile = File(...)):
    TOTAL_REQUESTS.inc()

    try:
        user = _require_user(request)
    except HTTPException:
        FAILED_REQUESTS.inc()
        raise

    user_key = f"user:{user.id}"
    if not daily_user_limiter.allow(user_key):
        FAILED_REQUESTS.inc()
        raise HTTPException(
            status_code=429,
            detail="Daily generation limit exceeded. Max 5 requests per 24 hours.",
        )

    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(client_ip):
        FAILED_REQUESTS.inc()
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Max 5 requests per minute.",
        )

    content_type = file.content_type or ""
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if content_type not in ALLOWED_TYPES and ext not in {"wav", "mp3", "m4a", "ogg"}:
        FAILED_REQUESTS.inc()
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {content_type}. Allowed: wav, mp3, m4a, ogg.",
        )

    audio_bytes = await file.read()

    if len(audio_bytes) > MAX_FILE_SIZE:
        FAILED_REQUESTS.inc()
        raise HTTPException(
            status_code=413,
            detail="File too large. Maximum size is 10MB.",
        )

    STT_REQUESTS.inc()
    QUEUE_SIZE.set(audio_queue.queue.qsize() + 1)

    start = time.perf_counter()

    future: asyncio.Future = asyncio.get_event_loop().create_future()
    await audio_queue.enqueue(audio_bytes, ext or "wav", future)

    try:
        result = await asyncio.wait_for(future, timeout=60)
    except asyncio.TimeoutError:
        FAILED_REQUESTS.inc()
        raise HTTPException(status_code=504, detail="Transcription timed out.")
    except Exception as e:
        FAILED_REQUESTS.inc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        elapsed = time.perf_counter() - start
        PROCESSING_TIME.observe(elapsed)
        QUEUE_SIZE.set(audio_queue.queue.qsize())

    if isinstance(result, dict):
        return {
            "transcription": result,
            "engine": result.get("engine", "unknown"),
            "daily_limit": {
                "max": daily_user_limiter.max_requests,
                "remaining": daily_user_limiter.remaining(user_key),
                "retry_after_seconds": daily_user_limiter.retry_after_seconds(user_key),
            },
        }
    return {
        "transcription": {"text": str(result), "engine": "unknown"},
        "engine": "unknown",
        "daily_limit": {
            "max": daily_user_limiter.max_requests,
            "remaining": daily_user_limiter.remaining(user_key),
            "retry_after_seconds": daily_user_limiter.retry_after_seconds(user_key),
        },
    }