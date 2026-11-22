FROM python:3.11-slim

WORKDIR /code

# Instalacja sqlite3 do bezpiecznych kopii zapasowych w tle
RUN apt-get update && apt-get install -y --no-install-recommends sqlite3 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app /code/app
COPY ./export_results.py /code/export_results.py

RUN mkdir -p /code/data /code/backups

EXPOSE 8000

# 1 worker jest idealny dla SQLite w trybie WAL (zero konfliktów zapisu, wysoka wydajność)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]