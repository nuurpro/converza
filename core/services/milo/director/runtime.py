"""Director integration with existing approved campaign jobs."""
import os
import logging
from .documents import DirectorDocuments
from .store import DirectorStore

logger=logging.getLogger('converza.milo.director')


async def reuse_snapshot(repo,org,current):
    from .provider import DirectorProvider
    passport=await repo.get_brand_passport(org)
    snapshot=getattr(repo,'director_reuse_context',None)
    if snapshot is None and os.getenv('MPT_API_KEY'):
        try:snapshot=await DirectorProvider().context(org,current.get('product_id'),current['artifact'].get('language') or current.get('language') or 'en')
        except Exception:
            logger.warning('director_cache_context_unavailable org=%s',org)
            return None
    if snapshot is None:return None
    return {'renderer':snapshot,'brand_revision':current['artifact']['brand_revision'],
        'palette':passport.get('hex_colors',[]),'negative_visual_constraints':passport.get('negative_visual_constraints',[]),
        'transition':os.getenv('MILO_DIRECTOR_TRANSITION','cut'),'background_asset_id':os.getenv('MILO_DIRECTOR_BACKGROUND_ASSET_ID') or None}


def enabled():
    return os.getenv('MILO_DIRECTOR_ENABLED','').strip().lower() in ('1','true','yes','on')


async def start_document(repo,org,campaign,document):
    from services.milo.store import MiloStore
    current=await MiloStore(repo).get_campaign(org,campaign)
    if not current or current['script_status']!='approved': return None
    board=document['storyboard'];store=DirectorStore(repo)
    runs=await store.list_for_campaign(org,campaign)
    key=f"storyboard:{board['revision']}:approved:{board['narration_approved']}"
    previous=next((r for r in runs if r['key']==key),None)
    if previous:return previous
    parent=next((r for r in runs if not r.get('superseded_by')),None)
    transition=os.getenv('MILO_DIRECTOR_TRANSITION','cut')
    if transition not in ('cut','crossfade'):raise ValueError('Unsupported director transition')
    return await store.create_run(org,campaign,current['revision'],board['scenes'],key,
        script_approved=board['narration_approved'],parent_run_id=parent['id'] if parent else None,
        storyboard_revision=board['revision'],language=current['artifact'].get('language') or current.get('language') or 'en',
        product_id=current.get('product_id'),
        reuse_context=await reuse_snapshot(repo,org,current),transitions=[transition]*(len(board['scenes'])-1),
        background_asset_id=os.getenv('MILO_DIRECTOR_BACKGROUND_ASSET_ID') or None)


async def start_pending(repo):
    docs=DirectorDocuments(repo)
    for row in await docs.pending():
        try:run=await start_document(repo,row['org_id'],row['campaign_id'],row)
        except Exception as exc:
            logger.warning('director_start_deferred org=%s campaign=%s error_type=%s',row['org_id'],row['campaign_id'],type(exc).__name__)
            continue
        if run:
            await docs.command(row['org_id'],row['campaign_id'],'started',expected_revision=row['storyboard']['revision'],
                key=f"started:{row['storyboard']['revision']}")


async def handoff_build(repo,job):
    from services.milo.store import MiloStore
    from .storyboard import decompose
    from services.milo.evidence import load_context
    from datetime import datetime,timedelta,timezone
    docs=DirectorDocuments(repo);org=job['org_id'];cid=job['campaign_id']
    document=await docs.document(org,cid)
    if not document:
        c=await MiloStore(repo).get_campaign(org,cid)
        context=await load_context(repo,org,MiloStore(repo),since=datetime.now(timezone.utc)-timedelta(days=7))
        board=await decompose(c['artifact'],context,product_id=c.get('product_id'))
        await docs.command(org,cid,'initialize',board=board,campaign_revision=c['revision'],key='initial')
        document=await docs.document(org,cid)
    # Sign-off is recorded atomically with the original approval/build intent.
    # A delayed job must never approve a later narration revision, even a revert.
    await start_document(repo,org,cid,document)
    await docs.handoff(job)


def worker(repo,model=None):
    from .worker import DirectorWorker
    from .provider import DirectorProvider
    from .verification import verify_scene,verify_master
    class ScopedRenderer(DirectorProvider):
        async def submit(self,task):
            from services.milo.store import MiloStore
            from services.milo.evidence import load_context
            from services.milo.pipeline import validate_brand_compliance
            from services.workflow.state import WorkflowConflict
            from .storyboard import as_campaign
            from datetime import datetime,timedelta,timezone
            doc=await DirectorDocuments(repo).document(task['org_id'],task['campaign_id'])
            if not doc or doc['storyboard']['revision']!=task['storyboard_revision'] or not doc['storyboard']['narration_approved']:
                raise WorkflowConflict('Narration revision no longer approved')
            campaign=await MiloStore(repo).get_campaign(task['org_id'],task['campaign_id'])
            context=await load_context(repo,task['org_id'],MiloStore(repo),since=datetime.now(timezone.utc)-timedelta(days=7))
            report=validate_brand_compliance(as_campaign(campaign['artifact'],doc['storyboard']['scenes']),context)
            if not report['passed']:raise ValueError('Current brand evidence requires review: '+'; '.join(report['violations']))
            return await super().submit(task)
    async def master(task,result):return await verify_master(task,result,model=model)
    return DirectorWorker(repo,renderer=ScopedRenderer(),scene_verifier=verify_scene,master_verifier=master)
