FROM python:3.11-slim

WORKDIR /app

COPY requirements/api.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
