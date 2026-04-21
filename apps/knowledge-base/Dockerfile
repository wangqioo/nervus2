FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev gcc && rm -rf /var/lib/apt/lists/*
COPY nervus-sdk /app/nervus-sdk
RUN pip install --no-cache-dir -e /app/nervus-sdk
COPY apps/knowledge-base/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/knowledge-base/ .
ENV PYTHONUNBUFFERED=1
EXPOSE 8004
CMD ["python", "main.py"]
