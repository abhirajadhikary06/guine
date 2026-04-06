import asyncio
import logging
from app.stt import transcribe_audio

logger = logging.getLogger(__name__)


class AudioQueue:
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()

    async def enqueue(self, audio_bytes: bytes, ext: str, future: asyncio.Future):
        await self.queue.put((audio_bytes, ext, future))

    async def worker(self):
        logger.info("Audio queue worker started.")
        while True:
            try:
                audio_bytes, ext, future = await self.queue.get()
                try:
                    result = await transcribe_audio(audio_bytes, ext)
                    if not future.done():
                        future.set_result(result)
                except Exception as e:
                    if not future.done():
                        future.set_exception(e)
                finally:
                    self.queue.task_done()
            except asyncio.CancelledError:
                logger.info("Audio queue worker stopped.")
                break
            except Exception as e:
                logger.error(f"Queue worker unexpected error: {e}")