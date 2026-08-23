FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    STATE_PATH=/data/simulator-state.json

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8000
CMD ["/bin/sh", "-c", "exec uvicorn simulator.api:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
