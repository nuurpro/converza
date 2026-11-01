"""Approved-script deterministic production. No generated scripts or remote stock.

The catalog is a trusted server-managed, read-only input; its tenant, rights,
checksums and paths are nevertheless checked again on every render.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
from urllib import error, request


ROOT = Path(__file__).resolve().parents[2]
PRESET_ROOT = ROOT / 'video_presets'


class VeaError(ValueError):
    def __init__(self, code, message=None):
        self.code = code
        super().__init__(message or code)


def content_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''): digest.update(block)
    return digest.hexdigest()


def normalize_token(value):
    value = unicodedata.normalize('NFKC', value).casefold()
    for apostrophe in '‘’ʻʼ`´': value = value.replace(apostrophe, "'")
    return ''.join(c for c in value if c.isalnum() or c == "'")


def _distance(a, b):
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a):
        current = [i + 1]
        for j, right in enumerate(b):
            current.append(min(current[-1] + 1, previous[j + 1] + 1,
                               previous[j] + (left != right)))
        previous = current
    return previous[-1]


def align_words(approved_text, observed_words, duration_ms):
    """Monotonic fuzzy token alignment with bounded neighbor interpolation.

    Scores use normalized character edit distance as token substitution cost.
    Two observed syllable fragments may jointly anchor one approved token.
    Approved wording is the sole caption source, regardless of ASR spelling.
    """
    tokens = approved_text.split()
    expected = [normalize_token(t) for t in tokens]
    observed = [w for w in observed_words if normalize_token(w['word'])]
    actual = [normalize_token(w['word']) for w in observed]
    if not tokens or not observed or duration_ms <= 0:
        raise VeaError('alignment_invalid', 'Narration has no usable word timestamps')
    last = 0
    for word in observed:
        start, end = word['start_ms'], word['end_ms']
        if not (isinstance(start, int) and isinstance(end, int) and last <= start < end <= duration_ms):
            raise VeaError('alignment_invalid', 'Whisper timestamps overlap or exceed the measured scene')
        last = end
    n, m = len(expected), len(actual)
    costs = [[float('inf')] * (m + 1) for _ in range(n + 1)]
    back = {}
    costs[0][0] = 0
    def offer(i, j, cost, predecessor):
        if cost < costs[i][j] - 1e-10:
            costs[i][j] = cost; back[i, j] = predecessor
    for i in range(n + 1):
        for j in range(m + 1):
            base = costs[i][j]
            if i < n and j < m:
                distance = _distance(expected[i], actual[j]) / max(len(expected[i]), len(actual[j]), 1)
                offer(i + 1, j + 1, base + distance, (i, j, 'match', distance))
                if j + 1 < m:
                    merged = actual[j] + actual[j + 1]
                    merge_distance = _distance(expected[i], merged) / max(len(expected[i]), len(merged), 1)
                    # Only join genuine fragments; unrelated words are normal insertions.
                    if merge_distance < .2:
                        offer(i + 1, j + 2, base + merge_distance, (i, j, 'merge', merge_distance))
            if i < n: offer(i + 1, j, base + 1, (i, j, 'delete', 1))
            if j < m: offer(i, j + 1, base + 1, (i, j, 'insert', 1))
    score = max(0.0, 1 - costs[n][m] / max(n, m))
    anchors = {}
    i, j = n, m
    while i or j:
        pi, pj, action, distance = back[i, j]
        if action in ('match', 'merge') and distance <= .3:
            anchors[pi] = (observed[pj]['start_ms'], observed[j - 1]['end_ms'])
        i, j = pi, pj
    coverage = len(anchors) / n
    if score + 1e-9 < .9 or coverage + 1e-9 < .9:
        raise VeaError('alignment_low_confidence', f'Alignment score {score:.3f}, acoustic coverage {coverage:.3f}; both require 0.90')
    missing = [i for i in range(n) if i not in anchors]
    if len(missing) > n * .1 + 1e-9:
        raise VeaError('alignment_gap_limit')
    result = [None] * n
    for index, (start, end) in anchors.items():
        result[index] = {'word': tokens[index], 'start_ms': start, 'end_ms': end, 'provenance': 'acoustic'}
    index = 0
    while index < n:
        if result[index]: index += 1; continue
        first = index
        while index < n and result[index] is None: index += 1
        count = index - first
        if count > 2: raise VeaError('alignment_gap_limit', 'More than two consecutive tokens lack acoustic anchors')
        left = result[first - 1]['end_ms'] if first else 0
        right = result[index]['start_ms'] if index < n else duration_ms
        if right - left < count:
            raise VeaError('alignment_invalid', 'No positive neighbor interval for missing tokens')
        for k in range(count):
            result[first + k] = {'word': tokens[first + k],
                'start_ms': left + round((right - left) * k / count),
                'end_ms': left + round((right - left) * (k + 1) / count), 'provenance': 'interpolated'}
    phrases, phrase = [], []
    for word in result:
        phrase.append(word)
        if len(phrase) == 5 or re.search(r'[.!?。！？]$', word['word']):
            phrases.append({'text': ' '.join(w['word'] for w in phrase), 'start_ms': phrase[0]['start_ms'], 'end_ms': phrase[-1]['end_ms']}); phrase = []
    if phrase: phrases.append({'text': ' '.join(w['word'] for w in phrase), 'start_ms': phrase[0]['start_ms'], 'end_ms': phrase[-1]['end_ms']})
    return {'words': result, 'phrases': phrases, 'alignment_score': score,
            'anchor_coverage': coverage, 'interpolated_token_indices': missing, 'duration_ms': duration_ms}


def extract_word_timestamps(audio_path, approved_text, language, cache_dir):
    key = content_hash({'audio': file_hash(audio_path), 'text': approved_text,
                        'language': language, 'model': os.getenv('VEA_WHISPER_MODEL', 'small'),
                        'alignment_version': 1})
    cached = Path(cache_dir) / (key + '.alignment.json')
    if cached.exists(): return json.loads(cached.read_text(encoding='utf-8'))
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise VeaError('alignment_unavailable', 'Install faster-whisper and provision VEA_WHISPER_MODEL') from exc
    try:
        model = WhisperModel(os.getenv('VEA_WHISPER_MODEL', 'small'), device=os.getenv('VEA_WHISPER_DEVICE', 'cpu'),
                             compute_type=os.getenv('VEA_WHISPER_COMPUTE_TYPE', 'int8'), local_files_only=True)
    except (OSError, ValueError, RuntimeError) as exc:
        raise VeaError('alignment_unavailable', 'Provision the configured local Whisper model before rendering') from exc
    try:
        segments, _ = model.transcribe(str(audio_path), language=language, word_timestamps=True, vad_filter=False)
        observed = [{'word': word.word, 'start_ms': round(word.start * 1000), 'end_ms': round(word.end * 1000)}
                    for segment in segments for word in (segment.words or [])]
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        raise VeaError('alignment_unavailable', 'Whisper could not align this narration; verify the local model, language and audio') from exc
    aligned = align_words(approved_text, observed, round(media_duration(audio_path) * 1000))
    atomic_json(cached, aligned)
    return aligned


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True); temporary = Path(handle.name)
    temporary.replace(path)


def run_media(args, cwd=None):
    try:
        result = subprocess.run([os.getenv('VEA_FFMPEG', 'ffmpeg'), '-hide_banner', '-loglevel', 'error', '-y', *map(str, args)],
                                cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VeaError('render_failed', 'Install FFmpeg and verify renderer resource limits') from exc
    if result.returncode:
        raise VeaError('render_failed', result.stderr.decode('utf-8', errors='replace')[-1200:])


def probe_media(path):
    try:
        result = subprocess.run([os.getenv('VEA_FFPROBE', 'ffprobe'), '-v', 'error', '-show_format', '-show_streams',
                                 '-of', 'json', str(path)], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VeaError('invalid_media', 'Install ffprobe and verify the asset media') from exc
    if result.returncode: raise VeaError('invalid_media', 'Asset cannot be inspected by ffprobe')
    return json.loads(result.stdout)


def media_duration(path):
    return float(probe_media(path)['format']['duration'])


def load_preset(preset_id):
    if not re.fullmatch(r'[a-z0-9_]+', preset_id): raise VeaError('invalid_preset')
    path = PRESET_ROOT / ('preset_' + preset_id + '.json')
    if not path.is_file(): raise VeaError('invalid_preset')
    preset = json.loads(path.read_text(encoding='utf-8'))
    if (preset['schema_version'] != 1 or preset['id'] != preset_id or preset['width'] != 1080 or
            preset['height'] != 1920 or preset['fps'] != 30 or
            not 0 < preset['cuts']['min_sec'] <= preset['cuts']['max_sec'] <= 3.5 or
            preset['graphics_fps'] != 12 or preset['audio']['speech_music_db'] != -18):
        raise VeaError('invalid_preset', 'Unsupported recipe settings')
    return preset


def list_presets():
    return [{'id': p['id'], 'name': p['name'], 'version': p['version'], 'sha256': content_hash(p),
             'width': p['width'], 'height': p['height'], 'fps': p['fps'], 'cuts': p['cuts']}
            for p in (load_preset(f.stem.removeprefix('preset_')) for f in sorted(PRESET_ROOT.glob('*.json')))]


def safe_crop(asset, width=1080, height=1920):
    """Describe a centered, non-stretched crop; reject unusable source geometry."""
    w, h = asset.get('width'), asset.get('height')
    if any(type(v) is not int or not 2 <= v <= 16384 for v in (w, h)):
        raise VeaError('invalid_media', 'Clip dimensions must be valid positive pixel dimensions')
    crop_w, crop_h = min(w, h * width / height), min(h, w * height / width)
    if min(crop_w, crop_h) < 2:
        raise VeaError('invalid_media', 'Clip cannot be safely cropped to the recipe aspect ratio')
    return {'mode': 'center_crop_no_stretch', 'source_width': w, 'source_height': h,
            'x': (w-crop_w)/2, 'y': (h-crop_h)/2, 'width': crop_w, 'height': crop_h}


def _scoped_asset(asset, product_id):
    products = asset.get('product_ids', [])
    # Music is a tenant-owned soundtrack, not initiative/product B-roll.
    return asset.get('kind') == 'music' or (product_id in products if product_id else not products)


def load_assets(org_id, product_id=None, language='en', verify_media=True, selection='automatic'):
    if selection not in ('automatic', 'manual'): raise VeaError('invalid_selection_mode')
    root_value = os.getenv('VEA_ASSET_ROOT', '')
    if not root_value: raise VeaError('asset_catalog_unavailable', 'Configure a read-only VEA_ASSET_ROOT with catalog.json')
    root = Path(root_value).resolve()
    try: catalog = json.loads((root / 'catalog.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc: raise VeaError('asset_catalog_unavailable') from exc
    if catalog.get('schema_version') != 1: raise VeaError('invalid_asset_catalog')
    eligible, ids = [], set()
    for item in catalog.get('assets', []):
        if item.get('org_id') != org_id: continue
        uses = item.get('permitted_uses')
        if item.get('rights_confirmed') is not True or not isinstance(uses, list) or 'advertising' not in uses: continue
        products = item.get('product_ids', [])
        if not isinstance(products, list) or any(not isinstance(p, str) for p in products):
            raise VeaError('invalid_asset_catalog')
        if selection == 'automatic' and not _scoped_asset(item, product_id): continue
        if not isinstance(item.get('id'), str) or item['id'] in ids: raise VeaError('invalid_asset_catalog')
        ids.add(item['id'])
        relative = Path(item.get('path', ''))
        path = (root / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(root) or not path.is_file():
            raise VeaError('unsafe_asset_path')
        if not re.fullmatch('[a-f0-9]{64}', item.get('sha256', '')) or file_hash(path) != item['sha256']:
            raise VeaError('asset_checksum_mismatch', f'Asset {item["id"]} differs from its catalog checksum')
        if type(item.get('duration_sec')) not in (float, int) or not math.isfinite(item['duration_sec']) or item['duration_sec'] <= 0:
            raise VeaError('invalid_asset_catalog')
        if item.get('kind') not in ('video', 'music'): raise VeaError('invalid_asset_catalog')
        if item['kind'] == 'video': safe_crop(item)
        if not isinstance(item.get('tags'), dict): raise VeaError('invalid_asset_catalog')
        if verify_media:
            info = probe_media(path)
            wanted = 'audio' if item['kind'] == 'music' else 'video'
            streams = [s for s in info['streams'] if s['codec_type'] == wanted]
            if not streams or abs(float(info['format']['duration']) - item['duration_sec']) > .1:
                raise VeaError('asset_metadata_mismatch', f'Asset {item["id"]} duration/type does not match catalog')
            if wanted == 'video' and (streams[0]['width'] != item.get('width') or streams[0]['height'] != item.get('height')):
                raise VeaError('asset_metadata_mismatch')
            if wanted == 'video' and streams[0].get('sample_aspect_ratio', '1:1') not in ('1:1', '0:1', 'N/A'):
                raise VeaError('invalid_media', 'Normalize non-square pixels before adding this clip to the vault')
            if wanted == 'video' and (streams[0].get('tags', {}).get('rotate', '0') not in ('0', 0) or
                    any(s.get('rotation', 0) != 0 for s in streams[0].get('side_data_list', []))):
                raise VeaError('invalid_media', 'Normalize clip rotation before adding it to the vault')
        eligible.append({**item, 'path': str(path)})
    return sorted(eligible, key=lambda a: a['id'])


def public_assets(assets):
    fields = ('id', 'org_id', 'sha256', 'duration_sec', 'width', 'height', 'kind', 'tags',
              'product_ids', 'rights_confirmed', 'permitted_uses')
    return [{k: a[k] for k in fields if k in a} for a in assets]


def _tag_tokens(asset, language):
    values = asset.get('tags', {}).get(language, []) + asset.get('tags', {}).get('und', [])
    return [normalize_token(t) for v in values for t in v.split() if normalize_token(t)]


def select_matching_broll(visual_cues, duration, assets, language):
    candidates = [a for a in assets if a.get('kind', 'video') == 'video' and a['duration_sec'] + .0001 >= duration]
    documents = [_tag_tokens(a, language) for a in candidates]
    query = sorted(set(normalize_token(t) for t in visual_cues.split()) - {''})
    average = sum(map(len, documents)) / max(len(documents), 1)
    scores = []
    for asset, tokens in zip(candidates, documents):
        score = 0.0
        for token in query:
            frequency = tokens.count(token)
            if not frequency: continue
            df = sum(token in doc for doc in documents)
            idf = math.log(1 + (len(documents) - df + .5) / (df + .5))
            score += idf * frequency * 2.2 / (frequency + 1.2 * (.25 + .75 * len(tokens) / max(average, 1)))
        if score > 0: scores.append((score, asset))
    if not scores: raise VeaError('missing_assets', 'No rights-cleared matching clip is long enough; seed relevant catalog assets')
    return [{**a, 'selection_score': round(s, 8)} for s, a in sorted(scores, key=lambda pair: (-pair[0], pair[1]['id']))]


def _language(value):
    code = (value or 'en').lower().split('-')[0].split('_')[0]
    return {'english': 'en', 'russian': 'ru', 'uzbek': 'uz'}.get(code, code)


def _remember_narration(result, text, language, cache_dir):
    metadata = {k: v for k, v in result.items() if k != 'path'}
    metadata.update(text_sha256=content_hash(text), language=language, audio_sha256=file_hash(result['path']))
    atomic_json(Path(cache_dir) / (result['cache_key'] + '.speech.json'), metadata)
    return result


def reuse_narration(cache_key, text, language, cache_dir):
    if not re.fullmatch('[a-f0-9]{64}', cache_key): raise VeaError('narration_cache_invalid')
    try:
        metadata = json.loads((Path(cache_dir) / (cache_key + '.speech.json')).read_text(encoding='utf-8'))
        audio = Path(cache_dir) / (cache_key + '.mp3')
        if (metadata['text_sha256'] != content_hash(text) or metadata['language'] != language or
                metadata['audio_sha256'] != file_hash(audio)):
            raise VeaError('narration_cache_invalid')
    except (OSError, ValueError, KeyError) as exc:
        raise VeaError('narration_cache_invalid', 'Cached narration is unavailable; retry a new variant from the approved script') from exc
    return {'path': audio, **{k: metadata[k] for k in ('cache_key', 'provider', 'fallback_used', 'fallback_reason') if k in metadata}}


def synthesize_narration(script_text, voice_id, language, cache_dir):
    language = _language(language)
    voices = json.loads(os.getenv('VEA_ELEVENLABS_VOICES', '{}'))
    voice_id = voices.get(language) or voice_id
    settings = {'stability': .5, 'similarity_boost': .75, 'style': 0, 'use_speaker_boost': True}
    primary_error = None
    if os.getenv('ELEVENLABS_API_KEY') and voice_id:
        key = content_hash({'text': script_text, 'language': language, 'provider': 'elevenlabs',
                            'model': 'eleven_v3', 'voice': voice_id, 'settings': settings})
        target = Path(cache_dir) / (key + '.mp3')
        if target.exists():
            return _remember_narration({'path': target, 'cache_key': key, 'provider': 'elevenlabs', 'fallback_used': False}, script_text, language, cache_dir)
        payload = json.dumps({'text': script_text, 'model_id': 'eleven_v3', 'language_code': language,
                              'voice_settings': settings}).encode('utf-8')
        # Voice IDs are identifiers, never caller-provided URLs.
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', voice_id): raise VeaError('invalid_voice')
        req = request.Request('https://api.elevenlabs.io/v1/text-to-speech/' + voice_id + '?output_format=mp3_44100_128',
                              data=payload, headers={'xi-api-key': os.environ['ELEVENLABS_API_KEY'],
                                                    'Content-Type': 'application/json', 'Accept': 'audio/mpeg'})
        try:
            with request.urlopen(req, timeout=120) as response: audio = response.read()
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=cache_dir, suffix='.mp3', delete=False) as handle:
                handle.write(audio); temporary = Path(handle.name)
            if media_duration(temporary) <= 0: raise VeaError('narration_invalid')
            temporary.replace(target)
            return _remember_narration({'path': target, 'cache_key': key, 'provider': 'elevenlabs', 'fallback_used': False}, script_text, language, cache_dir)
        except (error.URLError, OSError, VeaError) as exc: primary_error = type(exc).__name__
    else: primary_error = 'primary_voice_not_configured'
    local = json.loads(os.getenv('VEA_PIPER_VOICES', '{}')).get(language)
    if not local or not Path(local['model']).is_file():
        raise VeaError('narration_unavailable', f'Configure ElevenLabs or install a Piper voice for {language}')
    model = Path(local['model']).resolve()
    configuration = Path(local.get('config', str(model) + '.json'))
    try: metadata = json.loads(configuration.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc: raise VeaError('narration_unavailable', 'Piper voice configuration is missing') from exc
    if _language(metadata.get('language', {}).get('code', '')) != language:
        raise VeaError('narration_language_mismatch')
    key = content_hash({'text': script_text, 'language': language, 'provider': 'piper',
                        'voice': file_hash(model), 'settings': metadata})
    target = Path(cache_dir) / (key + '.mp3')
    if not target.exists():
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache_dir) as folder:
            wav = Path(folder) / 'speech.wav'
            try:
                result = subprocess.run([os.getenv('VEA_PIPER_EXE', 'piper'), '--model', str(model),
                                         '--config', str(configuration), '--output_file', str(wav)],
                                        input=script_text.encode('utf-8'), capture_output=True, timeout=120)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise VeaError('narration_unavailable', 'Install the configured Piper executable and verify its voice model and resource limits') from exc
            if result.returncode or not wav.exists(): raise VeaError('narration_unavailable', 'Piper failed to synthesize the configured language')
            encoded = Path(folder) / 'speech.mp3'
            run_media(['-i', wav, '-c:a', 'libmp3lame', '-b:a', '192k', encoded])
            encoded.replace(target)
    return _remember_narration({'path': target, 'cache_key': key, 'provider': 'piper', 'fallback_used': True,
                                'fallback_reason': primary_error}, script_text, language, cache_dir)


def compile_composition(scenes, timings, durations, assets, preset, brand, language, clip_overrides=None, reuse_manifest=None, product_id=None):
    segments, global_words, scene_entries = [], [], []
    offset = 0
    overrides = {o['segment_id']: o['asset_id'] for o in (clip_overrides or [])}
    used = set()
    old = {s['segment_id']: s for s in (reuse_manifest or {}).get('segments', [])}
    for scene_index, (scene, timing, duration) in enumerate(zip(scenes, timings, durations)):
        duration_ms = round(duration * 1000)
        scene_entries.append({'index': scene_index, 'start_ms': offset, 'end_ms': offset + duration_ms,
                              'on_screen_text': scene['on_screen_text'], 'spoken_narration': scene['spoken_narration']})
        global_words.extend({**w, 'start_ms': offset + w['start_ms'], 'end_ms': offset + w['end_ms'], 'scene_index': scene_index}
                            for w in timing['words'])
        cut_start, cut_index = 0, 0
        minimum, maximum = [round(preset['cuts'][key] * 1000) for key in ('min_sec', 'max_sec')]
        while cut_start < duration_ms:
            if duration_ms - cut_start <= maximum: cut_end = duration_ms
            else:
                ends = [w['end_ms'] for w in timing['words'] if cut_start + minimum <= w['end_ms'] <= cut_start + maximum]
                cut_end = min(ends, key=lambda e: (abs(e - cut_start - (minimum + maximum) / 2), e)) if ends else cut_start + round((minimum + maximum) / 2)
            segment_id = f'scene-{scene_index + 1}-clip-{cut_index + 1}'
            requested = overrides.get(segment_id) or old.get(segment_id, {}).get('asset_id')
            manual = segment_id in overrides
            if manual:
                # Only the bound config's persisted overrides authorize relevance bypass.
                # A flag in a reused manifest is never an authorization source.
                matching = []
                selected = next((a for a in assets if a['id'] == requested and a.get('kind') == 'video'), None)
                if selected is None: raise VeaError('invalid_clip_override', 'Operator-selected footage is no longer eligible')
                safe_crop(selected, preset['width'], preset['height'])
            else:
                scoped = [a for a in assets if product_id is None or _scoped_asset(a, product_id)]
                matching = select_matching_broll(scene['visual_broll_cues'], (cut_end - cut_start) / 1000, scoped, language)
                selected = next((a for a in matching if a['id'] == requested), None) if requested else matching[0]
                if selected is None: raise VeaError('missing_assets', f'No matching initiative footage for {segment_id}; add rights-cleared initiative clips or select a manual replacement')
            if segment_id in overrides: used.add(segment_id)
            source_start = old.get(segment_id, {}).get('source_start_ms', 0) if requested and segment_id not in overrides else 0
            if source_start < 0 or source_start + cut_end - cut_start > selected['duration_sec'] * 1000 + 1:
                raise VeaError('invalid_clip_override')
            segments.append({'segment_id': segment_id, 'scene_index': scene_index, 'asset_id': selected['id'],
                             'asset_sha256': selected['sha256'], 'start_ms': offset + cut_start, 'end_ms': offset + cut_end,
                             'source_start_ms': source_start, 'source_end_ms': source_start + cut_end - cut_start,
                             'selection_mode': 'manual' if manual else 'automatic',
                             **({'crop': safe_crop(selected, preset['width'], preset['height'])} if manual else {}),
                             'selection_score': selected.get('selection_score', 0), 'alternatives': [a['id'] for a in matching[:8]]})
            cut_start, cut_index = cut_end, cut_index + 1
        offset += duration_ms
    if used != set(overrides): raise VeaError('invalid_clip_override', 'Timeline segment does not exist')
    music = next((a for a in sorted(assets, key=lambda a: a['id']) if a.get('kind') == 'music'), None)
    reused_music = (reuse_manifest or {}).get('music')
    if reuse_manifest and reused_music:
        music = next((a for a in assets if a['id'] == reused_music['asset_id'] and a.get('kind') == 'music'
                      and a['sha256'] == reused_music['asset_sha256']), None)
        if music is None: raise VeaError('missing_assets', 'Previously selected music is no longer eligible; create a new variant')
    elif reuse_manifest:
        # Swapping a clip must not introduce a newly seeded soundtrack.
        music = None
    return {'schema_version': 1, 'preset': preset, 'preset_sha256': content_hash(preset),
            'brand_snapshot': brand, 'language': language, 'duration_ms': offset,
            'scenes': scene_entries, 'words': global_words, 'segments': segments,
            'music': {'asset_id': music['id'], 'asset_sha256': music['sha256']} if music else None}


def _ass_escape(text):
    # ASS commands in approved text must render literally, never execute tags.
    return text.replace('\\', '\\\u2060').replace('{', '\\{').replace('}', '\\}').replace('\r\n', '\n').replace('\n', '\\N')


def _ass_time(ms):
    centis = max(0, round(ms / 10)); hours, rest = divmod(centis, 360000)
    minutes, rest = divmod(rest, 6000); seconds, fraction = divmod(rest, 100)
    return f'{hours}:{minutes:02}:{seconds:02}.{fraction:02}'


def write_ass(manifest, target):
    preset = manifest['preset']; captions = preset['captions']
    palette = manifest.get('brand_snapshot', {}).get('hex_colors', [])
    color = next((c for c in palette if re.fullmatch('#[a-fA-F0-9]{6}', c)), '#FFFFFF')
    rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    luminance = sum(weight * (v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4)
                    for weight, v in zip((.2126, .7152, .0722), rgb))
    background = '&H00151515' if luminance > .179 else '&H00FFFFFF'
    primary = '&H00FFFFFF' if luminance > .179 else '&H00000000'
    ass_color = '&H00' + color[5:7] + color[3:5] + color[1:3]
    header = ('[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n'
              '[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
              f'Style: Caption,{captions["font"]},{captions["font_size"]},{primary},{ass_color},{background},{background},1,0,0,0,100,100,0,0,3,12,0,2,90,90,{captions["bottom_margin"]},1\n'
              'Style: Overlay,DejaVu Sans,58,&H00FFFFFF,&H00FFFFFF,&H00151515,&H90151515,1,0,0,0,100,100,0,0,3,10,0,8,90,90,230,1\n'
              '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n')
    lines = [header]
    for scene in manifest['scenes']:
        if scene['on_screen_text']:
            lines.append(f'Dialogue: 0,{_ass_time(scene["start_ms"])},{_ass_time(scene["end_ms"])},Overlay,,0,0,0,,{_ass_escape(scene["on_screen_text"])}\n')
    words = manifest['words']
    # Stable phrase group, active word highlighted at each measured boundary.
    for index, word in enumerate(words):
        scene_words = [w for w in words if w['scene_index'] == word['scene_index']]
        count = captions['words_per_phrase']
        local = scene_words.index(word); group = scene_words[(local // count) * count:(local // count + 1) * count]
        # Discrete graphic states change once per 12fps tick, while source
        # footage remains 30fps and word boundaries retain acoustic timing.
        tick = round(1000 / preset['graphics_fps'])
        split = min(word['start_ms'] + tick, word['end_ms'])
        intervals = [(word['start_ms'], split, True)]
        if split < word['end_ms']: intervals.append((split, word['end_ms'], False))
        for begin, end, entrance in intervals:
            scale = 104 if entrance and captions['animation'] == 'word_highlight_pop' else 100
            alpha = '&H40&' if entrance and captions['animation'] == 'word_highlight_fade' else '&H00&'
            body = ' '.join((f'{{\\c{ass_color}&\\fscx{scale}\\fscy{scale}\\alpha{alpha}}}' + _ass_escape(w['word']) + '{\\rCaption}')
                            if w is word else _ass_escape(w['word']) for w in group)
            lines.append(f'Dialogue: 1,{_ass_time(begin)},{_ass_time(end)},Caption,,0,0,0,,{body}\n')
    Path(target).write_text(''.join(lines), encoding='utf-8')


def render_video_composition(audio_paths, manifest, assets, output_dir):
    output_dir = Path(output_dir).resolve(); output_dir.mkdir(parents=True, exist_ok=True)
    lookup = {a['id']: a for a in assets}; recipe = manifest['preset']
    clips = []
    for index, segment in enumerate(manifest['segments']):
        asset = lookup[segment['asset_id']]
        if file_hash(asset['path']) != segment['asset_sha256']:
            raise VeaError('asset_checksum_mismatch')
        destination = output_dir / f'clip-{index}.mp4'
        duration = (segment['end_ms'] - segment['start_ms']) / 1000
        grade = recipe['grade']
        filters = (f'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30,'
                   f'eq=contrast={grade["contrast"]}:saturation={grade["saturation"]}:brightness={grade["brightness"]}')
        if grade['grain_strength']:
            filters += f',noise=alls={grade["grain_strength"]}:allf=t:all_seed={grade["grain_seed"]}'
        run_media(['-ss', segment['source_start_ms'] / 1000, '-i', asset['path'], '-t', duration,
                   '-an', '-vf', filters, '-c:v', 'libx264', '-preset', os.getenv('VEA_X264_PRESET', 'veryfast'),
                   '-crf', '20', '-pix_fmt', 'yuv420p', '-threads', '2', destination])
        clips.append(destination)
    # Generated safe local names avoid concat-file quoting/path injection.
    (output_dir / 'clips.txt').write_text(''.join(f"file 'clip-{i}.mp4'\n" for i in range(len(clips))), encoding='utf-8')
    run_media(['-f', 'concat', '-safe', '1', '-i', 'clips.txt', '-c', 'copy', 'combined.mp4'], cwd=output_dir)
    normalized = []
    for i, audio in enumerate(audio_paths):
        target = output_dir / f'voice-{i}.wav'
        scene = manifest['scenes'][i]
        scene_duration = (scene['end_ms'] - scene['start_ms']) / 1000
        run_media(['-i', Path(audio).resolve(), '-af', f'loudnorm=I=-16:TP=-1.5:LRA=11,apad,atrim=duration={scene_duration},asetpts=PTS-STARTPTS',
                   '-ar', '48000', '-ac', '2', target])
        normalized.append(target)
    (output_dir / 'voices.txt').write_text(''.join(f"file 'voice-{i}.wav'\n" for i in range(len(normalized))), encoding='utf-8')
    run_media(['-f', 'concat', '-safe', '1', '-i', 'voices.txt', '-c:a', 'pcm_s16le', 'narration.wav'], cwd=output_dir)
    write_ass(manifest, output_dir / 'captions.ass')
    duration = manifest['duration_ms'] / 1000
    arguments = ['-i', 'combined.mp4', '-i', 'narration.wav']
    music_ref = manifest.get('music')
    music = lookup.get(music_ref['asset_id']) if music_ref else None
    if music_ref and (music is None or file_hash(music['path']) != music_ref['asset_sha256']):
        raise VeaError('asset_checksum_mismatch')
    if music:
        arguments += ['-stream_loop', '-1', '-i', music['path'], '-filter_complex',
                      '[1:a]anull[voice];[2:a]loudnorm=I=-16:TP=-1.5:LRA=11,volume=-18dB[music];'
                      '[voice][music]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:latency=1[audio]', '-map', '0:v', '-map', '[audio]']
    else: arguments += ['-map', '0:v', '-map', '1:a', '-af', 'alimiter=limit=0.95:latency=1']
    arguments += ['-vf', 'ass=captions.ass', '-t', duration, '-c:v', 'libx264', '-preset', os.getenv('VEA_X264_PRESET', 'veryfast'),
                  '-crf', '20', '-pix_fmt', 'yuv420p', '-r', '30', '-threads', '2', '-c:a', 'aac', '-ar', '48000',
                  '-b:a', '192k', '-movflags', '+faststart', 'final-1.mp4']
    run_media(arguments, cwd=output_dir)
    run_media(['-i', 'final-1.mp4', '-frames:v', '1', '-update', '1', 'final-1.jpg'], cwd=output_dir)
    return {'video': str(output_dir / 'final-1.mp4'), 'thumbnail': str(output_dir / 'final-1.jpg')}


def start_render(task_id, params, output_dir, cache_root, progress=None):
    config = params.vea_config.model_dump(mode='json')
    binding = params.milo_binding
    language = _language(params.video_language)
    stage_times, start = {}, time.monotonic()
    preset = load_preset(config['preset_id'])
    if ((config.get('preset_version') is not None and config['preset_version'] != preset['version']) or
            (config.get('preset_sha256') is not None and config['preset_sha256'] != content_hash(preset))):
        raise VeaError('preset_changed', 'Pinned recipe is unavailable; create a new variant with the current recipe')
    reused = config.get('reuse_manifest')
    if reused and (reused.get('preset_sha256') != content_hash(preset) or reused.get('preset') != preset):
        raise VeaError('preset_changed', 'Clip swaps require the original recipe; create a new variant after recipe changes')
    assets = load_assets(binding.org_id, config.get('product_id'), language,
                         selection='manual' if config.get('clip_overrides') else 'automatic')
    if not config.get('clip_overrides') and not any(a['kind'] == 'video' for a in assets):
        raise VeaError('missing_assets', 'Add rights-cleared footage explicitly assigned to the selected initiative before rendering')
    stage_times['assets_sec'] = round(time.monotonic() - start, 3)
    if progress: progress(15)
    # Per-organization caches prevent cross-tenant narration sharing.
    cache_dir = Path(cache_root) / content_hash({'org_id': binding.org_id})
    cache_dir.mkdir(parents=True, exist_ok=True)
    scenes = [s.model_dump() for s in params.approved_scenes]
    audio, timings, durations = [], [], []
    reuse_keys = (config.get('reuse_manifest') or {}).get('narration_cache_keys', [])
    if reuse_keys and len(reuse_keys) != len(scenes): raise VeaError('narration_cache_invalid')
    for index, scene in enumerate(scenes):
        speech = (reuse_narration(reuse_keys[index], scene['spoken_narration'], language, cache_dir) if reuse_keys else
                  synthesize_narration(scene['spoken_narration'], None, language, cache_dir))
        audio.append(speech)
        durations.append(media_duration(speech['path']))
        timings.append(extract_word_timestamps(speech['path'], scene['spoken_narration'], language, cache_dir))
    stage_times['narration_alignment_sec'] = round(time.monotonic() - start - stage_times['assets_sec'], 3)
    if progress: progress(40)
    manifest = compile_composition(scenes, timings, durations, assets, preset, config['brand_snapshot'], language,
                                   config.get('clip_overrides'), config.get('reuse_manifest'), product_id=config.get('product_id'))
    manifest['org_id'] = binding.org_id
    manifest['script_sha256'] = binding.script_sha256
    manifest['narration_cache_keys'] = [s['cache_key'] for s in audio]
    manifest['vea_config_sha256'] = binding.vea_config_sha256
    composition_hash = content_hash(manifest)
    atomic_json(Path(output_dir) / 'composition.json', manifest)
    render_started = time.monotonic()
    outputs = render_video_composition([s['path'] for s in audio], manifest, assets, output_dir)
    stage_times['render_sec'] = round(time.monotonic() - render_started, 3)
    info = probe_media(outputs['video'])
    measured = float(info['format']['duration'])
    if abs(measured - manifest['duration_ms'] / 1000) > 1 / 30 + .001:
        raise VeaError('render_duration_mismatch')
    endpoint = os.getenv('VEA_PUBLIC_ENDPOINT', '').rstrip('/')
    prefix = endpoint + f'/tasks/{task_id}/'
    artifact = {'schema_version': 1, 'id': config['variant_id'],
        'variant_revision': config['variant_revision'], 'video_url': prefix + 'final-1.mp4',
        'thumbnail_url': prefix + 'final-1.jpg', 'duration_sec': measured,
        'preset_used': preset['id'], 'preset_version': preset['version'], 'preset_sha256': content_hash(preset),
        'source_milo_script_id': binding.campaign_id, 'approved_script_revision': binding.script_revision,
        'composition_sha256': composition_hash,
        'render_telemetry': {'stage_durations': stage_times, 'total_sec': round(time.monotonic() - start, 3),
            'alignment': [{k: t[k] for k in ('alignment_score', 'anchor_coverage', 'interpolated_token_indices')} for t in timings],
            'narration': [{k: v for k, v in a.items() if k != 'path'} for a in audio],
            'assets': [{'id': s['asset_id'], 'sha256': s['asset_sha256']} for s in manifest['segments']] +
                      ([{'id': manifest['music']['asset_id'], 'sha256': manifest['music']['asset_sha256']}] if manifest['music'] else []),
            'preset_sha256': content_hash(preset), 'vea_config_sha256': binding.vea_config_sha256,
            'composition_sha256': composition_hash, 'provider_attempt': binding.provider_attempt,
            'media': {'width': 1080, 'height': 1920, 'fps': 30, 'video_codec': 'h264', 'audio_codec': 'aac'},
            'failure_code': None}}
    return {'videos': [outputs['video']], 'vea_artifact': artifact, 'composition_manifest': manifest,
            'milo_binding': binding.model_dump()}
