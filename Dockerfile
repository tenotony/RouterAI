FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create data directories
RUN mkdir -p data/cache

EXPOSE 8900

# Run unified server
CMD ["gunicorn", "--bind", "0.0.0.0:8900", "--workers", "2", "--threads", "4", "--timeout", "120", "--access-logfile", "-", "src.server:app"]
