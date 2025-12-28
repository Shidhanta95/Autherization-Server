FROM python:3.11-slim

WORKDIR /app

RUN pip install kafka-python psycopg2-binary requests

COPY sync-worker.py .

CMD ["python", "-u", "sync-worker.py"]