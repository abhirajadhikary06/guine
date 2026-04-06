"""
Guine API tests — run with:
  pytest tests/test_api.py -v
"""
import io
import os
import tempfile
import wave
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

# Keep auth state isolated per test run.
TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="guine-tests-"))
os.environ.setdefault("GUINE_DB_PATH", str(TEST_DB_DIR / "guine.sqlite3"))
os.environ.setdefault("GUINE_SESSION_SECRET", "test-secret")
os.environ.setdefault("GUINE_SESSION_SAME_SITE", "lax")
os.environ.setdefault("GUINE_SESSION_HTTPS_ONLY", "false")

from app.main import app


# ── HELPERS ────────────────────────────────────────────────────────────────

def make_wav(duration_ms: int = 500) -> bytes:
    """Generate a minimal valid WAV file in memory."""
    sample_rate = 16000
    n_samples = int(sample_rate * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_samples)
    return buf.getvalue()


# ── FIXTURES ───────────────────────────────────────────────────────────────

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def sign_up(client: AsyncClient, email: str = "tester@example.com", password: str = "password123"):
    res = await client.post(
        "/auth/signup",
        json={"name": "Test User", "email": email, "password": password},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["user"]["email"] == email
    assert data["user"]["avatar"].startswith("/static/")
    return data["user"]


# ── TESTS ──────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_health(client):
    res = await client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "queue_size" in data


@pytest.mark.anyio
async def test_root_serves_frontend(client):
    res = await client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")


@pytest.mark.anyio
async def test_signup_login_and_me(client):
    user = await sign_up(client, email="signup@example.com")

    me = await client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == user["email"]

    logout = await client.post("/auth/logout")
    assert logout.status_code == 200

    missing = await client.get("/auth/me")
    assert missing.status_code == 401

    login = await client.post(
        "/auth/login",
        json={"email": "signup@example.com", "password": "password123"},
    )
    assert login.status_code == 200


@pytest.mark.anyio
async def test_daily_quota_visible(client):
    await sign_up(client, email="quota@example.com")

    quota = await client.get("/auth/quota")
    assert quota.status_code == 200
    payload = quota.json()
    assert "daily_limit" in payload
    assert payload["daily_limit"]["max"] == 5
    assert "remaining" in payload["daily_limit"]

    wav_bytes = make_wav(100)
    files = {"file": ("test.wav", wav_bytes, "audio/wav")}
    res = await client.post("/stt", files=files)
    assert res.status_code in (200, 500)
    if res.status_code == 200:
        body = res.json()
        assert "daily_limit" in body
        assert "remaining" in body["daily_limit"]


@pytest.mark.anyio
async def test_metrics_endpoint(client):
    res = await client.get("/metrics")
    assert res.status_code == 200
    assert "guine_total_requests_total" in res.text


@pytest.mark.anyio
async def test_stt_endpoint_valid_wav(client):
    """
    Send a silent WAV — Google will likely fail; whisper should return empty.
    We only check that the response shape is correct, not content.
    """
    await sign_up(client, email="stt@example.com")
    wav_bytes = make_wav()
    files = {"file": ("test.wav", wav_bytes, "audio/wav")}
    res = await client.post("/stt", files=files)
    # Accept 200 (transcribed) or 500 (both engines failed on silence)
    assert res.status_code in (200, 500)
    if res.status_code == 200:
        data = res.json()
        assert "transcription" in data
        assert "engine" in data


@pytest.mark.anyio
async def test_file_size_limit(client):
    """Files over 10 MB must be rejected with 413."""
    await sign_up(client, email="size@example.com")
    big_data = b"\x00" * (10 * 1024 * 1024 + 1)
    files = {"file": ("big.wav", big_data, "audio/wav")}
    res = await client.post("/stt", files=files)
    assert res.status_code == 413
    assert "10MB" in res.json()["detail"]


@pytest.mark.anyio
async def test_unsupported_file_type(client):
    """Non-audio files must be rejected with 415."""
    await sign_up(client, email="type@example.com")
    files = {"file": ("doc.txt", b"hello world", "text/plain")}
    res = await client.post("/stt", files=files)
    assert res.status_code == 415


@pytest.mark.anyio
async def test_rate_limit(client):
    """
    The 6th request within a minute from the same IP must return 429.
    We override client_ip to avoid collisions with other tests.
    """
    wav_bytes = make_wav(100)

    await sign_up(client, email="rate@example.com")

    # Reset rate limiter state by importing and clearing
    from app.main import rate_limiter
    rate_limiter._store.clear()

    responses = []
    for _ in range(6):
        files = {"file": ("test.wav", wav_bytes, "audio/wav")}
        r = await client.post("/stt", files=files)
        responses.append(r.status_code)

    # At least one of the responses must be 429
    assert 429 in responses, f"Expected a 429, got: {responses}"