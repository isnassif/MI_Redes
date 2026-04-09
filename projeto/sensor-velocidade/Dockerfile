FROM python:3.11-slim

LABEL author="Seu Nome" \
      description="Sensor de velocidade — PBL Redes" \
      version="1.0"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sensor_velocidade.py .

ENV BROKER_HOST=localhost

ENV SENSOR_ID=""

CMD ["python", "-u", "sensor_velocidade.py"]
