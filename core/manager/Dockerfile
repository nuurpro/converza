FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./requirements.txt
COPY manager/requirements.txt ./manager-requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r manager-requirements.txt
COPY . .
WORKDIR /app/manager
EXPOSE 8000
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
