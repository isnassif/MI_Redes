FROM python:3.11-slim
WORKDIR /app
COPY atuador_resfriamento.py .
ENV BROKER_HOST=localhost
CMD ["python", "-u", "atuador_resfriamento.py"]
