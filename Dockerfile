FROM python:3.13-alpine

WORKDIR /app
COPY server.py .

ENV PYTHONUNBUFFERED=1
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s \
  CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1

CMD ["python", "-I", "server.py"]
