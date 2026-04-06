# Guine — Speech to Text

A minimal, scalable speech-to-text web application.
Built to test FastAPI Cloud backend deployment + Cloudflare Pages frontend deployment.

---

## Architecture

```
Browser (Cloudflare Pages)
        │
        │  POST /stt  (multipart audio)
        ▼
Cloudflare (traffic shield, CDN, DDoS protection)
        │
        ▼
FastAPI backend (FastAPI Cloud / Docker)
   ├── Rate limiter (5 req/min/IP — pure Python)
   ├── asyncio.Queue (internal job queue)
   ├── STT Engine
   │     ├── Primary: Google Speech (SpeechRecognition)
   │     └── Fallback: faster-whisper (tiny model, CPU)
   └── Prometheus metrics (/metrics)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | HTML · CSS · vanilla JS |
| Design | Neu-brutalism |
| Backend | FastAPI (async) |
| STT Primary | SpeechRecognition (Google Speech API) |
| STT Fallback | faster-whisper (tiny, CPU) |
| Queue | asyncio.Queue |
| Rate limiting | Pure Python sliding window |
| Metrics | prometheus_client |
| Container | Docker (python:3.11-slim) |
| Tests | pytest + httpx |
| CDN / Shield | Cloudflare |

---

## How It Works

1. User selects an audio file (WAV / MP3 / M4A / OGG, max 10 MB).
2. Browser computes a SHA-256 hash of the file.
3. If a cached transcription exists in `localStorage` (TTL 30 min) → show it instantly.
4. Otherwise, the file is sent as multipart POST to `/stt`.
5. FastAPI validates type + size → checks rate limit → enqueues the job.
6. The queue worker picks it up → tries Google Speech → falls back to faster-whisper.
7. Result is returned, stored in `localStorage`, and displayed.

---

## Folder Structure

```
guine/
├── app/
│   ├── __init__.py
│   ├── main.py        # FastAPI app, routes, middleware
│   ├── stt.py         # Transcription engines
│   ├── queue.py       # asyncio.Queue worker
│   ├── rate_limit.py  # Sliding-window rate limiter
│   └── metrics.py     # Prometheus counters/histograms
├── frontend/
│   └── index.html     # Self-contained UI (no framework)
├── tests/
│   └── test_api.py    # Pytest test suite
├── Dockerfile
├── requirements.txt
├── pytest.ini
└── README.md
```

---

## Local Setup

**Requirements:** Python 3.11+, `ffmpeg` and `flac` installed system-wide.

```bash
# Clone / enter project
cd guine

# Create virtualenv
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run backend (single worker for dev)
uvicorn app.main:app --reload --port 8000

# Open frontend
open frontend/index.html
# or serve it: python -m http.server 3000 --directory frontend
```

> By default the frontend sends requests to the same origin (`/stt`).
> For local dev with a separate backend set `window.GUINE_API_URL` in browser console or add:
> ```html
> <script>window.GUINE_API_URL = "http://localhost:8000";</script>
> ```

---

## Docker Setup

```bash
# Build
docker build -t guine .

# Run (4 workers)
docker run -p 8000:8000 guine

# With env overrides
docker run -p 8000:8000 -e WORKERS=8 guine
```

---

## Deployment Guide

### Backend — FastAPI Cloud

1. Push the repo to GitHub.
2. On [FastAPI Cloud](https://fastapi.tiangolo.com/deployment/cloud/), connect the repo.
3. Set the start command:
   ```
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
   ```
4. Add system packages: `ffmpeg`, `flac`.
5. Set the port to `8000`.

### Frontend — Cloudflare Pages

1. In [Cloudflare Pages](https://pages.cloudflare.com/), create a new project.
2. Connect the repo → set **Build output directory** to `frontend`.
3. No build command needed (pure HTML).
4. Add an environment variable or edit `index.html`:
   ```javascript
   window.GUINE_API_URL = "https://your-backend.fastapi.cloud";
   ```
5. Deploy. Cloudflare serves the frontend globally.

### Cloudflare as Traffic Shield (optional but recommended)

- Point your backend domain through Cloudflare (proxied).
- Enable **Rate Limiting** rules in Cloudflare dashboard as a secondary shield.
- Enable **Browser Cache TTL** for static assets.
- Add a **WAF rule** to block non-POST requests to `/stt`.

---

## API Endpoints

### `POST /stt`

Upload an audio file for transcription.

**Request:** `multipart/form-data`

| Field | Type | Description |
|---|---|---|
| `file` | binary | Audio file (wav/mp3/m4a/ogg, ≤ 10 MB) |

**Response 200:**
```json
{
  "transcription": { "text": "hello world", "engine": "google" },
  "engine": "google"
}
```

**Error responses:**

| Code | Meaning |
|---|---|
| 413 | File exceeds 10 MB |
| 415 | Unsupported audio type |
| 429 | Rate limit exceeded (5 req/min) |
| 504 | Transcription timed out (60 s) |
| 500 | Both STT engines failed |

---

### `GET /health`

```json
{ "status": "ok", "queue_size": 0 }
```

---

### `GET /metrics`

Prometheus text format. Metrics exposed:

| Metric | Type | Description |
|---|---|---|
| `guine_total_requests_total` | Counter | All HTTP requests received |
| `guine_stt_requests_total` | Counter | STT requests accepted |
| `guine_failed_requests_total` | Counter | Requests that errored |
| `guine_processing_seconds` | Histogram | Transcription latency |
| `guine_queue_size` | Gauge | Current queue depth |

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# With coverage
pip install pytest-cov
pytest tests/ -v --cov=app --cov-report=term-missing
```

Tests cover:
- `GET /health` returns 200 + correct shape
- `GET /metrics` exposes Prometheus metrics
- `POST /stt` with valid WAV returns 200 or 500 (both engines silent)
- File > 10 MB returns 413
- Unsupported file type returns 415
- 6th request in 1 minute returns 429

---

## Future Improvements

- Add speaker diarization (pyannote.audio)
- Support URL-based audio input (no upload needed)
- GPU-accelerated faster-whisper (CUDA)
- WebSocket streaming transcription
- Auth via API keys (FastAPI dependency injection)
- Redis-backed rate limiter for multi-instance deployments
- OpenTelemetry tracing
- Larger whisper models selectable via query param
- Language detection and multi-language support