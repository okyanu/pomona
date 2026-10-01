FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as an unprivileged user; this service writes no files.
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin pomona
ENV PYTHONDONTWRITEBYTECODE=1
USER 10001:10001

ENV DASHBOARD_HOST=0.0.0.0
ENV DASHBOARD_PORT=3000
ENV CORE_URL=http://core:8080

EXPOSE 3000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
