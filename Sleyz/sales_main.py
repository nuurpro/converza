"""Active service entry point: uvicorn Sleyz.sales_main:app from repository root."""
from services.runtime import load_environment
from fastapi import FastAPI

load_environment()

from Sleyz.routers.webhook import router as webhook_router

app = FastAPI(title="Converza Sales Bot")
app.include_router(webhook_router)

from services.sleyz.channels import create_instagram_router
from Sleyz.db import client as sales_db
app.include_router(create_instagram_router(sales_db.get_repository))


@app.get("/health")
def health():
    return {"status": "ok", "bot": "sales", "version": "1.1"}
