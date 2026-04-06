# Guine — Speech to Text

A minimal, scalable speech-to-text web application.
Built to test FastAPI Cloud backend deployment + Cloudflare Pages frontend deployment.

---

## Architecture

```
Browser (Cloudflare Pages)
        │
   │  POST /auth/signup, /auth/login, /stt
        ▼
Cloudflare (traffic shield, CDN, DDoS protection)
        │
        ▼
FastAPI backend (FastAPI Cloud / Docker)
   ├── Session auth (signed cookies)
   ├── User store (SQLite schema compatible with Cloudflare D1)
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
| Auth | Login/signup with cookie sessions |
| User storage | SQLite / Cloudflare D1-compatible schema |
| Avatars | Randomly assigned from static assets or R2 public URLs |
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

1. User signs up or logs in on the landing gate.
2. FastAPI stores the account in a SQLite schema that matches Cloudflare D1 tables.
3. A random avatar is assigned from `frontend/static/image*.png` and returned to the client.
4. User selects an audio file (WAV / MP3 / M4A / OGG, max 10 MB).
5. Browser computes a SHA-256 hash of the file.
6. If a cached transcription exists in `localStorage` (TTL 30 min) → show it instantly.
7. Otherwise, the file is sent as multipart POST to `/stt` with the session cookie.
8. FastAPI validates auth + type + size → checks rate limit → enqueues the job.
9. The queue worker picks it up → tries Google Speech → falls back to faster-whisper.
10. Result is returned, stored in `localStorage`, and displayed.

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

Authentication uses cookie sessions. If the frontend and backend are on different origins, set these backend env vars for your deployment:

- `GUINE_SESSION_SECRET`
- `GUINE_SESSION_SAME_SITE=none`
- `GUINE_SESSION_HTTPS_ONLY=true`
- `GUINE_AVATAR_BASE_URL=https://<your-r2-public-base>/avatars` if you move avatar files to R2

For Cloudflare D1 access, create a **custom API token** with:
- Account scope for your account only
- D1 permission set to **Edit** for signup/login writes
- D1 permission set to **Read** is not enough for signup because inserts need write access

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
6. Add environment variables for cross-origin auth from Pages:
   ```
   GUINE_SESSION_SECRET=<long-random-secret>
   GUINE_SESSION_SAME_SITE=none
   GUINE_SESSION_HTTPS_ONLY=true
   GUINE_ALLOWED_ORIGINS=https://<your-pages-domain>
   ```

If you use a custom Pages domain that is not `*.pages.dev`, include it in `GUINE_ALLOWED_ORIGINS`.

### Frontend — Cloudflare Pages

1. In [Cloudflare Pages](https://pages.cloudflare.com/), create a new project.
2. Connect the repo → set **Build output directory** to `frontend`.
3. No build command needed (pure HTML).
4. Add an environment variable or edit `index.html`:
   ```javascript
   window.GUINE_API_URL = "https://your-backend.fastapi.cloud";
   ```
5. Deploy. Cloudflare serves the frontend globally.

Cloudflare can cache the static UI and avatar assets because the backend now emits long-lived cache headers for `/static/*`. The HTML shell remains no-cache so deployments stay fresh.

### User Storage — Cloudflare D1

The app uses a single `users` table schema that is SQLite-compatible, so the same SQL can be imported into D1. The backend implementation in this repo uses a local SQLite file for development; in production, point the same schema at D1 through your deployment strategy.

The canonical table definition lives in [schema.sql](schema.sql).

Suggested columns:

```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
name TEXT NOT NULL,
email TEXT NOT NULL UNIQUE,
password_hash TEXT NOT NULL,
avatar_file TEXT NOT NULL,
created_at TEXT NOT NULL
```

### Avatar Assets — Cloudflare R2

The frontend expects avatar files named `image.png`, `image1.png`, `image2.png`, `image3.png`, and `image4.png`.
Locally they are served from `/static`; in production you can publish the same filenames from an R2 public bucket and set `GUINE_AVATAR_BASE_URL` to that public base URL.

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

Requires an authenticated session cookie.

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

### `POST /auth/signup`

Create a new account and start a session.

**Request:**
```json
{ "name": "Ada", "email": "ada@example.com", "password": "secret123" }
```

### `POST /auth/login`

Log in with an existing account.

### `GET /auth/me`

Returns the current user profile or `401` if no session is present.

### `POST /auth/logout`

Clears the session cookie.

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
- Authenticated login/signup flow backed by cookie sessions
- Redis-backed rate limiter for multi-instance deployments
- OpenTelemetry tracing
- Larger whisper models selectable via query param
- Language detection and multi-language support