FROM python:3.11-slim

WORKDIR /app

COPY requirements/ingest.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY ingest/ .

CMD ["python", "build_vectorstore.py"]
