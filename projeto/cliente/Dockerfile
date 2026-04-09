FROM python:3.11-slim

LABEL author="Seu Nome" \
      description="Cliente terminal de monitoramento — PBL Redes" \
      version="1.0"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cliente.py .

ENV BROKER_HOST=localhost

CMD ["python", "-u", "cliente.py"]
