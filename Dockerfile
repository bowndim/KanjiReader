FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium
ENV PYTHONUNBUFFERED=1
CMD ["bash","-c","uvicorn main:app --host 0.0.0.0 --port $PORT"]
