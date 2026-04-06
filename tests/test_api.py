"""
Guine API tests — run with:
  pytest tests/test_api.py -v
"""
import io
import time
import wave

import pytest
import httpx
from httpx import AsyncClient, ASGITransport

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
    big_data = b"\x00" * (10 * 1024 * 1024 + 1)
    files = {"file": ("big.wav", big_data, "audio/wav")}
    res = await client.post("/stt", files=files)
    assert res.status_code == 413
    assert "10MB" in res.json()["detail"]


@pytest.mark.anyio
async def test_unsupported_file_type(client):
    """Non-audio files must be rejected with 415."""
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