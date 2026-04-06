from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

TOTAL_REQUESTS = Counter(
    "guine_total_requests_total",
    "Total number of HTTP requests received",
)

STT_REQUESTS = Counter(
    "guine_stt_requests_total",
    "Total number of STT transcription requests",
)

FAILED_REQUESTS = Counter(
    "guine_failed_requests_total",
    "Total number of failed requests",
)

PROCESSING_TIME = Histogram(
    "guine_processing_seconds",
    "Time spent processing audio transcription",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

QUEUE_SIZE = Gauge(
    "guine_queue_size",
    "Current number of items in the audio processing queue",
)


def generate_metrics() -> str:
    return generate_latest().decode("utf-8")