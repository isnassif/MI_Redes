FROM python:3.11-slim

LABEL author="Ikhlas Nassif" \
      description="Cliente terminal de monitoramento — PBL Redes" \
      version="1.0"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cliente.py .

ENV BROKER_HOST=localhost

CMD ["python", "-u", "cliente.py"]
