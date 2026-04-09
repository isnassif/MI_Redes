FROM python:3.11-slim

LABEL author="Seu Nome" \
      description="Atuador de resfriamento — PBL Redes" \
      version="1.0"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY atuador_resfriamento.py .

ENV BROKER_HOST=localhost

ENV ACTUATOR_ID=""

CMD ["python", "-u", "atuador_resfriamento.py"]
