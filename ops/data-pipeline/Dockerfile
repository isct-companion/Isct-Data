FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates openssl \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/isct/requirements.txt
RUN pip install --no-cache-dir -r /opt/isct/requirements.txt

# Only the scheduler is baked in: every job runs the scripts of a fresh checkout of main.
COPY --chmod=0644 ops/data-pipeline/runner.py ops/data-pipeline/review.py ops/data-pipeline/status.py \
    ops/data-pipeline/status_pages.py /opt/isct/
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 HOME=/tmp GIT_TERMINAL_PROMPT=0
ENTRYPOINT ["python", "/opt/isct/runner.py"]
CMD ["serve"]
