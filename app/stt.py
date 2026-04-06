import io
import logging
import tempfile
import os
import asyncio
import subprocess
import time

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
    temp_paths: list[str] = []

    def _transcribe() -> str | None:
        import speech_recognition as sr

        recognizer = sr.Recognizer()
        suffix = f".{ext}" if ext else ".wav"
        input_path = ""

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as src:
            src.write(audio_bytes)
            input_path = src.name
            temp_paths.append(input_path)

        audio_path = input_path
        if ext.lower() not in {"wav", "wave", "flac", "aiff", "aif", "aifc"}:
            wav_path = f"{input_path}.wav"
            # Normalize unsupported formats (mp3/m4a/ogg) to WAV for SpeechRecognition.
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", input_path, wav_path],
                check=True,
            )
            temp_paths.append(wav_path)
            audio_path = wav_path

        with sr.AudioFile(audio_path) as source:
            audio_data = recognizer.record(source)

        start_time = time.perf_counter()
        try:
            text = recognizer.recognize_google(audio_data)
            elapsed = time.perf_counter() - start_time
            logger.info("Google Speech succeeded in %.2fs", elapsed)
            return text
        except sr.UnknownValueError:
            logger.warning("Google Speech could not understand audio")
            return None
        except sr.RequestError as exc:
            logger.warning("Google Speech request failed: %s", exc)
            return None

    try:
        return await asyncio.to_thread(_transcribe)
    except Exception as e:
        logger.warning(f"Google Speech error: {e}")
        return None
    finally:
        for path in temp_paths:
            try:
                os.unlink(path)
            except OSError:
                pass


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