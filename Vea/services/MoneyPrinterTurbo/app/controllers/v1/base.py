import hmac
import os
from fastapi import APIRouter, Depends, Header, HTTPException
from app.config import config


def require_provider_auth(authorization: str | None = Header(default=None)):
    if not config.app.get('approved_only', False):
        return
    key = os.getenv('MPT_API_KEY', '').strip()
    if not key:
        raise HTTPException(status_code=503, detail='Renderer control authentication is not configured')
    if not hmac.compare_digest(authorization or '', 'Bearer ' + key):
        raise HTTPException(status_code=401, detail='Renderer control authentication required',
                            headers={'WWW-Authenticate': 'Bearer'})


def new_router(dependencies=None):
    router = APIRouter()
    router.tags = ["V1"]
    router.prefix = "/api/v1"
    # 将认证依赖项应用于所有路由
    router.dependencies = [Depends(require_provider_auth), *(dependencies or [])]
    return router
