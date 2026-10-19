FROM python:3.12-slim
WORKDIR /app/core
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY core/requirements.txt /app/core/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY core/main.py core/db.py core/llm.py /app/core/
COPY core/lib /app/core/lib
COPY core/services /app/core/services
COPY core/agents /app/core/agents
COPY Milo/identity.md /app/Milo/identity.md
COPY Sleyz/identity.md /app/Sleyz/identity.md
COPY Vea/identity.md /app/Vea/identity.md
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
