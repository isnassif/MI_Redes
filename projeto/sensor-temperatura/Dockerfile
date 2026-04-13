FROM python:3.11-slim
WORKDIR /app
COPY sensor_temperatura.py .
ENV BROKER_HOST=localhost
CMD ["python", "-u", "sensor_temperatura.py"]
