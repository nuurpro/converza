import importlib.util
from pathlib import Path
import unittest
import sys
import hashlib
import json
import tempfile
from types import SimpleNamespace
from unittest.mock import patch


SPEC=importlib.util.spec_from_file_location('approved_scenes',Path(__file__).parents[2]/'app/services/approved_scenes.py')
module=importlib.util.module_from_spec(SPEC)


class ApprovedSceneTests(unittest.TestCase):
    def setUp(self):
        SPEC.loader.exec_module(module)
        self.scenes=[{'spoken_narration':'Does it last?','on_screen_text':'Built to last'},
                     {'spoken_narration':'See the test.','on_screen_text':'Watch the test'}]

    def test_overlay_text_uses_narration_cue_timing_and_exact_approved_text(self):
        cues=[((0.1,1.5),'Does it last?'),((1.7,3.1),'See the test.')]
        self.assertEqual(module.scene_overlays(self.scenes,cues),[((0.1,1.5),'Built to last'),((1.7,3.1),'Watch the test')])

    def test_multi_sentence_scene_and_unicode_alignment(self):
        scenes=[{'spoken_narration':'Привет! Всё хорошо?','on_screen_text':'Проверено'},
                {'spoken_narration':"Sinab ko‘ring.",'on_screen_text':"Ko‘ring"}]
        cues=[((0,1),'Привет!'),((1,3),'Всё хорошо?'),((3.2,5),"Sinab ko‘ring.")]
        self.assertEqual(module.scene_overlays(scenes,cues),[((0,3),'Проверено'),((3.2,5),"Ko‘ring")])

    def test_cue_crossing_scene_boundary_interpolates_boundary(self):
        scenes=[{'spoken_narration':'AB','on_screen_text':'first'},{'spoken_narration':'CD','on_screen_text':'last'}]
        self.assertEqual(module.scene_overlays(scenes,[((0,4),'ABCD')]),[((0,2),'first'),((2,4),'last')])

    def test_unaligned_or_missing_subtitles_block_overlay(self):
        for cues in [[],[((0,2),'An unrelated narration')]]:
            with self.assertRaisesRegex(ValueError,'align'):module.scene_overlays(self.scenes,cues)

    def test_empty_overlay_removes_narration_subtitle_for_that_scene(self):
        self.scenes[0]['on_screen_text']=''
        result=module.scene_overlays(self.scenes,[((0,1),'Does it last?'),((1,2),'See the test.')])
        self.assertEqual(result,[((1,2),'Watch the test')])

    def test_narration_srt_timings_are_read_before_overlay_alignment(self):
        with tempfile.TemporaryDirectory() as folder:
            filename=Path(folder)/'scenes.srt'
            filename.write_text('1\n00:00:00,100 --> 00:00:01,500\nDoes it last?\n\n2\n00:00:01,700 --> 00:00:03,100\nSee the test.\n',encoding='utf-8')
            self.assertEqual(module.read_subtitle_cues(filename),[((0.1,1.5),'Does it last?'),((1.7,3.1),'See the test.')])

    def test_json_overlay_timeline_preserves_blank_lines_and_timing_like_text(self):
        self.scenes[0]['on_screen_text']='First line\n\nSecond line\n00:00:00,100 --> 00:00:01,000'
        cues=[((0.1,1.5),'Does it last?'),((1.7,3.1),'See the test.')]
        with tempfile.TemporaryDirectory() as folder:
            filename=Path(folder)/'overlays.json'
            module.write_scene_overlays(filename,self.scenes,cues)
            self.assertEqual(module.read_scene_overlays(filename),module.scene_overlays(self.scenes,cues))


class ApprovedSceneSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The schema only needs UI defaults from config. Avoid loading provider
        # media dependencies/network configuration for this contract gate.
        schema_path=Path(__file__).parents[2]/'app/models/schema.py'
        spec=importlib.util.spec_from_file_location('approved_scene_schema_test',schema_path)
        cls.schema=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'approved_scene_schema_test':cls.schema,
                'app.config':SimpleNamespace(config=SimpleNamespace(ui={}))}):
            spec.loader.exec_module(cls.schema)

    def parameters(self):
        scene={'spoken_narration':'  Exact narration.  ','visual_broll_cues':'steel hinge','on_screen_text':'Tested steel'}
        return dict(video_subject='campaign',video_script=scene['spoken_narration'],
            video_terms=[scene['visual_broll_cues']],approved_scenes=[scene])

    def test_approved_scene_schema_preserves_exact_fields_and_enables_order(self):
        values=self.parameters(); result=self.schema.VideoParams(**values)
        self.assertEqual(result.video_script,values['video_script'])
        self.assertEqual(result.approved_scenes[0].model_dump(),values['approved_scenes'][0])
        self.assertTrue(result.match_materials_to_script)
        self.assertEqual(result.video_concat_mode,'sequential')

    def test_mismatched_narration_cues_or_custom_audio_are_rejected(self):
        for replacement in [dict(video_script='rewritten'),dict(video_terms=['different']),dict(custom_audio_file='sound.mp3'),dict(subtitle_enabled=False)]:
            values={**self.parameters(),**replacement}
            with self.assertRaises(ValueError):self.schema.VideoParams(**values)

    def test_legacy_request_still_accepts_plain_script(self):
        params=self.schema.VideoParams(video_subject='legacy',video_script='Legacy script')
        self.assertIsNone(params.approved_scenes)

    def test_binding_hash_must_match_all_approved_scene_fields_and_language(self):
        values=self.parameters(); values['video_language']='uz'
        serialized=json.dumps({'video_script':values['approved_scenes'],'language':'uz'},sort_keys=True,ensure_ascii=False,separators=(',',':'))
        values['milo_binding']={'job_id':'j','org_id':'a','campaign_id':'c','script_revision':3,
            'provider_attempt':1,
            'script_sha256':hashlib.sha256(serialized.encode()).hexdigest()}
        result=self.schema.VideoParams(**values)
        self.assertEqual(result.milo_binding.model_dump(),values['milo_binding'])
        for field in ['spoken_narration','visual_broll_cues','on_screen_text']:
            import copy
            changed=copy.deepcopy(values); changed['approved_scenes'][0][field]+='changed'
            changed['video_script']=changed['approved_scenes'][0]['spoken_narration']
            changed['video_terms']=[changed['approved_scenes'][0]['visual_broll_cues']]
            with self.assertRaises(ValueError):self.schema.VideoParams(**changed)
        with self.assertRaises(ValueError):self.schema.VideoParams(**{**values,'video_language':'ru'})


class ProviderBindingStateTests(unittest.TestCase):
    def test_memory_progress_updates_preserve_creation_binding(self):
        root=Path(__file__).parents[2]; sys.path.insert(0,str(root))
        spec=importlib.util.spec_from_file_location('milo_bound_provider_state',root/'app/services/state.py')
        state_module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'app.config':SimpleNamespace(config=SimpleNamespace(ui={},app={}))}):
            spec.loader.exec_module(state_module)
        state=state_module.MemoryState(); binding={'job_id':'build','org_id':'brand'}
        state.update_task('t',state=4,milo_binding=binding)
        state.update_task('t',state=4,progress=50)
        self.assertEqual(state.get_task('t')['milo_binding'],binding)
        state.update_task('t',state=1,videos=['final.mp4'])
        self.assertEqual(state.get_task('t')['milo_binding'],binding)
