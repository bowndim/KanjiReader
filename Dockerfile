FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium
CMD ["sh","-c","python -m uvicorn main:app --host 0.0.0.0 --port $PORT"]
