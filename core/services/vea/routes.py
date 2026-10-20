"""Owner-scoped VEA variant commands and authenticated renderer catalogs."""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from starlette.concurrency import run_in_threadpool
from services.workflow.state import WorkflowConflict
from .contracts import VariantRequest, RevisionRequest, SwapRequest
from .store import VeaStore, enabled, fetch_renderer


def create_vea_router(get_repo, authenticate, assert_owner):
    router=APIRouter(prefix='/api/vea/{org_id}',tags=['vea'])

    async def scoped(org_id,auth):
        await run_in_threadpool(assert_owner,auth.user_id,org_id)
        return get_repo()

    async def invoke(operation):
        try:
            return await operation
        except WorkflowConflict as exc:
            raise HTTPException(409,str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from None
        except (RuntimeError, OSError):
            raise HTTPException(503,'VEA renderer is unavailable. Check renderer configuration and retry.') from None
        except Exception as exc:
            import httpx
            if isinstance(exc,httpx.HTTPError):
                raise HTTPException(503,'VEA renderer is unavailable. Check renderer configuration and retry.') from None
            raise

    def capability():
        if not enabled():
            raise HTTPException(503,'VEA preset rendering is disabled on this server.')

    @router.get('/presets')
    async def presets(org_id:str,auth=Depends(authenticate)):
        await scoped(org_id,auth)
        data=await invoke(fetch_renderer('presets'))
        keys={'id','preset_id','name','description','version','sha256','resolution','fps','aspect_ratio'}
        return {'presets':[{k:v for k,v in row.items() if k in keys} for row in data['presets']]}

    @router.get('/assets')
    async def assets(org_id:str,product_id:str|None=Query(default=None,max_length=200),language:str=Query(default='en',pattern='^(en|ru|uz)$'),auth=Depends(authenticate)):
        await scoped(org_id,auth)
        data=await invoke(fetch_renderer('assets',{'org_id':org_id,'product_id':product_id,'language':language}))
        keys={'id','asset_id','name','title','tags','duration_sec','width','height','sha256','product_id','kind'}
        return {'assets':[{k:v for k,v in row.items() if k in keys} for row in data['assets']]}

    @router.get('/variants')
    async def variants(org_id:str,auth=Depends(authenticate)):
        return {'variants':await VeaStore(await scoped(org_id,auth)).list_variants(org_id)}

    @router.get('/variants/{variant_id}')
    async def variant(org_id:str,variant_id:str,auth=Depends(authenticate)):
        row=await VeaStore(await scoped(org_id,auth)).get_variant(org_id,variant_id)
        if not row: raise HTTPException(404,'VEA variant not found')
        return row

    @router.post('/variants',status_code=202)
    async def create(org_id:str,body:VariantRequest,idempotency_key:str=Header(min_length=1,max_length=200),auth=Depends(authenticate)):
        repo=await scoped(org_id,auth);capability()
        return await invoke(VeaStore(repo).create_variant(org_id,body.campaign_id,body.expected_revision,body.preset_id,idempotency_key))

    @router.post('/variants/{variant_id}/swap',status_code=202)
    async def swap(org_id:str,variant_id:str,body:SwapRequest,idempotency_key:str=Header(min_length=1,max_length=200),auth=Depends(authenticate)):
        repo=await scoped(org_id,auth);capability()
        return await invoke(VeaStore(repo).swap(org_id,variant_id,body.expected_revision,body.segment_id,body.asset_id,idempotency_key))

    @router.post('/variants/{variant_id}/retry',status_code=202)
    async def retry(org_id:str,variant_id:str,body:RevisionRequest,idempotency_key:str=Header(min_length=1,max_length=200),auth=Depends(authenticate)):
        repo=await scoped(org_id,auth)
        # Turning off new production must not strand recovery of existing work.
        return await invoke(VeaStore(repo).retry(org_id,variant_id,body.expected_revision,idempotency_key))

    return router
