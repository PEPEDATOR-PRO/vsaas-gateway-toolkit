FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 COLLECTOR_DATA_DIR=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home collector && mkdir /data && chown collector:collector /data
COPY collector ./collector
USER collector
EXPOSE 8080
CMD ["uvicorn", "collector.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--timeout-graceful-shutdown", "60"]
