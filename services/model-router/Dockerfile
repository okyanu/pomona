FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV MODEL_ROUTER_HOST=0.0.0.0
ENV MODEL_ROUTER_PORT=8081
ENV MODELS_DIR=/app/models

EXPOSE 8081

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081"]
