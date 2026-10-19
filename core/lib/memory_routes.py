"""Authenticated memory routes; storage stays behind the memory service contract."""
from decimal import Decimal
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from starlette.concurrency import run_in_threadpool


class ProductInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=250)
    description: str = Field(default="", max_length=12000)
    price: Decimal = Field(ge=0, allow_inf_nan=False, max_digits=18, decimal_places=6)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    metadata: dict[str, Any] = Field(default_factory=dict)
    sku: str | None = Field(default=None, min_length=1, max_length=200)
    stock_count: StrictInt | None = Field(default=None, ge=0)
    checkout_url_template: str | None = Field(default=None, max_length=2000)

    @field_validator('checkout_url_template')
    @classmethod
    def checkout_template(cls, value):
        from services.sleyz.tools import validate_checkout_template
        return validate_checkout_template(value)

    @field_validator('sku')
    @classmethod
    def canonical_sku(cls, value):
        if value is not None and (not value.strip() or value != value.strip()):
            raise ValueError('SKU must be nonempty and have no surrounding whitespace')
        return value


class KnowledgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["faq", "manual"] = "manual"
    title: str = Field(min_length=1, max_length=250)
    content: str = Field(min_length=1, max_length=40000)


def create_memory_router(get_store: Callable, authenticate: Callable, assert_owner: Callable) -> APIRouter:
    router = APIRouter(prefix="/api/memory/{org_id}", tags=["memory"])

    async def call(org_id, auth, method, *args, **kwargs):
        await run_in_threadpool(assert_owner, auth.user_id, org_id)
        try:
            return await run_in_threadpool(getattr(get_store(), method), org_id, *args, **kwargs)
        except KeyError:
            raise HTTPException(404, "Memory record not found")
        except ValueError as error:
            raise HTTPException(422, str(error))

    @router.get("/identity")
    async def identity(org_id: str, auth=Depends(authenticate)):
        return await call(org_id, auth, "identity")

    @router.put("/identity")
    async def save_identity(org_id: str, payload: dict[str, Any], auth=Depends(authenticate)):
        allowed = {"brand_name", "industry", "target_location", "target_audience", "core_offer", "primary_goal", "brand_voice", "tone", "hex_colors", "voice_rules", "negative_constraints", "avoid_topics", "revision"}
        if set(payload) - allowed:
            raise HTTPException(422, "Unsupported identity field")
        return await call(org_id, auth, "save_identity", payload)

    @router.get("/identity/export/{filename}")
    async def export_identity(org_id: str, filename: str, auth=Depends(authenticate)):
        if filename not in {"brand_passport.md", "voice_rules.md", "negative_constraints.md"}:
            raise HTTPException(404, "Unknown identity document")
        result = await call(org_id, auth, "identity")
        return PlainTextResponse(result["exports"][filename], headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @router.get("/products")
    async def products(org_id: str, auth=Depends(authenticate)):
        return {"products": await call(org_id, auth, "products")}

    @router.post("/products")
    async def create_product(org_id: str, payload: ProductInput, auth=Depends(authenticate)):
        return await call(org_id, auth, "create_product", payload.model_dump(mode="json"))

    @router.put("/products/{product_id}")
    async def update_product(org_id: str, product_id: str, payload: ProductInput, auth=Depends(authenticate)):
        return await call(org_id, auth, "update_product", product_id, payload.model_dump(mode="json"))

    @router.delete("/products/{product_id}")
    async def delete_product(org_id: str, product_id: str, auth=Depends(authenticate)):
        return {"deleted": await call(org_id, auth, "delete_product", product_id)}

    @router.get("/knowledge")
    async def knowledge(org_id: str, auth=Depends(authenticate)):
        return {"knowledge": await call(org_id, auth, "knowledge")}

    @router.post("/knowledge")
    async def create_knowledge(org_id: str, payload: KnowledgeInput, auth=Depends(authenticate)):
        return await call(org_id, auth, "create_knowledge", payload.model_dump())

    @router.put("/knowledge/{source_id}")
    async def update_knowledge(org_id: str, source_id: str, payload: KnowledgeInput, auth=Depends(authenticate)):
        return await call(org_id, auth, "update_knowledge", source_id, payload.model_dump())

    @router.delete("/knowledge/{source_id}")
    async def delete_knowledge(org_id: str, source_id: str, auth=Depends(authenticate)):
        return {"deleted": await call(org_id, auth, "delete_knowledge", source_id)}

    @router.delete("/sources/{source_id}")
    async def forget_source(org_id: str, source_id: str, auth=Depends(authenticate)):
        return {"deleted": await call(org_id, auth, "forget_source", source_id)}

    @router.get("/search")
    async def search(org_id: str, q: str = Query(min_length=1, max_length=2000), limit: int = Query(default=8, ge=1, le=30), auth=Depends(authenticate)):
        return {"results": await call(org_id, auth, "search", q, limit=limit)}

    @router.get("/jobs")
    async def jobs(org_id: str, auth=Depends(authenticate)):
        return {"jobs": await call(org_id, auth, "jobs")}

    @router.post("/jobs/{job_id}/retry")
    async def retry_job(org_id: str, job_id: str, auth=Depends(authenticate)):
        return await call(org_id, auth, "retry_job", job_id)

    return router
