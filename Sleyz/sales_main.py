"""Active service entry point: uvicorn Sleyz.sales_main:app from repository root."""
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / "core" / ".env")

from Sleyz.routers.webhook import router as webhook_router

app = FastAPI(title="Converza Sales Bot")
app.include_router(webhook_router)


@app.get("/health")
def health():
    return {"status": "ok", "bot": "sales", "version": "1.1"}
