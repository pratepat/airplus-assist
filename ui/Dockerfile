FROM python:3.11-slim

WORKDIR /app

COPY requirements/ui.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY ui/ .

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
