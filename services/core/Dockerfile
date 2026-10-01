FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as an unprivileged user; writable state lives only in /app/data (a named volume).
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin pomona \
    && mkdir -p /app/data && chown pomona:pomona /app/data
ENV PYTHONDONTWRITEBYTECODE=1
USER 10001:10001

ENV CORE_HOST=0.0.0.0
ENV CORE_PORT=8080

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
