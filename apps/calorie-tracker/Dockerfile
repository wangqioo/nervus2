FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev gcc && rm -rf /var/lib/apt/lists/*
# SDK is copied into the image by docker-compose build context (repo root)
COPY nervus-sdk /app/nervus-sdk
RUN pip install --no-cache-dir -e /app/nervus-sdk
COPY apps/calorie-tracker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/calorie-tracker/ .
ENV PYTHONUNBUFFERED=1
RUN mkdir -p /data
EXPOSE 8001
CMD ["python", "main.py"]
