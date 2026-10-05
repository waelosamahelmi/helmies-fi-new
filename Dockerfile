FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home helmies && mkdir /data && chown helmies:helmies /data
COPY --chown=helmies:helmies app ./app
COPY --chown=helmies:helmies scripts ./scripts
COPY --chown=helmies:helmies site ./site
USER helmies
EXPOSE 8088
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8088/healthz',timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088", "--workers", "1", "--no-proxy-headers", "--no-access-log"]
