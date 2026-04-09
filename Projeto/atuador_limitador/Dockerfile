FROM python:3.11-slim
WORKDIR /app
COPY atuador_limitador.py .
ENV BROKER_HOST=localhost
CMD ["python", "-u", "atuador_limitador.py"]
