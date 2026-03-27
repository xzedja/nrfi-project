FROM python:3.11-slim

WORKDIR /app

# Install system deps needed by psycopg2-binary and pybaseball
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    cron \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=America/Los_Angeles

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

RUN chmod +x /app/scripts/entrypoint.sh

CMD ["/bin/bash", "/app/scripts/entrypoint.sh"]
