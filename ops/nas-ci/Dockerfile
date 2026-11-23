FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates openssl \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/isct/requirements.txt
RUN pip install --no-cache-dir -r /opt/isct/requirements.txt

COPY --chmod=0644 ops/nas-ci/runner.py ops/nas-ci/review.py /opt/isct/ci/
COPY --chmod=0644 ops/syllabus-reader/runner.py /opt/isct/syllabus.py
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 HOME=/tmp GIT_TERMINAL_PROMPT=0
