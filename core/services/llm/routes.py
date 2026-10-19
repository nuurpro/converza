"""Service-only extraction bridge for non-Python callers of the shared client."""
import hmac
import os
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import complete_json

router=APIRouter(prefix='/api/internal/llm',tags=['internal inference'])


async def authenticate_service(x_llm_service_key: str | None=Header(None)):
    expected=os.getenv('LLM_SERVICE_API_KEY')
    if not expected or not x_llm_service_key or not hmac.compare_digest(expected,x_llm_service_key):
        raise HTTPException(403,'Inference service credentials required')


class Message(BaseModel):
    model_config=ConfigDict(extra='forbid')
    role: Literal['system','user','assistant']
    content: str=Field(max_length=50000)


class Extraction(BaseModel):
    model_config=ConfigDict(extra='forbid')
    messages: list[Message]=Field(min_length=1,max_length=30)
    output_schema: dict[str,Any]
    max_tokens: int=Field(default=1024,ge=64,le=8192)


@router.post('/extract',dependencies=[Depends(authenticate_service)])
async def extract(body: Extraction):
    try:
        return await complete_json([message.model_dump() for message in body.messages],operation='extraction',schema=body.output_schema,max_tokens=body.max_tokens)
    except Exception as error:
        raise HTTPException(502,f'Configured Huawei extraction failed ({type(error).__name__})') from None
