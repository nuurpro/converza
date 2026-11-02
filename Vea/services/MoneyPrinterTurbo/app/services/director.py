"""Durable, tenant-bound director jobs and local measured inspection evidence.

Only server-managed catalog assets and locally provisioned speech/OCR models are
used. A failed inspection is a terminal receipt; retry is a new attempt.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
from contextlib import contextmanager
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from app.services import vea


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Visual(Strict):
    prompt: str = Field(min_length=1, max_length=4000)
    subject_action: str = Field(min_length=1, max_length=1000)
    camera_movement: str = Field(min_length=1, max_length=500)
    lighting_style: str = Field(min_length=1, max_length=500)


class Constraints(Strict):
    required_sku_tags: list[str] = Field(max_length=30)
    brand_hex_palette: list[str] = Field(max_length=12)
    negative_visual_constraints: list[str] = Field(max_length=100)

    @model_validator(mode='after')
    def colors(self):
        import re
        if any(not re.fullmatch(r'#[a-fA-F0-9]{6}', c) for c in self.brand_hex_palette):
            raise ValueError('Invalid brand palette')
        if any(not c.strip() for c in self.required_sku_tags + self.negative_visual_constraints):
            raise ValueError('Asset constraints cannot contain blank values')
        return self


class Overlay(Strict):
    text: str = Field(max_length=500)
    font_family: str = Field(min_length=1, max_length=100, pattern=r'^[\w .-]+$')
    font_size: StrictInt = Field(ge=16, le=160)
    color: str = Field(pattern=r'^#[a-fA-F0-9]{6}$')
    position: Literal['top', 'center', 'bottom']
    animation: Literal['none', 'fade', 'slide']
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)


class Scene(Strict):
    scene_index: StrictInt = Field(ge=1, le=12)
    total_scenes: StrictInt = Field(ge=1, le=12)
    target_duration_sec: float = Field(gt=0, le=120)
    narration_chunk: str = Field(min_length=1, max_length=1500, pattern=r'\S')
    visual_directive: Visual
    asset_constraints: Constraints
    overlay_text: Overlay

    @model_validator(mode='after')
    def bounds(self):
        if self.scene_index > self.total_scenes or not self.overlay_text.start_sec < self.overlay_text.end_sec <= self.target_duration_sec:
            raise ValueError('Scene index or overlay interval outside scene')
        return self


class RendererContext(Strict):
    asset_catalog_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    renderer_config_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class Envelope(Strict):
    org_id: str = Field(min_length=1, max_length=200)
    run_id: str = Field(min_length=1, max_length=200)
    campaign_id: str = Field(min_length=1, max_length=200)
    storyboard_revision: StrictInt = Field(ge=1)
    attempt: StrictInt = Field(ge=1, le=3)
    spec_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    idempotency_key: str = Field(min_length=1, max_length=200)
    correction_notes: list[str] = Field(default_factory=list, max_length=32)
    expected_context: RendererContext | None = None


class SceneRequest(Envelope):
    scene: Scene
    language: Literal['en', 'ru', 'uz'] = 'en'
    product_id: str | None = None

    @model_validator(mode='before')
    @classmethod
    def digest(cls, data):
        if isinstance(data, dict) and vea.content_hash(data.get('scene')) != data.get('spec_sha256'):
            raise ValueError('Scene specification hash mismatch')
        return data


class SceneToken(Strict):
    scene_index: StrictInt = Field(ge=1, le=12)
    task_id: str
    artifact_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    verified_token: str = Field(min_length=1)


class Manifest(Strict):
    schema_version: Literal[1] = 1
    storyboard_revision: StrictInt = Field(ge=1)
    scenes: list[SceneToken] = Field(min_length=1, max_length=12)
    target_duration_sec: float = Field(gt=0, le=1440)
    transitions: list[Literal['cut', 'crossfade']] = []
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    format: Literal['mp4'] = 'mp4'
    audio_ducking_db: float = Field(le=-12, ge=-60, default=-18)
    background_asset_id: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode='after')
    def order(self):
        if [s.scene_index for s in self.scenes] != list(range(1, len(self.scenes) + 1)):
            raise ValueError('Scene tokens must be complete and ordered')
        if self.transitions and len(self.transitions) != len(self.scenes) - 1:
            raise ValueError('One transition required per scene boundary')
        return self


class MasterRequest(Envelope):
    manifest: Manifest

    @model_validator(mode='before')
    @classmethod
    def digest(cls, data):
        if not isinstance(data, dict): return data
        if data.get('manifest', {}).get('storyboard_revision') != data.get('storyboard_revision'):
            raise ValueError('Storyboard revision mismatch')
        if vea.content_hash(data.get('manifest')) != data.get('spec_sha256'):
            raise ValueError('Manifest specification hash mismatch')
        return data


class Conflict(ValueError): pass


class ReceiptStore:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS director_jobs(
                task_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, idem TEXT NOT NULL,
                request_hash TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
                status TEXT NOT NULL, fence TEXT, lease REAL, result TEXT, error TEXT,
                UNIQUE(org_id,idem))''')
            db.execute('''CREATE TABLE IF NOT EXISTS director_bindings(
                binding_key TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES director_jobs(task_id))''')
            db.execute("CREATE INDEX IF NOT EXISTS director_campaign_active ON director_jobs(org_id,json_extract(payload,'$.campaign_id'),status)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db: yield db
        finally:
            db.close()

    @staticmethod
    def decode(row):
        if row is None: return None
        item = dict(row)
        for key in ('payload', 'result', 'error'):
            item[key] = json.loads(item[key]) if item[key] else None
        item['binding'] = {k: item['payload'][k] for k in ('org_id', 'run_id', 'campaign_id', 'storyboard_revision', 'attempt', 'spec_sha256', 'idempotency_key')}
        return item

    def submit(self, kind, payload):
        digest = vea.content_hash({'kind': kind, 'payload': payload})
        binding_key = vea.content_hash({'kind': kind, **{k: payload[k] for k in ('org_id', 'run_id', 'campaign_id', 'storyboard_revision', 'attempt')},
                                       'scene_index': payload.get('scene', {}).get('scene_index')})
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT * FROM director_jobs WHERE org_id=? AND idem=?', (payload['org_id'], payload['idempotency_key'])).fetchone()
            if prior:
                if prior['request_hash'] != digest: raise Conflict('Idempotency key is already bound to another immutable request')
                return self.decode(prior)
            # The database lock covers the check and insertion across processes.
            # Keep an old revision's uncertain running work behind this barrier
            # until its receipt is terminal or explicit recovery closes it.
            if db.execute("SELECT 1 FROM director_jobs WHERE org_id=? AND json_extract(payload,'$.campaign_id')=? AND status IN ('queued','running') LIMIT 1",
                          (payload['org_id'], payload['campaign_id'])).fetchone():
                raise Conflict('campaign_execution_busy')
            if db.execute('SELECT 1 FROM director_bindings WHERE binding_key=?', (binding_key,)).fetchone():
                raise Conflict('Attempt is already bound to another immutable request; create a new attempt')
            task_id = str(uuid4())
            db.execute('INSERT INTO director_jobs(task_id,org_id,idem,request_hash,kind,payload,status) VALUES(?,?,?,?,?,?,?)',
                       (task_id, payload['org_id'], payload['idempotency_key'], digest, kind, json.dumps(payload, ensure_ascii=False), 'queued'))
            db.execute('INSERT INTO director_bindings(binding_key,task_id) VALUES(?,?)', (binding_key, task_id))
        return self.get(task_id, payload['org_id'])

    def get(self, task_id, org_id):
        with self.connect() as db:
            return self.decode(db.execute('SELECT * FROM director_jobs WHERE task_id=? AND org_id=?', (task_id, org_id)).fetchone())

    def lookup(self, org_id, idempotency_key):
        with self.connect() as db:
            return self.decode(db.execute('SELECT * FROM director_jobs WHERE org_id=? AND idem=?', (org_id, idempotency_key)).fetchone())

    def claim(self, task_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM director_jobs WHERE task_id=?', (task_id,)).fetchone()
            if not row or row['status'] != 'queued': return None
            campaign = json.loads(row['payload'])['campaign_id']
            if db.execute("SELECT 1 FROM director_jobs WHERE org_id=? AND json_extract(payload,'$.campaign_id')=? AND status='running' AND task_id<>? LIMIT 1",
                          (row['org_id'], campaign, task_id)).fetchone():
                return None
            fence = str(uuid4())
            db.execute("UPDATE director_jobs SET status='running',fence=?,lease=? WHERE task_id=?", (fence, time.time() + 3600, task_id))
            return self.decode(db.execute('SELECT * FROM director_jobs WHERE task_id=?', (task_id,)).fetchone())

    def finish(self, task_id, fence, result=None, error=None):
        with self.connect() as db:
            return db.execute("UPDATE director_jobs SET status=?,result=?,error=?,lease=NULL WHERE task_id=? AND status='running' AND fence=?",
                ('failed' if error else 'complete', json.dumps(result), json.dumps(error), task_id, fence)).rowcount == 1

    def recover(self):
        # Never rerender uncertain work: an expired execution remains visibly failed.
        with self.connect() as db:
            db.execute("UPDATE director_jobs SET status='failed',error=? WHERE status='running' AND lease<?",
                       (json.dumps({'code': 'execution_interrupted', 'message': 'Lease expired; create a new attempt after reconciling this receipt'}), time.time()))


def store():
    return ReceiptStore(os.getenv('VEA_DIRECTOR_DB', str(vea.ROOT / 'storage/director.sqlite3')))


def artifact_dir(task_id):
    from uuid import UUID
    task_id = str(UUID(task_id))
    return Path(os.getenv('VEA_DIRECTOR_ROOT', str(vea.ROOT / 'storage/director'))) / task_id


def inspection_dependencies(language):
    exe = os.getenv('VEA_TESSERACT', 'tesseract')
    if not shutil.which(exe): raise vea.VeaError('ocr_unavailable', 'Install local Tesseract and provision eng/rus/uzb language packs')
    code = {'en': 'eng', 'ru': 'rus', 'uz': 'uzb'}[language]
    result = subprocess.run([exe, '--list-langs'], capture_output=True, text=True, timeout=30)
    if result.returncode or code not in result.stdout.split():
        raise vea.VeaError('ocr_unavailable', f'Provision local Tesseract language pack {code}')
    return exe, code


def rendering_context(org_id, product_id=None, language='en'):
    """Hashes of actual server-managed inputs; no tenant paths or credentials."""
    if language not in ('en', 'ru', 'uz'): raise vea.VeaError('invalid_language')
    assets = vea.load_assets(org_id, product_id, language)
    exe, code = inspection_dependencies(language)
    model_path = Path(os.getenv('VEA_WHISPER_MODEL', ''))
    if not model_path.is_dir() or not (model_path / 'model.bin').is_file():
        raise vea.VeaError('alignment_unavailable', 'Context requires an explicit provisioned local model directory')
    model_hashes = {p.name: vea.file_hash(p) for p in sorted(model_path.iterdir()) if p.is_file()}
    tessdata = Path(os.getenv('TESSDATA_PREFIX', str(Path(shutil.which(exe)).parent / 'tessdata')))
    language_file = tessdata / (code + '.traineddata')
    if not language_file.is_file(): raise vea.VeaError('ocr_unavailable', 'Cannot hash local OCR language data')
    narration = []
    if os.getenv('VEA_DIRECTOR_NARRATION_ROOT'):
        root = Path(os.environ['VEA_DIRECTOR_NARRATION_ROOT']).resolve()
        try: catalog = json.loads((root / 'catalog.json').read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc: raise vea.VeaError('narration_unavailable') from exc
        for item in catalog.get('recordings', []):
            if item.get('org_id') != org_id or item.get('language') != language: continue
            path = (root / item.get('path', '')).resolve()
            if not path.is_relative_to(root) or not path.is_file() or vea.file_hash(path) != item.get('audio_sha256'):
                raise vea.VeaError('narration_checksum_mismatch')
            narration.append({'text_sha256': item['text_sha256'], 'audio_sha256': item['audio_sha256']})
    else:
        voice = json.loads(os.getenv('VEA_PIPER_VOICES', '{}')).get(language)
        if not voice or not Path(voice['model']).is_file(): raise vea.VeaError('narration_unavailable', 'Provision exact local narration or Piper voice')
        narration.append({'voice_sha256': vea.file_hash(voice['model']), 'config_sha256': vea.file_hash(voice.get('config', voice['model'] + '.json'))})
    font_roots = [Path(os.getenv('WINDIR', 'C:/Windows')) / 'Fonts', vea.ROOT / 'resource/fonts',
                  Path('/usr/share/fonts'), Path('/usr/local/share/fonts'), Path.home() / '.local/share/fonts']
    fonts = {f'{index}/{p.relative_to(root).as_posix()}': vea.file_hash(p) for index, root in enumerate(font_roots) if root.is_dir() for p in root.rglob('*')
             if p.is_file() and p.suffix.lower() in ('.ttf', '.otf', '.ttc')}
    config = {'schema_version': 1, 'code': {p.name: vea.file_hash(p) for p in (Path(__file__), Path(vea.__file__))},
              'model': model_hashes, 'ocr_data': vea.file_hash(language_file), 'narration': narration, 'fonts': fonts,
              'whisper_device': os.getenv('VEA_WHISPER_DEVICE', 'cpu'), 'whisper_compute_type': 'int8',
              'binaries': {name: vea.file_hash(shutil.which(os.getenv(env, name))) for name, env in [('ffmpeg', 'VEA_FFMPEG'), ('ffprobe', 'VEA_FFPROBE'), ('tesseract', 'VEA_TESSERACT')]}}
    if not os.getenv('VEA_DIRECTOR_NARRATION_ROOT'):
        executable = shutil.which(os.getenv('VEA_PIPER_EXE', 'piper'))
        if not executable: raise vea.VeaError('narration_unavailable', 'Provision the local Piper executable')
        config['binaries']['piper'] = vea.file_hash(executable)
    asset_rows = [{**metadata, 'sku_tags': asset.get('sku_tags', [])} for metadata, asset in zip(vea.public_assets(assets), assets)]
    return {'asset_catalog_sha256': vea.content_hash(asset_rows), 'renderer_config_sha256': vea.content_hash(config)}


def media_evidence(path):
    probe = vea.probe_media(path)
    # Decode every frame/sample as ffprobe alone does not prove decodability.
    vea.run_media(['-i', path, '-f', 'null', '-'])
    streams = [{k: s[k] for k in ('codec_type', 'codec_name', 'width', 'height', 'duration', 'start_time', 'sample_rate') if k in s} for s in probe['streams']]
    return {'duration_sec': float(probe['format']['duration']), 'format_name': probe['format']['format_name'], 'streams': streams, 'decoded': True}


def observe_words(audio, language):
    return vea.observe_audio_words(audio, language)


def narration_audio(request, cache):
    """Use exact tenant-owned recordings when provisioned, else explicit local TTS.

    This is a server-managed catalog, never an arbitrary caller supplied path.
    Reusing a recording also permits independently annotated speech evaluations.
    """
    configured = os.getenv('VEA_DIRECTOR_NARRATION_ROOT')
    if configured:
        root = Path(configured).resolve()
        try:
            catalog = json.loads((root / 'catalog.json').read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise vea.VeaError('narration_unavailable', 'Provision the local approved narration catalog') from exc
        for item in catalog.get('recordings', []):
            if (item.get('org_id'), item.get('language'), item.get('text_sha256')) != (request.org_id, request.language, vea.content_hash(request.scene.narration_chunk)):
                continue
            path = (root / item.get('path', '')).resolve()
            if not path.is_relative_to(root) or not path.is_file() or vea.file_hash(path) != item.get('audio_sha256'):
                raise vea.VeaError('narration_checksum_mismatch')
            return {'path': path, 'provider': 'approved_local_recording', 'fallback_used': False}
        raise vea.VeaError('narration_unavailable', 'No exact tenant/language/narration hash recording is provisioned')
    if os.getenv('ELEVENLABS_API_KEY'):
        raise vea.VeaError('local_narration_required', 'Director jobs require an approved local recording or provisioned local Piper voice')
    return vea.synthesize_narration(request.scene.narration_chunk, None, request.language, cache)


def ocr_frames(video, overlay, language, folder):
    exe, code = inspection_dependencies(language)
    start, end = overlay.start_sec, overlay.end_sec
    points = sorted({start + min(.15, (end-start)/4), (start+end)/2, end-min(.15, (end-start)/4)})
    if overlay.animation == 'fade':
        points = sorted(set(points + [start + min(.3, (end-start)/2), end-min(.3, (end-start)/2)]))
    evidence = []
    crop_y = {'top': 0, 'center': 640, 'bottom': 1280}[overlay.position]
    for i, second in enumerate(points):
        frame = folder / f'ocr-{round(start*1000)}-{i}.png'
        vea.run_media(['-ss', second, '-i', video, '-vf', f'crop=1080:640:0:{crop_y}', '-frames:v', '1', frame])
        result = subprocess.run([exe, str(frame), 'stdout', '-l', code, '--psm', '11', 'tsv'], capture_output=True, text=True, encoding='utf-8', timeout=60)
        if result.returncode: raise vea.VeaError('ocr_failed', 'Local Tesseract could not inspect rendered frame')
        rows = []
        import csv, io
        for row in csv.DictReader(io.StringIO(result.stdout), delimiter='\t'):
            if row.get('text', '').strip(): rows.append(row)
        evidence.append({'time_sec': second, 'frame_sha256': vea.file_hash(frame), 'observed_text': ' '.join(r['text'] for r in rows),
                         'language': code, 'region': {'x': 0, 'y': crop_y, 'width': 1080, 'height': 640},
                         'boxes': [{**{k: r[k] for k in ('left', 'width', 'height', 'conf', 'text')}, 'top': str(int(r['top']) + crop_y)} for r in rows]})
    return evidence


def render_scene(job):
    request = SceneRequest.model_validate(job['payload']); scene = request.scene
    folder = artifact_dir(job['task_id']); folder.mkdir(parents=True, exist_ok=True)
    inspection_dependencies(request.language)
    assets = vea.load_assets(request.org_id, request.product_id, request.language)
    required = set(scene.asset_constraints.required_sku_tags)
    eligible = [a for a in assets if a['kind'] == 'video' and required.issubset(set(a.get('sku_tags', [])) | set(sum(a.get('tags', {}).values(), [])))]
    selected = vea.select_matching_broll(scene.visual_directive.prompt, scene.target_duration_sec, eligible, request.language)[0]
    cache = folder / 'speech'; cache.mkdir(exist_ok=True)
    speech = narration_audio(request, cache)
    speech_duration = vea.media_duration(speech['path'])
    duration = max(scene.target_duration_sec, speech_duration)
    if speech_duration > scene.target_duration_sec + .15:
        raise vea.VeaError('narration_duration_mismatch', 'Approved narration exceeds scene duration; revise timing without truncating speech')
    audio = folder / 'narration.wav'
    vea.run_media(['-i', speech['path'], '-af', f'apad,atrim=duration={duration}', '-ar', '48000', '-ac', '2', audio])
    observed = observe_words(audio, request.language)
    alignment = vea.align_words(scene.narration_chunk, observed, round(duration*1000))
    overlay = scene.overlay_text
    color = '&H00' + overlay.color[5:7] + overlay.color[3:5] + overlay.color[1:3]
    alignment_code = {'top': 8, 'center': 5, 'bottom': 2}[overlay.position]
    narration_position, narration_margin = (8, 600) if overlay.position == 'bottom' else (2, 260)
    header = ('[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n[V4+ Styles]\n'
              'Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BorderStyle, Outline, Alignment, MarginL, MarginR, MarginV\n'
              f'Style: Exact,{overlay.font_family},{overlay.font_size},{color},&H00000000,1,3,{alignment_code},80,80,120\n'
              f'Style: Narration,{overlay.font_family},48,&H00FFFFFF,&H00000000,1,3,{narration_position},80,80,{narration_margin}\n'
              '[Events]\nFormat: Layer, Start, End, Style, Text\n')
    animation = r'{\fad(150,150)}' if overlay.animation == 'fade' else ''
    if overlay.animation == 'slide':
        y = {'top': 120, 'center': 960, 'bottom': 1800}[overlay.position]
        animation = f'{{\\move(440,{y},540,{y},0,150)}}'
    lines = [header, f'Dialogue: 0,{vea._ass_time(overlay.start_sec*1000)},{vea._ass_time(overlay.end_sec*1000)},Exact,{animation}{vea._ass_escape(overlay.text)}\n']
    for word in alignment['words']:
        phrase = next(p for p in alignment['phrases'] if p['start_ms'] <= word['start_ms'] and word['end_ms'] <= p['end_ms'])
        group = [w for w in alignment['words'] if phrase['start_ms'] <= w['start_ms'] and w['end_ms'] <= phrase['end_ms']]
        caption = ' '.join((r'{\b1}' if item is word else r'{\b0}') + vea._ass_escape(item['word']) for item in group)
        lines.append(f'Dialogue: 1,{vea._ass_time(word["start_ms"])},{vea._ass_time(word["end_ms"])},Narration,{caption}\n')
    (folder / 'overlay.ass').write_text(''.join(lines), encoding='utf-8')
    video = folder / 'final-1.mp4'
    if vea.file_hash(selected['path']) != selected['sha256']: raise vea.VeaError('asset_checksum_mismatch')
    vea.run_media(['-i', selected['path'], '-i', audio.resolve(), '-t', duration, '-vf',
                   'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30,ass=overlay.ass',
                   '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264', '-preset', 'veryfast', '-threads', '2', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', video.resolve()], cwd=folder)
    if vea.file_hash(selected['path']) != selected['sha256']: raise vea.VeaError('asset_checksum_mismatch')
    rendered_observed = observe_words(video, request.language)
    result = {'artifact_sha256': vea.file_hash(video), 'audio_sha256': vea.file_hash(audio), 'media': media_evidence(video),
              'scene_index': scene.scene_index, 'spec_sha256': request.spec_sha256,
              'alignment': {**alignment, 'observed_words': rendered_observed,
                            'rendered_cues': [{**w, 'start_ms': round(w['start_ms']/10)*10, 'end_ms': round(w['end_ms']/10)*10} for w in alignment['words']],
                            'rendered_phrase_cues': alignment['phrases'], 'observation_source': 'encoded_video_audio', 'tolerance_ms': 150},
              'overlay_timeline': [overlay.model_dump()], 'ocr': ocr_frames(video, overlay, request.language, folder),
              'provenance': [{**vea.public_assets([selected])[0], 'sku_tags': selected.get('sku_tags', []),
                              'source_path_verified': True}], 'binding': job['binding']}
    return result


def assemble_master(job):
    request = MasterRequest.model_validate(job['payload']); manifest = request.manifest
    folder = artifact_dir(job['task_id']); folder.mkdir(parents=True, exist_ok=True)
    source_rows, offset, master_ocr, all_text, languages = [], 0.0, [], [], []
    for index, token in enumerate(manifest.scenes):
        if index and manifest.transitions and manifest.transitions[index-1] == 'crossfade': offset -= .15
        row = store().get(token.task_id, request.org_id)
        if not row or row['kind'] != 'scene' or row['status'] != 'complete': raise vea.VeaError('scene_not_available')
        # Milo authorizes reuse using the complete immutable specification and its
        # verified token. Source receipts retain their original run/revision.
        if any(row['binding'][k] != job['binding'][k] for k in ('org_id', 'campaign_id')):
            raise vea.VeaError('scene_binding_mismatch')
        result = row['result']; source = artifact_dir(token.task_id) / 'final-1.mp4'
        if result['scene_index'] != token.scene_index or result['artifact_sha256'] != token.artifact_sha256 or vea.file_hash(source) != token.artifact_sha256:
            raise vea.VeaError('scene_checksum_mismatch')
        # Local copies make concat paths unambiguous on all supported hosts.
        shutil.copyfile(source, folder / f'scene-{index}.mp4')
        shutil.copyfile(artifact_dir(token.task_id) / 'narration.wav', folder / f'voice-{index}.wav')
        duration = result['media']['duration_sec']
        source_rows.append({'scene_index': token.scene_index, 'task_id': token.task_id, 'artifact_sha256': vea.file_hash(source),
                            'verified_token': token.verified_token, 'start_sec': offset, 'end_sec': offset + duration,
                            'overlay_timeline': result['overlay_timeline'], 'ocr': result['ocr']})
        all_text.append(row['payload']['scene']['narration_chunk']); languages.append(row['payload'].get('language', 'en'))
        offset += duration
    (folder / 'scenes.txt').write_text(''.join(f"file 'scene-{i}.mp4'\n" for i in range(len(source_rows))), encoding='utf-8')
    (folder / 'voices.txt').write_text(''.join(f"file 'voice-{i}.wav'\n" for i in range(len(source_rows))), encoding='utf-8')
    if 'crossfade' in manifest.transitions:
        args, filters = [], []
        count = len(source_rows)
        for index in range(count): args += ['-i', f'scene-{index}.mp4']
        for index in range(count): args += ['-i', f'voice-{index}.wav']
        for index in range(count):
            filters += [f'[{index}:v]settb=AVTB,setpts=PTS-STARTPTS[v{index}]', f'[{count+index}:a]asetpts=PTS-STARTPTS[a{index}]']
        video, audio = 'v0', 'a0'
        for index in range(1, count):
            if manifest.transitions[index-1] == 'crossfade':
                filters += [f'[{video}][v{index}]xfade=transition=fade:duration=0.15:offset={source_rows[index]["start_sec"]}[vv{index}]',
                            f'[{audio}][a{index}]acrossfade=d=0.15:c1=tri:c2=tri[aa{index}]']
            else:
                filters += [f'[{video}][v{index}]concat=n=2:v=1:a=0[vv{index}]', f'[{audio}][a{index}]concat=n=2:v=0:a=1[aa{index}]']
            video, audio = f'vv{index}', f'aa{index}'
        vea.run_media(args + ['-filter_complex_threads', '1', '-filter_complex', ';'.join(filters), '-map', f'[{video}]',
                              '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-threads', '2', '-pix_fmt', 'yuv420p', 'visuals.mp4',
                              '-map', f'[{audio}]', '-vn', '-c:a', 'pcm_s16le', 'narration.wav'], cwd=folder)
    else:
        vea.run_media(['-f', 'concat', '-safe', '1', '-i', 'scenes.txt', '-an', '-c:v', 'copy', 'visuals.mp4'], cwd=folder)
        vea.run_media(['-f', 'concat', '-safe', '1', '-i', 'voices.txt', '-c:a', 'pcm_s16le', 'narration.wav'], cwd=folder)
    narration_words = observe_words(folder / 'narration.wav', languages[0]) if len(set(languages)) == 1 else []
    music_asset, ducking = None, []
    if manifest.background_asset_id:
        available = vea.load_assets(request.org_id, language=languages[0], selection='manual')
        music_asset = next((a for a in available if a['kind'] == 'music' and a['id'] == manifest.background_asset_id), None)
        if not music_asset: raise vea.VeaError('missing_music_asset', 'Provision rights-cleared music in this tenant catalog')
        if vea.file_hash(music_asset['path']) != music_asset['sha256']: raise vea.VeaError('asset_checksum_mismatch')
        if not narration_words: raise vea.VeaError('ducking_evidence_unavailable', 'Measured speech intervals required for music ducking')
        voice_samples = pcm_samples(folder / 'narration.wav')
        windows = [(max(0, w['start_ms']/1000), min(offset, w['end_ms']/1000)) for w in narration_words]
        voice_levels = [window_db(voice_samples, a, b) for a, b in windows]
        # Bound speech-time music by the quietest measured narration window;
        # let it recover by 12 dB during pauses, with 100 ms speech shoulders.
        gain = min(voice_levels) + manifest.audio_ducking_db - 1
        speech_expression = '+'.join(f'between(t,{max(0,a-.1):.6f},{min(offset,b+.1):.6f})' for a, b in windows)
        volume = f"volume='if(gt({speech_expression},0),{10**(gain/20):.12f},{10**((gain+12)/20):.12f})':eval=frame"
        vea.run_media(['-stream_loop', '-1', '-i', music_asset['path'], '-t', offset, '-af', f'alimiter=limit=0.95:latency=1,{volume}',
                       '-ar', '48000', '-ac', '2', 'background.wav'], cwd=folder)
        background_samples = pcm_samples(folder / 'background.wav')
        ducking = [{'start_sec': a, 'end_sec': b, 'narration_dbfs': level, 'background_dbfs': window_db(background_samples, a, b)}
                   for (a, b), level in zip(windows, voice_levels)]
        vea.run_media(['-i', 'visuals.mp4', '-i', 'narration.wav', '-i', 'background.wav', '-filter_complex',
                       '[1:a][2:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:latency=1[a]',
                       '-map', '0:v', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-movflags', '+faststart', 'final-1.mp4'], cwd=folder)
        if vea.file_hash(music_asset['path']) != music_asset['sha256']: raise vea.VeaError('asset_checksum_mismatch')
    else:
        vea.run_media(['-i', 'visuals.mp4', '-i', 'narration.wav', '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac',
                       '-movflags', '+faststart', 'final-1.mp4'], cwd=folder)
    video = folder / 'final-1.mp4'
    for item, token in zip(source_rows, manifest.scenes):
        row = store().get(token.task_id, request.org_id)
        overlay = Overlay.model_validate(row['payload']['scene']['overlay_text'])
        overlay.start_sec += item['start_sec']; overlay.end_sec += item['start_sec']
        frames = ocr_frames(video, overlay, row['payload'].get('language', 'en'), folder)
        item['source_ocr'] = item['ocr']
        item['ocr'] = frames
        master_ocr.append({'scene_index': item['scene_index'], 'frames': frames})
    # Only final master media is copied into the existing public preview surface.
    preview_dir = vea.ROOT / 'storage/tasks' / job['task_id']; preview_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(video, preview_dir / 'final-1.mp4')
    vea.run_media(['-i', video, '-frames:v', '1', '-update', '1', preview_dir / 'final-1.jpg'])
    prefix = os.getenv('VEA_PUBLIC_ENDPOINT', '').rstrip('/') + '/tasks/' + job['task_id']
    return {'artifact_sha256': vea.file_hash(video), 'media': media_evidence(video), 'binding': job['binding'],
            'video_url': prefix + '/final-1.mp4', 'thumbnail_url': prefix + '/final-1.jpg', 'ocr': master_ocr,
            'observed_words': observe_words(video, languages[0]) if len(set(languages)) == 1 else [],
            'ordered_scenes': source_rows, 'narration_sha256': vea.file_hash(folder / 'narration.wav'),
            'audio': audio_measurements(video), 'music_present': bool(music_asset), 'ducking_windows': ducking,
            'background_asset_id': music_asset['id'] if music_asset else None,
            'background_stem': audio_measurements(folder / 'background.wav') if music_asset else None,
            'background_sha256': vea.file_hash(folder / 'background.wav') if music_asset else None,
            'provenance': vea.public_assets([music_asset]) if music_asset else [],
            'narration_stem': audio_measurements(folder / 'narration.wav')}


def pcm_samples(path):
    import array
    result = subprocess.run([os.getenv('VEA_FFMPEG', 'ffmpeg'), '-v', 'error', '-i', str(path), '-vn', '-f', 'f32le', '-ac', '1', '-ar', '16000', '-'], capture_output=True, timeout=300)
    if result.returncode: raise vea.VeaError('audio_inspection_failed')
    values = array.array('f'); values.frombytes(result.stdout)
    if not values or any(not math.isfinite(v) for v in values): raise vea.VeaError('audio_inspection_failed')
    return values


def window_db(values, start, end):
    samples = values[round(start*16000):round(end*16000)]
    if not samples: raise vea.VeaError('audio_inspection_failed', 'Empty measured speech window')
    return 20*math.log10(max(math.sqrt(sum(v*v for v in samples)/len(samples)), 1e-12))


def audio_measurements(path):
    values = pcm_samples(path)
    peak = max(abs(v) for v in values); rms = math.sqrt(sum(v*v for v in values)/len(values))
    return {'sample_count': len(values), 'sample_rate': 16000, 'peak': peak, 'rms_dbfs': 20*math.log10(max(rms, 1e-12)), 'clipped_samples': sum(abs(v) >= 1 for v in values)}


def job_rendering_context(job):
    payload = job['payload']
    language, product_id = payload.get('language', 'en'), payload.get('product_id')
    if job['kind'] == 'master':
        sources = payload['manifest']['scenes']
        row = store().get(sources[0]['task_id'], payload['org_id'])
        if not row or row['kind'] != 'scene' or row['status'] != 'complete':
            raise vea.VeaError('scene_not_available')
        language, product_id = row['payload'].get('language', 'en'), row['payload'].get('product_id')
    return RendererContext.model_validate(rendering_context(payload['org_id'], product_id, language)).model_dump(mode='json')


def execute(task_id):
    receipts = store(); job = receipts.claim(task_id)
    if not job: return
    try:
        request = (SceneRequest if job['kind'] == 'scene' else MasterRequest).model_validate(job['payload'])
        actual_context = job_rendering_context(job)
        expected = request.expected_context.model_dump(mode='json') if request.expected_context else None
        if expected is not None and actual_context != expected:
            raise vea.VeaError('renderer_context_changed', 'Tenant assets or renderer inputs changed; create a newly validated run')
        result = render_scene(job) if job['kind'] == 'scene' else assemble_master(job)
        if job_rendering_context(job) != actual_context:
            raise vea.VeaError('renderer_context_changed', 'Tenant assets or renderer inputs changed during rendering')
        result['renderer_context'] = actual_context
        result['evidence_sha256'] = vea.content_hash(result)
        vea.atomic_json(artifact_dir(task_id) / 'evidence.json', result)
        receipts.finish(task_id, job['fence'], result=result)
    except Exception as exc:
        receipts.finish(task_id, job['fence'], error={'code': getattr(exc, 'code', 'render_failed'), 'message': str(exc)[:1500]})
