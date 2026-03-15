ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache gcc musl-dev libffi-dev

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all source files
COPY server.py .
COPY core/ core/
COPY plugins/ plugins/

CMD ["python", "-u", "server.py"]
