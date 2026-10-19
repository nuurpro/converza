FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app:/app/core
COPY core/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY core/services /app/core/services
COPY core/lib /app/core/lib
COPY core/db.py /app/core/db.py
COPY Sleyz/__init__.py Sleyz/sales_main.py /app/Sleyz/
COPY Sleyz/agents /app/Sleyz/agents
COPY Sleyz/routers /app/Sleyz/routers
COPY Sleyz/db /app/Sleyz/db
COPY Sleyz/personas /app/Sleyz/personas
EXPOSE 8000
CMD ["uvicorn", "Sleyz.sales_main:app", "--host", "0.0.0.0", "--port", "8000"]
