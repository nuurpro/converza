"""Evaluate source safety and variant determinism without inference or rendering.

Run from core: python -m services.vea.evals.run. All cases must pass.
Renderer matching, alignment and media quality have their own renderer eval lane.
"""
import asyncio
import json

from lib.repository import InMemoryRepository
from services.milo.store import MiloStore
from services.workflow.state import WorkflowConflict
from ..store import VeaStore, prepare_build, _relevant_replacement


async def run():
    cases=[]
    for language,text in [('en','This bag has reinforced stitching.'),('ru','У этой сумки усиленные швы.'),('uz','Bu sumkaning choklari mustahkamlangan.')]:
        repo=InMemoryRepository();repo.seed_brand_passport('brand',{'revision':1,'hex_colors':['#223344']})
        milo=MiloStore(repo);vea=VeaStore(repo)
        campaign=await milo.enqueue('brand','manual',language=language,key='campaign')
        script=[{'spoken_narration':text,'visual_broll_cues':'Product stitching','on_screen_text':text}]
        job=(await milo.claim('generate'))[0]
        campaign=await milo.complete_generation(job,{'brand_revision':1,'proof_references':[],'video_script':script,'language':language},
            {'passed':True,'semantic_checked':True,'checked_brand_revision':1},selected_scope={'product_id':'bag','topic':'durability'})
        campaign=await milo.decide_script('brand',campaign['id'],'approve',campaign['revision'],'approve')
        job=await prepare_build((await milo.claim('build'))[0],milo)
        cases.append({'id':'selected_scope_'+language,'kind':'safety','passed':campaign['product_id']=='bag' and job['payload']['vea_config']['product_id']=='bag'})
        matching={'tags':{language:['STITCHING!']}}
        unrelated={'tags':{language:['Mountain']}}
        cases.append({'id':'visual_relevance_'+language,'kind':'safety','passed':
            _relevant_replacement(matching,{'scene_index':0},campaign,language) and
            not _relevant_replacement(unrelated,{'scene_index':0},campaign,language)})
        cases.append({'id':'approved_words_'+language,'kind':'safety','passed':job['payload']['video_script']==script and job['payload']['language']==language})
        rows=await asyncio.gather(*(vea.create_variant('brand',campaign['id'],campaign['revision'],'editorial_showcase','manual') for _ in range(4)))
        cases.append({'id':'idempotency_'+language,'kind':'quality','passed':len({r['id'] for r in rows})==1 and len(await vea.list_variants('brand'))==2})
        cases.append({'id':'tenant_isolation_'+language,'kind':'safety','passed':not await vea.list_variants('foreign') and await vea.get_variant('foreign',rows[0]['id']) is None})
        repo.brand_passports['brand']['revision']=2
        try:
            await vea.create_variant('brand',campaign['id'],campaign['revision'],'editorial_showcase','stale')
            blocked=False
        except WorkflowConflict:
            blocked=True
        cases.append({'id':'stale_evidence_'+language,'kind':'safety','passed':blocked})
    rates={kind:sum(c['passed'] for c in cases if c['kind']==kind)/sum(c['kind']==kind for c in cases) for kind in ('safety','quality')}
    return {'lane':'fixture',**rates,'cases':cases}


def cli():
    report=asyncio.run(run())
    print(json.dumps(report,ensure_ascii=True))
    return int(report['safety']<1 or report['quality']<1)


if __name__=='__main__':raise SystemExit(cli())
