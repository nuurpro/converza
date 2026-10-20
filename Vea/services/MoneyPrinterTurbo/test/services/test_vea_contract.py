import hashlib
import json
import unittest

from app.models.schema import TaskVideoRequest


class VeaContractTests(unittest.TestCase):
    def payload(self):
        scenes = [{'spoken_narration': 'Exact words.', 'visual_broll_cues': 'steel hinge', 'on_screen_text': 'Line one\n\nLine two'}]
        config = {'schema_version': 1, 'preset_id': 'high_velocity_d2c',
                  'preset_version': None, 'preset_sha256': None,
                  'brand_snapshot': {'revision': 1, 'hex_colors': ['#123456']}, 'product_id': None,
                  'variant_id': 'variant', 'variant_revision': 1, 'clip_overrides': [], 'reuse_manifest': None}
        sha = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        return {'video_subject': 'test', 'video_script': 'Exact words.', 'video_terms': ['steel hinge'],
                'video_language': 'en', 'approved_scenes': scenes, 'vea_config': config,
                'milo_binding': {'job_id': 'job', 'org_id': 'org', 'campaign_id': 'campaign', 'script_revision': 1,
                                 'script_sha256': sha({'video_script': scenes, 'language': 'en'}), 'vea_config_sha256': sha(config)}}

    def test_configuration_binding_round_trips_canonical_hash(self):
        payload = self.payload()
        model = TaskVideoRequest(**payload)
        self.assertEqual(model.vea_config.model_dump(), payload['vea_config'])

    def test_configuration_hash_tampering_refused(self):
        payload = self.payload(); payload['vea_config']['variant_revision'] = 2
        with self.assertRaises(ValueError): TaskVideoRequest(**payload)

    def test_vea_requires_bound_approved_scenes(self):
        payload = self.payload(); payload.pop('approved_scenes')
        with self.assertRaises(ValueError): TaskVideoRequest(**payload)

    def test_legacy_binding_has_no_new_null_field(self):
        payload = self.payload(); payload.pop('vea_config'); payload['milo_binding'].pop('vea_config_sha256')
        model = TaskVideoRequest(**payload)
        self.assertEqual(model.milo_binding.model_dump()['provider_attempt'], 1)
        self.assertNotIn('vea_config_sha256', model.milo_binding.model_dump())


if __name__ == '__main__': unittest.main()
