FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev gcc && rm -rf /var/lib/apt/lists/*
COPY nervus-sdk /app/nervus-sdk
RUN pip install --no-cache-dir -e /app/nervus-sdk
COPY apps/meeting-notes/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/meeting-notes/ .
ENV PYTHONUNBUFFERED=1
EXPOSE 8002
CMD ["python", "main.py"]
