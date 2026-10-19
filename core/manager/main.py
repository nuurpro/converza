import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI

from routers import webhook

app = FastAPI(title="Converza Manager Bot", version="1.0.0")

app.include_router(webhook.router)


@app.get("/health")
async def health():
    return {"status": "ok", "bot": "manager", "version": "1.0"}
