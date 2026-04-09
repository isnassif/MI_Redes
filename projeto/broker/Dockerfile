FROM python:3.11-slim
WORKDIR /app
COPY broker.py .
EXPOSE 5000/udp
EXPOSE 5001
EXPOSE 5002
CMD ["python", "-u", "broker.py"]
