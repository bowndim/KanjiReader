FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

# --- native deps for fugashi (MeCab) + Playwright ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        mecab libmecab-dev mecab-ipadic-utf8 build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
COPY reader ./reader
COPY requirements.txt . 

RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium

CMD ["sh","-c","python -m uvicorn main:app --host 0.0.0.0 --port $PORT"]

