FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

# Run as an unprivileged user; writable state lives only in /data (a named volume).
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin pomona \
    && mkdir -p /data && chown pomona:pomona /data
ENV PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
EXPOSE 8085
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8085"]
