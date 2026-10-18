FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs
RUN pip install --no-cache-dir -e .
ENV PUBLIC_DEMO=true DATA_DIR=/data
RUN mkdir -p /data
# ponytail: one worker owns the refresh lock; use a shared job queue before scaling.
CMD ["sh", "-c", "uvicorn idxscreener.web.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]