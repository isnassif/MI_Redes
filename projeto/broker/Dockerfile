FROM python:3.11-slim
 
LABEL author="Ikhlas Nassif" \
      description="Broker central do sistema de telemetria veicular — PBL Redes" \
      version="1.0"
 
WORKDIR /app
 
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
 
COPY broker.py .
 
EXPOSE 5000/udp
EXPOSE 5001
EXPOSE 5002
 
ENV BROKER_HOST=0.0.0.0
 
CMD ["python", "-u", "broker.py"]
 
