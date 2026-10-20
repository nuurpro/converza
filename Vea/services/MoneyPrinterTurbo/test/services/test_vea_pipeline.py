"""Deterministic VEA gates; no provider credentials or model downloads required."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from app.services import vea


def words(text, step=200):
    return [{'word': token, 'start_ms': i * step + 20, 'end_ms': (i + 1) * step}
            for i, token in enumerate(text.split())]


class AlignmentTests(unittest.TestCase):
    def test_syllable_fragments_share_one_acoustic_anchor(self):
        observed = words('wonder ful product makes every morning feel a little more special')
        result = vea.align_words('wonderful product makes every morning feel a little more special', observed, 2500)
        self.assertEqual(result['words'][0]['start_ms'], 20)
        self.assertEqual(result['words'][0]['end_ms'], 400)
        self.assertFalse(result['interpolated_token_indices'])

    def test_two_missing_tokens_interpolate_and_three_are_rejected(self):
        approved = ' '.join('word' + str(i) for i in range(30))
        observed = words(approved)
        observed[3:5] = []
        result = vea.align_words(approved, observed, 6200)
        self.assertEqual(result['interpolated_token_indices'], [3, 4])
        self.assertLessEqual(result['words'][3]['end_ms'], result['words'][4]['start_ms'])
        for index in range(len(result['words']) - 1):
            self.assertLessEqual(result['words'][index]['end_ms'], result['words'][index + 1]['start_ms'])
    def test_normalization_preserves_original_caption_words_in_three_languages(self):
        for approved, spoken in [('Buy NOW, today!', 'buy now today'),
                                  ('Купите СЕЙЧАС, друзья!', 'купите сейчас друзья'),
                                  ("O‘zbekcha yaxshi mahsulot.", "o'zbekcha yaxshi mahsulot")]:
            result = vea.align_words(approved, words(spoken), 1000)
            self.assertEqual([w['word'] for w in result['words']], approved.split())
            self.assertEqual(result['alignment_score'], 1)

    def test_exactly_ninety_percent_accepts_neighbor_interpolation(self):
        approved = 'one two three four five six seven eight nine ten'
        observed = words(approved)
        observed.pop(4)
        result = vea.align_words(approved, observed, 2200)
        self.assertAlmostEqual(result['alignment_score'], .9)
        self.assertEqual(result['interpolated_token_indices'], [4])
        self.assertEqual(result['words'][4]['start_ms'], 800)
        self.assertEqual(result['words'][4]['end_ms'], 1020)

    def test_small_fuzzy_substitution_anchors_without_replacing_approved_words(self):
        approved = 'wonderful product makes every morning feel a little more special'
        result = vea.align_words(approved, words(approved.replace('wonderful', 'wonderfull')), 2200)
        self.assertGreaterEqual(result['alignment_score'], .9)
        self.assertEqual(result['words'][0]['word'], 'wonderful')
        self.assertFalse(result['interpolated_token_indices'])

    def test_scene_edges_use_measured_anchors(self):
        approved = 'one two three four five six seven eight nine ten'
        for index, bounds in [(0, (0, 220)), (9, (1800, 2200))]:
            observed = words(approved); observed.pop(index)
            result = vea.align_words(approved, observed, 2200)
            self.assertEqual((result['words'][index]['start_ms'], result['words'][index]['end_ms']), bounds)

    def test_low_confidence_or_long_gaps_or_invalid_anchors_are_rejected(self):
        cases = [('one two three four five', words('one two other four five'), 1100),
                 (' '.join(str(i) for i in range(30)), words(' '.join(str(i) for i in range(3, 30))), 6500),
                 ('one two', [{'word': 'one', 'start_ms': 20, 'end_ms': 500},
                              {'word': 'two', 'start_ms': 300, 'end_ms': 600}], 700)]
        for approved, observed, duration in cases:
            with self.assertRaises(vea.VeaError): vea.align_words(approved, observed, duration)


class CatalogAndRecipeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        (self.root / 'clip.mp4').write_bytes(b'fixture')
        self.asset = {'id': 'clip', 'org_id': 'org', 'path': 'clip.mp4',
                      'sha256': hashlib.sha256(b'fixture').hexdigest(), 'duration_sec': 8,
                      'width': 1080, 'height': 1920, 'kind': 'video',
                      'tags': {'en': ['steel', 'hinge', 'product']}, 'product_ids': ['product'],
                      'permitted_uses': ['advertising'], 'rights_confirmed': True}

    def tearDown(self): self.tmp.cleanup()

    def catalog(self, assets):
        (self.root / 'catalog.json').write_text(json.dumps({'schema_version': 1, 'assets': assets}), encoding='utf-8')

    def test_catalog_filters_rights_org_product_and_uses(self):
        rejected = []
        for key, value in [('org_id', 'other'), ('product_ids', ['other']),
                           ('rights_confirmed', False), ('permitted_uses', ['internal'])]:
            rejected.append({**self.asset, 'id': key, key: value})
        self.catalog([self.asset, *rejected])
        with patch.dict(os.environ, {'VEA_ASSET_ROOT': str(self.root)}):
            assets = vea.load_assets('org', 'product', 'en', verify_media=False)
        self.assertEqual([a['id'] for a in assets], ['clip'])

    def test_hash_and_path_traversal_rejected(self):
        for mutation in [{'sha256': '0' * 64}, {'path': '../clip.mp4'}]:
            self.catalog([{**self.asset, **mutation}])
            with patch.dict(os.environ, {'VEA_ASSET_ROOT': str(self.root)}):
                with self.assertRaises(vea.VeaError): vea.load_assets('org', 'product', 'en', verify_media=False)

    def test_bm25_requires_match_and_breaks_ties_by_id(self):
        assets = [{**self.asset, 'id': 'b'}, {**self.asset, 'id': 'a'}]
        self.assertEqual(vea.select_matching_broll('steel hinge', 3, assets, 'en')[0]['id'], 'a')
        with self.assertRaises(vea.VeaError): vea.select_matching_broll('unrelated beach', 3, assets, 'en')

    def test_presets_validated_and_timeline_covers_all_speech(self):
        presets = vea.list_presets()
        self.assertEqual(len(presets), 2)
        preset = vea.load_preset('high_velocity_d2c')
        timing = vea.align_words('one two three four five six seven eight nine ten', words('one two three four five six seven eight nine ten', 550), 5600)
        scenes = [{'spoken_narration': 'one two three four five six seven eight nine ten',
                   'visual_broll_cues': 'steel hinge', 'on_screen_text': 'First\n\nLast'}]
        manifest = vea.compile_composition(scenes, [timing], [5.6], [self.asset], preset,
                                           {'revision': 1, 'hex_colors': ['#123456']}, 'en')
        self.assertEqual(manifest['segments'][0]['start_ms'], 0)
        self.assertEqual(manifest['segments'][-1]['end_ms'], 5600)
        self.assertEqual(manifest['scenes'][0]['on_screen_text'], 'First\n\nLast')
        self.assertEqual(vea.content_hash(manifest), vea.content_hash(manifest))

    def test_clip_override_reuses_all_unaffected_choices(self):
        alternate = {**self.asset, 'id': 'alternate'}
        text = 'one two three four five six seven eight nine ten'
        timing = vea.align_words(text, words(text, 550), 5600)
        scene = {'spoken_narration': text, 'visual_broll_cues': 'steel hinge', 'on_screen_text': ''}
        preset = vea.load_preset('high_velocity_d2c'); brand = {'revision': 1, 'hex_colors': []}
        original = vea.compile_composition([scene], [timing], [5.6], [self.asset], preset, brand, 'en')
        replaced = vea.compile_composition([scene], [timing], [5.6], [self.asset, alternate], preset, brand, 'en',
                    [{'segment_id': original['segments'][0]['segment_id'], 'asset_id': 'alternate'}], original)
        self.assertEqual(replaced['segments'][0]['asset_id'], 'alternate')
        self.assertEqual([s['asset_id'] for s in replaced['segments'][1:]], [s['asset_id'] for s in original['segments'][1:]])

    def test_music_provenance_is_bound_to_manifest(self):
        text = 'Good product'
        scene = {'spoken_narration': text, 'visual_broll_cues': 'steel hinge', 'on_screen_text': ''}
        music = {**self.asset, 'id': 'song', 'kind': 'music'}
        manifest = vea.compile_composition([scene], [vea.align_words(text, words(text), 1000)], [1],
                    [self.asset, music], vea.load_preset('high_velocity_d2c'), {'revision': 1, 'hex_colors': []}, 'en')
        self.assertEqual(manifest['music']['asset_id'], 'song')
        self.assertEqual(manifest['music']['asset_sha256'], music['sha256'])

    def test_caption_box_contrast_and_discrete_recipe_motion(self):
        scene = {'spoken_narration': 'Good product', 'visual_broll_cues': 'steel hinge', 'on_screen_text': 'Approved\n\nOverlay'}
        timing = vea.align_words('Good product', words('Good product', 450), 1000)
        for palette, expected_primary, expected_box in [(['#112233'], '&H00000000', '&H00FFFFFF'),
                                                        (['#FFF000'], '&H00FFFFFF', '&H00151515')]:
            manifest = vea.compile_composition([scene], [timing], [1], [self.asset],
                          vea.load_preset('high_velocity_d2c'), {'revision': 1, 'hex_colors': palette}, 'en')
            target = self.root / 'captions.ass'; vea.write_ass(manifest, target)
            ass = target.read_text(encoding='utf-8')
            style = next(line for line in ass.splitlines() if line.startswith('Style: Caption,'))
            self.assertEqual(style.split(',')[3], expected_primary)
            self.assertEqual(style.split(',')[5], expected_box)
            self.assertNotIn('\\fad(', ass)
            self.assertIn('\\fscx104', ass)
            self.assertIn('\\fscx100', ass)


class NarrationTests(unittest.TestCase):
    def test_missing_piper_executable_is_actionable(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / 'voice.onnx'; model.write_bytes(b'model')
            Path(str(model) + '.json').write_text(json.dumps({'language': {'code': 'en_US'}}))
            with patch.dict(os.environ, {'ELEVENLABS_API_KEY': '', 'VEA_PIPER_EXE': 'not-installed-vea-piper',
                    'VEA_PIPER_VOICES': json.dumps({'en': {'model': str(model)}})}):
                with self.assertRaisesRegex(vea.VeaError, 'Install the configured Piper'):
                    vea.synthesize_narration('Approved words', None, 'en', folder)

    def test_unprovisioned_whisper_model_is_actionable_without_download(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / 'voice.mp3'; audio.write_bytes(b'fixture')
            with patch.dict('sys.modules', {'faster_whisper': SimpleNamespace(WhisperModel=lambda *args, **kwargs: (_ for _ in ()).throw(OSError('private/path')))}):
                with self.assertRaisesRegex(vea.VeaError, 'Provision the configured local Whisper'):
                    vea.extract_word_timestamps(audio, 'Approved words', 'en', folder)

    def test_missing_language_voice_mapping_does_not_call_elevenlabs(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                'ELEVENLABS_API_KEY': 'test-key', 'VEA_ELEVENLABS_VOICES': '{}', 'VEA_PIPER_VOICES': '{}'}), patch.object(vea.request, 'urlopen') as network:
            with self.assertRaises(vea.VeaError): vea.synthesize_narration('Exact words', None, 'en', folder)
            network.assert_not_called()

    def test_unsupported_local_language_never_substitutes_voice(self):
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / 'voice.onnx'; model.write_bytes(b'model')
            Path(str(model) + '.json').write_text(json.dumps({'language': {'code': 'en_US'}}))
            with patch.dict(os.environ, {'ELEVENLABS_API_KEY': '', 'VEA_PIPER_VOICES': json.dumps({'uz': {'model': str(model)}})}):
                with self.assertRaisesRegex(vea.VeaError, 'narration_language_mismatch'):
                    vea.synthesize_narration('Mahsulot', '', 'uz', folder)

    def test_missing_provider_and_local_voice_has_actionable_error(self):
        with patch.dict(os.environ, {'ELEVENLABS_API_KEY': '', 'VEA_PIPER_VOICES': '{}'}):
            with self.assertRaisesRegex(vea.VeaError, 'Piper voice for uz'):
                vea.synthesize_narration('Mahsulot', '', 'uz', '.')

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_piper_audio_is_cached_and_reusable_without_provider(self):
        import wave
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / 'voice.onnx'; model.write_bytes(b'model')
            Path(str(model) + '.json').write_text(json.dumps({'language': {'code': 'en_US'}}))
            original = subprocess.run
            def command(args, **kwargs):
                if args[0] != 'fake-piper': return original(args, **kwargs)
                with wave.open(args[args.index('--output_file') + 1], 'wb') as out:
                    out.setnchannels(1); out.setsampwidth(2); out.setframerate(22050); out.writeframes(b'\x00\x00' * 22050)
                return subprocess.CompletedProcess(args, 0)
            environment = {'ELEVENLABS_API_KEY': '', 'VEA_PIPER_EXE': 'fake-piper',
                           'VEA_PIPER_VOICES': json.dumps({'en': {'model': str(model)}})}
            with patch.dict(os.environ, environment), patch.object(vea.subprocess, 'run', side_effect=command):
                result = vea.synthesize_narration('Approved words', '', 'en', folder)
                self.assertTrue(result['fallback_used'])
                reused = vea.reuse_narration(result['cache_key'], 'Approved words', 'en', folder)
                self.assertEqual(result['cache_key'], reused['cache_key'])
                with self.assertRaises(vea.VeaError): vea.reuse_narration(result['cache_key'], 'Different text', 'en', folder)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class RealMediaTests(unittest.TestCase):
    def test_multiple_mp3_scenes_preserve_measured_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            vea.run_media(['-f', 'lavfi', '-i', 'color=c=navy:s=180x320:r=30:d=3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', root/'clip.mp4'])
            vea.run_media(['-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:a', 'libmp3lame', root/'audio.mp3'])
            duration = vea.media_duration(root/'audio.mp3')
            asset = {'id': 'a', 'path': str(root/'clip.mp4'), 'sha256': vea.file_hash(root/'clip.mp4'), 'duration_sec': 3,
                     'tags': {'en': ['product']}}
            scene = {'spoken_narration': 'Good product', 'visual_broll_cues': 'product', 'on_screen_text': ''}
            timing = vea.align_words('Good product', words('Good product', 450), round(duration*1000))
            manifest = vea.compile_composition([scene]*3, [timing]*3, [duration]*3, [asset],
                        vea.load_preset('high_velocity_d2c'), {'revision': 1, 'hex_colors': []}, 'en')
            result = vea.render_video_composition([root/'audio.mp3']*3, manifest, [asset], root)
            self.assertLessEqual(abs(vea.media_duration(result['video']) - manifest['duration_ms']/1000), 1/30)
            self.assertAlmostEqual(vea.media_duration(root/'narration.wav'), manifest['duration_ms']/1000, places=3)

    def test_real_vertical_video_audio_thumbnail_and_caption_escaping(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
                            'color=c=navy:s=180x320:r=30:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(root/'clip.mp4')], check=True)
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
                            'sine=frequency=440:duration=1', '-c:a', 'pcm_s16le', str(root/'audio.wav')], check=True)
            asset = {'id': 'a', 'path': str(root/'clip.mp4'), 'sha256': vea.file_hash(root/'clip.mp4'), 'duration_sec': 1,
                     'tags': {'en': ['product']}}
            scene = {'spoken_narration': 'Good product', 'visual_broll_cues': 'product',
                     'on_screen_text': 'Exact {text} \\ path\n\nSecond line'}
            timing = vea.align_words(scene['spoken_narration'], words('good product', 450), 1000)
            manifest = vea.compile_composition([scene], [timing], [1], [asset],
                        vea.load_preset('high_velocity_d2c'), {'revision': 1, 'hex_colors': ['#123456']}, 'en')
            result = vea.render_video_composition([root/'audio.wav'], manifest, [asset], root)
            info = vea.probe_media(result['video'])
            video = next(s for s in info['streams'] if s['codec_type'] == 'video')
            self.assertEqual((video['width'], video['height'], video['codec_name']), (1080, 1920, 'h264'))
            self.assertTrue(any(s['codec_name'] == 'aac' for s in info['streams']))
            self.assertLessEqual(abs(float(info['format']['duration']) - 1), 1/30)
            self.assertGreater(Path(result['thumbnail']).stat().st_size, 100)


if __name__ == '__main__': unittest.main()
