FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8080

WORKDIR /app

# Deps first (cached layer), then the package source on PYTHONPATH so paths
# computed from __file__ (trace dir, snapshot) resolve under /app.
COPY pyproject.toml CLAUDE.md ./
COPY driftwatch/ driftwatch/
RUN pip install --no-cache-dir ".[agents,api]"

COPY data/snapshot/ data/snapshot/
COPY traces/ traces/
COPY reports/ reports/

EXPOSE 8080
CMD ["python", "-m", "uvicorn", "driftwatch.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
