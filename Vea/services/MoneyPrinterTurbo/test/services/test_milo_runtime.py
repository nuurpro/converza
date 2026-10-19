import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).parents[2]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class MiloRuntimeTests(unittest.TestCase):
    def test_env_key_and_approved_only_mode_disable_generation_and_publishing(self):
        runtime=load('milo_runtime_config',ROOT/'app/config/runtime.py')
        settings={'pexels_api_keys':['file-key'],'upload_post_enabled':True,'upload_post_auto_upload':True,'llm_provider':'openai'}
        runtime.apply_runtime_environment(settings,{'PEXELS_API_KEY':'server-key','MPT_APPROVED_ONLY':'1'})
        self.assertEqual(settings['pexels_api_keys'],['server-key'])
        self.assertTrue(settings['approved_only'])
        self.assertFalse(settings['upload_post_enabled'])
        self.assertFalse(settings['upload_post_auto_upload'])
        self.assertEqual(settings['llm_provider'],'disabled')

    def test_resource_bootstrap_acquires_font_and_creates_runtime_folders(self):
        bootstrap=load('milo_resource_bootstrap',ROOT/'scripts/prepare_resources.py')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'provider'; source=Path(folder)/'DejaVuSans.ttf'; source.write_bytes(b'test font fixture')
            result=bootstrap.prepare_resources(root,source)
            self.assertEqual(result.read_bytes(),source.read_bytes())
            self.assertTrue((root/'storage/tasks').is_dir())
            self.assertTrue((root/'resource/public').is_dir())
            self.assertTrue((root/'resource/songs').is_dir())
        with self.assertRaises(FileNotFoundError):bootstrap.prepare_resources(font_path='missing-font-file.ttf')
