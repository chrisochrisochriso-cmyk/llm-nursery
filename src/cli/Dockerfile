FROM python:3.11-slim

# paperknight AI - CLI image
# Used when running pk inside the cluster (e.g. for scripted jobs)
# Normal use: install on your laptop via install.sh, not Docker

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY rag.py .
COPY chat.py .

# Default: drop into shell so users can run pk commands
ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
