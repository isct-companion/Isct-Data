FROM python:3.12-slim
RUN pip install --no-cache-dir 'PyJWT[crypto]>=2.10,<3'
COPY --chmod=0644 server.py /opt/status/server.py
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["python", "/opt/status/server.py"]
