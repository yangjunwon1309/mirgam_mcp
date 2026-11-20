FROM python:3.12-slim

WORKDIR /app
COPY server ./server
COPY config.json ./config.json
RUN pip install --no-cache-dir pyserial==3.5

ENV PYTHONUNBUFFERED=1
EXPOSE 8080 8081
CMD ["python", "-m", "server.beacon_server", "--config", "/app/config.json"]
