FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# App Runner expects the container to listen on the port you configure
# in the service settings — we use 8080 here and set that same value
# when creating the App Runner service.
EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "app:server"]
