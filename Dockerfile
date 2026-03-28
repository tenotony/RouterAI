FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir httpx flask flask-cors gunicorn chromadb

COPY src/proxy.py ./src/proxy.py
COPY providers.json .
COPY src/ ./src/

RUN mkdir -p /app/data/cache
RUN echo '{}' > /app/api_keys.json
RUN echo '{}' > /app/proxy_config.json

ENV PYTHONIOENCODING=utf-8
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV ROUTERAI_PORT=8900

COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8900

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8900/health')" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "src/proxy.py"]
