FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "jsonschema>=4.25,<5" \
    # The checkout lives on a host volume owned by another user.
    && git config --global --add safe.directory /data/repo

ENV PYTHONUNBUFFERED=1
COPY runner.py /usr/local/bin/syllabus-reader
ENTRYPOINT ["python", "/usr/local/bin/syllabus-reader"]
