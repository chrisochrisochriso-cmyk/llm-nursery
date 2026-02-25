FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# PyTorch CPU-only wheel (~260MB, avoids pulling the CUDA variant)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
# Install remaining deps (torch already present, pip will skip it)
RUN pip install --no-cache-dir -r requirements.txt

COPY shard.py .

EXPOSE 8080

CMD ["python", "shard.py"]
