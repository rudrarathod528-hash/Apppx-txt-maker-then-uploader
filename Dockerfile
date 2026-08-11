# APPX Course Bot — Docker image
#   docker build -t appx-course-bot .
#   docker run --env-file .env -v appx-data:/app/data appx-course-bot
FROM python:3.11-slim

# ffmpeg — HLS/DASH media processing ke liye (authorized DRM-free streams)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# temp dirs + data dir
RUN mkdir -p /tmp/appx/exports /tmp/appx/jobs /app/data

ENV PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/app/data/appx.db \
    EXPORT_DIR=/tmp/appx/exports \
    JOB_DIR=/tmp/appx/jobs

CMD ["python", "main.py"]
