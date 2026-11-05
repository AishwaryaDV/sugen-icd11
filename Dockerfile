FROM python:3.11-slim

WORKDIR /app

# Dependencies first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code + shipped data (mms code set + WHO enrichment + any prebuilt index).
COPY . .

# docker compose run coder /in/notes.jsonl /out/predictions.jsonl
ENTRYPOINT ["python", "-m", "coder.main"]
