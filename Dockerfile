FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CW_DB=/data/worksites.db \
    CW_HOST=0.0.0.0 \
    CW_PORT=8787 \
    CW_MAX_HTTP_WORKERS=32 \
    CW_HTTP_SOCKET_TIMEOUT=10

WORKDIR /app
COPY worksites.py worksites_server.py server_runtime.py audit_guard.py /app/

RUN useradd --create-home --uid 10001 crisisweave \
    && mkdir -p /data \
    && chown -R crisisweave:crisisweave /data /app

USER crisisweave
VOLUME ["/data"]
EXPOSE 8787

HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=2)"

CMD ["sh", "-c", "python audit_guard.py install >/dev/null && exec python worksites_server.py"]
