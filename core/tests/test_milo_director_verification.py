import unittest
from copy import deepcopy
from services.milo.director.verification import verify_scene
from services.milo.director.verification import verify_master
from unittest.mock import AsyncMock
from test_milo_director_contracts import scene


def evidence():
    spec=scene();spec['narration_chunk']='Exact narration'
    return dict(scene_index=1,org_id='a',specification=spec,spec_hash='b'*64,attempt=1),dict(
        artifact_sha256='a'*64,spec_sha256='b'*64,
        media={'decoded':True,'duration_sec':3,'format_name':'mov,mp4','streams':[
            {'codec_type':'video','width':1080,'height':1920,'duration':'3','start_time':'0'},
            {'codec_type':'audio','duration':'3','start_time':'0'}]},
        alignment={'alignment_score':1,'anchor_coverage':1,'observed_words':[{'word':'Exact','start_ms':0,'end_ms':1000,'probability':1},{'word':'narration','start_ms':1000,'end_ms':2000,'probability':1}],
            'rendered_cues':[{'word':'Exact','start_ms':0,'end_ms':1000},{'word':'narration','start_ms':1000,'end_ms':2000}]},
        ocr=[{'time_sec':t,'observed_text':'Exact overlay','boxes':[{'left':100,'top':100,'width':300,'height':80,'conf':95}]} for t in (.15,1.5,2.85)],
        provenance=[{'org_id':'a','id':'asset','sku_tags':['bag']}])


class VerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_automatic_checks_and_150ms_boundary(self):
        task,result=evidence();result['alignment']['rendered_cues'][0]['end_ms']+=150
        self.assertTrue((await verify_scene(task,result))['passed'])
        result['alignment']['rendered_cues'][0]['end_ms']+=1
        self.assertFalse((await verify_scene(task,result))['passed'])

    async def test_ocr_tenant_media_missing_and_low_confidence_fail(self):
        for change in ('ocr','tenant','media','alignment'):
            task,result=evidence()
            if change=='ocr': result['ocr'][1]['observed_text']='Exact'
            if change=='tenant': result['provenance'][0]['org_id']='foreign'
            if change=='media': result['media']['streams'][0]['width']=720
            if change=='alignment': result['alignment']['anchor_coverage']=.89
            self.assertFalse((await verify_scene(task,result))['passed'],change)

    async def test_master_order_audio_ocr_and_narrative_before_promotion(self):
        task,result=evidence();spec=task['specification'];token=dict(scene_index=1,task_id='provider-1',artifact_sha256='a'*64,verified_token='verified')
        master={'specification':{'scenes':[token],'target_duration_sec':3},'narration_chunks':[spec['narration_chunk']],'scene_prompts':[spec]}
        value={'media':result['media'],'ordered_scenes':[{**token,'start_sec':0,'end_sec':3,'overlay_timeline':[spec['overlay_text']],'ocr':result['ocr']}],
            'audio':{'clipped_samples':0,'sample_count':48000},'narration_stem':{'clipped_samples':0,'rms_dbfs':-18},
            'music_present':False,'observed_words':result['alignment']['observed_words']}
        model=AsyncMock(return_value={'passed':True,'reasons':[]})
        self.assertTrue((await verify_master(master,value,model=model))['passed'])
        for change in ('order','ocr','clipping','ducking','narrative','overlay_metadata','missing_music'):
            broken=deepcopy(value);review=AsyncMock(return_value={'passed':True,'reasons':[]})
            if change=='order':broken['ordered_scenes'][0]['task_id']='foreign'
            if change=='ocr':broken['ordered_scenes'][0]['ocr'][0]['observed_text']='truncated'
            if change=='clipping':broken['audio']['clipped_samples']=1
            if change=='ducking':broken.update(music_present=True,ducking_windows=[{'narration_dbfs':-18,'background_dbfs':-20}])
            if change=='narrative':broken['observed_words']=[]
            if change=='overlay_metadata':broken['ordered_scenes'][0]['overlay_timeline'][0]['font_size']=100
            if change=='missing_music':master['specification']['background_asset_id']='requested-music'
            self.assertFalse((await verify_master(master,broken,model=review))['passed'],change)
            review.assert_not_awaited()

    async def test_master_semantic_coherence_can_block_technically_valid_master(self):
        task,result=evidence();spec=task['specification'];token=dict(scene_index=1,task_id='provider',artifact_sha256='a'*64,verified_token='v')
        value={'media':result['media'],'ordered_scenes':[{**token,'start_sec':0,'end_sec':3,'overlay_timeline':[spec['overlay_text']],'ocr':result['ocr']}],
            'audio':{'clipped_samples':0,'sample_count':1},'narration_stem':{'clipped_samples':0,'rms_dbfs':-18},'music_present':False,
            'observed_words':result['alignment']['observed_words']}
        report=await verify_master({'specification':{'scenes':[token],'target_duration_sec':3},'narration_chunks':[spec['narration_chunk']],'scene_prompts':[spec]},value,
            model=AsyncMock(return_value={'passed':False,'reasons':['Missing CTA']}))
        self.assertFalse(report['passed']);self.assertIn('Missing CTA',report['violations'])
