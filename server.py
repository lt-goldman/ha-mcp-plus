ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.19
FROM $BUILD_FROM

# Install dependencies
RUN apk add --no-cache gcc musl-dev libffi-dev

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ .

# HA addon entrypoint
CMD ["python", "-u", "server.py"]
