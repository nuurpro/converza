"""Provider orchestration gates without loading codecs or paid providers.

Import the real task service with its media/network dependencies stubbed. Tests
exercise the actual script/subtitle/start functions and use real SRT files.
"""
import importlib.util
import sys
import tempfile
import unittest
from enum import Enum
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).parents[2]


class Concat(str, Enum):
    sequential = 'sequential'
    random = 'random'


class ApprovedScenePipelineTests(unittest.TestCase):
    def setUp(self):
        helper_spec=importlib.util.spec_from_file_location('scene_pipeline_helper',ROOT/'app/services/approved_scenes.py')
        self.helper=importlib.util.module_from_spec(helper_spec); helper_spec.loader.exec_module(self.helper)
        self.config=SimpleNamespace(app={'subtitle_provider':'edge'})
        services=ModuleType('app.services'); services.__path__=[]
        self.dependencies={name:MagicMock() for name in ['llm','material','subtitle','twelvelabs','video','voice','upload_post','state']}
        for name,value in self.dependencies.items():setattr(services,name,value)
        utils=ModuleType('app.utils'); utils.utils=MagicMock(); utils.file_security=MagicMock()
        stubs={'loguru':SimpleNamespace(logger=MagicMock()),'app.config':SimpleNamespace(config=self.config),
            'app.models':SimpleNamespace(const=SimpleNamespace(TASK_STATE_FAILED=-1,TASK_STATE_PROCESSING=4,TASK_STATE_COMPLETE=1)),
            'app.models.schema':SimpleNamespace(VideoConcatMode=Concat,VideoParams=object),
            'app.services':services,'app.services.approved_scenes':self.helper,'app.utils':utils}
        spec=importlib.util.spec_from_file_location('approved_task_pipeline_test',ROOT/'app/services/task.py')
        self.task=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,stubs):spec.loader.exec_module(self.task)

    def scenes(self):
        return [{'spoken_narration':'Exact narration.','visual_broll_cues':'steel','on_screen_text':'Tested'}]

    def params(self):
        scenes=self.scenes()
        return SimpleNamespace(video_script='Exact narration.',approved_scenes=[SimpleNamespace(model_dump=lambda:scenes[0])],
            subtitle_enabled=True,video_source='pexels',video_concat_mode='sequential')

    def test_generate_script_passes_approved_whitespace_unchanged_without_model(self):
        params=self.params(); params.video_script='  Exact narration.  '
        self.assertEqual(self.task.generate_script('id',params),params.video_script)
        self.dependencies['llm'].generate_script.assert_not_called()

    def test_approved_cues_reach_stock_search_in_order_without_model_or_reranking(self):
        params=self.params(); params.video_terms=['steel hinge','laboratory test','product demo']
        params.match_materials_to_script=True; params.video_aspect='9:16'; params.video_count=1; params.video_clip_duration=5
        terms=self.task.generate_terms('id',params,params.video_script)
        self.assertEqual(terms,params.video_terms)
        self.task.get_video_materials('id',params,terms,10)
        self.assertEqual(self.dependencies['material'].download_videos.call_args.kwargs['search_terms'],params.video_terms)
        self.assertTrue(self.dependencies['material'].download_videos.call_args.kwargs['match_script_order'])
        self.dependencies['llm'].generate_terms.assert_not_called()
        self.dependencies['twelvelabs'].rerank_terms_by_subject.assert_not_called()

    def test_narration_reaches_tts_without_script_rewriting(self):
        params=self.params(); params.voice_name='uz-UZ-MadinaNeural'; params.voice_rate=1
        params.video_script="O‘zbekcha matn.\n\nАниқ матн."
        self.dependencies['voice'].get_audio_duration.return_value=3
        self.task.utils.task_dir.return_value='test-task-dir'
        self.task.generate_audio('id',params,params.video_script)
        self.assertEqual(self.dependencies['voice'].tts.call_args.kwargs['text'],params.video_script)

    def test_approved_overlay_is_written_with_narration_timing(self):
        params=self.params()
        with tempfile.TemporaryDirectory() as folder:
            self.task.utils.task_dir.return_value=folder
            def create(**kwargs):Path(kwargs['subtitle_file']).write_text('1\n00:00:00,100 --> 00:00:02,500\nExact narration.\n\n',encoding='utf-8')
            self.dependencies['voice'].create_subtitle.side_effect=create
            self.dependencies['subtitle'].file_to_subtitles.return_value=[object()]
            result=self.task.generate_subtitle('id',params,params.video_script,object(),'audio.mp3')
            self.assertEqual(self.helper.read_scene_overlays(result),[((0.1,2.5),'Tested')])

    def test_missing_timing_blocks_instead_of_silently_dropping_overlay(self):
        params=self.params()
        with self.assertRaisesRegex(ValueError,'timing'):
            self.task.generate_subtitle('id',params,params.video_script,None,'audio.mp3')

    def test_completed_approved_render_skips_configured_automatic_cross_post(self):
        params=self.params(); self.dependencies['upload_post'].upload_post_service.is_configured.return_value=True
        params.milo_binding=SimpleNamespace(model_dump=lambda:{'job_id':'build','org_id':'brand'})
        self.dependencies['upload_post'].upload_post_service.auto_upload=True
        with patch.object(self.task,'generate_script',return_value='Exact narration.'), \
             patch.object(self.task,'generate_terms',return_value=['steel']), \
             patch.object(self.task,'save_script_data'), \
             patch.object(self.task,'generate_audio',return_value=('audio.mp3',3,object())), \
             patch.object(self.task,'generate_subtitle',return_value='approved-scenes.srt'), \
             patch.object(self.task,'get_video_materials',return_value=['steel.mp4']), \
             patch.object(self.task,'generate_final_videos',return_value=(['final.mp4'],['combined.mp4'])):
            result=self.task.start('id',params)
        self.assertEqual(result['videos'],['final.mp4'])
        self.assertEqual(result['milo_binding'],{'job_id':'build','org_id':'brand'})
        self.dependencies['upload_post'].cross_post_video.assert_not_called()
        self.dependencies['llm'].generate_social_metadata.assert_not_called()

    def test_approved_pipeline_exception_sets_terminal_failed_task(self):
        with patch.object(self.task,'generate_script',side_effect=ValueError('alignment failed')):
            result=self.task.start('id',self.params())
        self.assertIsNone(result)
        self.dependencies['state'].state.update_task.assert_called_with('id',state=-1,error_code='approved_scene_render_failed')
