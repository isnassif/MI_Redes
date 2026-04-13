FROM python:3.11-slim
WORKDIR /app
COPY sensor_velocidade.py .
ENV BROKER_HOST=localhost
CMD ["python", "-u", "sensor_velocidade.py"]
