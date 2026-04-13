FROM python:3.11-slim
WORKDIR /app
COPY sensor_oleo.py .
ENV BROKER_HOST=localhost
CMD ["python", "-u", "sensor_oleo.py"]
