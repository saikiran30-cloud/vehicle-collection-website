FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /var/data/uploads && useradd --create-home appuser && chown -R appuser:appuser /app /var/data
USER appuser
ENV DATA_DIR=/var/data DATABASE_PATH=/var/data/collection.db
CMD ["sh", "-c", "gunicorn --workers 2 --bind 0.0.0.0:${PORT:-10000} app:app"]
