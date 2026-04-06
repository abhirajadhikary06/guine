FROM python:3.11-slim

# System deps for speechrecognition (flac, ffmpeg for audio conversion)
RUN apt-get update && apt-get install -y --no-install-recommends \
    flac \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /guine

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY app/ ./app/

# Expose FastAPI port
EXPOSE 8000

# 4 async workers; adjust --workers to match CPU cores on deployment host
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]