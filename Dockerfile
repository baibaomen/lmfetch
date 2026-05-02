# lmfetch container — slim Python 3.12 + uv
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install uv (fast, deterministic) — keeps image small vs. a full pip layer.
RUN pip install --no-cache-dir uv==0.5.11

# Copy only what affects the install layer first for cache friendliness.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN uv pip install --system --no-cache .

# Default cache dir; override via LMFETCH_CACHE_DIR (mount a volume here).
RUN mkdir -p /var/lib/lmfetch/cache
VOLUME ["/var/lib/lmfetch/cache"]

EXPOSE 8000

# Healthcheck hits /healthz which build_app already provides.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status==200 else 1)"

ENTRYPOINT ["lmfetch"]
CMD ["serve"]
