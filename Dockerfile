FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

ARG APP_BUILD_REVISION=unknown
ENV APP_BUILD_REVISION=${APP_BUILD_REVISION}

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup --system homemeterhub && adduser --system --ingroup homemeterhub homemeterhub
COPY --chown=homemeterhub:homemeterhub src ./src

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('APP_STATUS_PORT', '8080') + '/healthz', timeout=4).close()" || exit 1

USER homemeterhub

CMD ["python", "-m", "homemeterhub.app"]
