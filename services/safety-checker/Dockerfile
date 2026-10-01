FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as an unprivileged user; this service writes no files.
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin pomona
ENV PYTHONDONTWRITEBYTECODE=1
USER 10001:10001

ENV SAFETY_CHECKER_HOST=0.0.0.0
ENV SAFETY_CHECKER_PORT=8082

EXPOSE 8082

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8082"]
