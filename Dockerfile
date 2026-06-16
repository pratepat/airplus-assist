FROM python:3.12-slim

WORKDIR /app

COPY neo-app/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY neo-app/ ./

# Documents are baked in for the prototype ingest-on-startup flow.
# In production, replace with a read from Azure Blob Storage.
COPY docs/ /docs

ENV DOCUMENTS_PATH=/docs
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
