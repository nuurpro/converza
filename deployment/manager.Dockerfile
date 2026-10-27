FROM python:3.12-slim
WORKDIR /app/core
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/core
COPY core/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY core/lib ./lib
COPY core/services ./services
COPY core/manager ./manager
WORKDIR /app/core/manager
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
