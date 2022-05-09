FROM python:3.10.4-alpine3.15
COPY --chown=nobody:nogroup scaler /app
RUN pip install -U pip && \
    pip install -r /app/requirements.txt --no-cache-dir
USER nobody
WORKDIR /app
