import io
import logging
import tempfile
import os

logger = logging.getLogger(__name__)


async def transcribe_audio(audio_bytes: bytes, ext: str) -> dict:
    """
    Attempt transcription via Google Speech Recognition.
    Fall back to faster-whisper on failure.
    """
    result = await _try_google(audio_bytes, ext)
    if result is not None:
        return {"text": result, "engine": "google"}

    logger.warning("Google Speech failed, falling back to faster-whisper.")
    result = await _try_whisper(audio_bytes, ext)
    if result is not None:
        return {"text": result, "engine": "whisper"}

    raise RuntimeError("Both Google Speech and faster-whisper failed to transcribe audio.")


async def _try_google(audio_bytes: bytes, ext: str) -> str | None:
    try:
        import speech_recognition as sr

        recognizer = sr.Recognizer()
        audio_io = io.BytesIO(audio_bytes)

        # SpeechRecognition needs AudioFile; wrap BytesIO
        with sr.AudioFile(audio_io) as source:
            audio_data = recognizer.record(source)

        text = recognizer.recognize_google(audio_data)
        return text
    except Exception as e:
        logger.warning(f"Google Speech error: {e}")
        return None


async def _try_whisper(audio_bytes: bytes, ext: str) -> str | None:
    try:
        from faster_whisper import WhisperModel

        # Use tiny model for speed; upgrade to base/small for accuracy
        model = WhisperModel("tiny", device="cpu", compute_type="int8")

        # faster-whisper requires a file path
        suffix = f".{ext}" if ext else ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            segments, _ = model.transcribe(tmp_path)
            text = " ".join(seg.text.strip() for seg in segments)
        finally:
            os.unlink(tmp_path)

        return text if text else None
    except Exception as e:
        logger.error(f"faster-whisper error: {e}")
        return None