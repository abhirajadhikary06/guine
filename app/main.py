import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

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
from app.stt import transcribe_audio

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_TYPES = {"audio/wav", "audio/mpeg", "audio/mp4", "audio/ogg", "audio/x-wav",
                 "audio/wave", "audio/mp3", "audio/m4a", "audio/x-m4a"}

audio_queue = AudioQueue()
rate_limiter = RateLimiter(max_requests=5, window_seconds=60)


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

FRONTEND_INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
FRONTEND_STATIC = Path(__file__).resolve().parent.parent / "frontend" / "static"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
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
    return response


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "queue_size": audio_queue.queue.qsize(),
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

    client_ip = request.client.host
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
        return {"transcription": result, "engine": result.get("engine", "unknown")}
    return {"transcription": {"text": str(result), "engine": "unknown"}, "engine": "unknown"}