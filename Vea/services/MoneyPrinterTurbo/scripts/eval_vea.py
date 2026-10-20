"""Separate VEA evaluation suite. Default cases are explicitly synthetic.

--corpus enables actual locally recorded speech evaluation in en/ru/uz. No
credentials or model downloads are attempted; missing inputs/config exit 2.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import vea
from scripts.evaluate_vea_alignment import boundary_metrics


def fixture_evaluation():
    results = []
    texts = {'en': 'one two three four five six seven eight nine ten',
             'ru': 'один два три четыре пять шесть семь восемь девять десять',
             'uz': 'bir ikki uch to‘rt besh olti yetti sakkiz to‘qqiz o‘n'}
    for language, text in texts.items():
        reference = [{'word': word, 'start_ms': i*300+20, 'end_ms': (i+1)*300}
                     for i, word in enumerate(text.split())]
        observed = [dict(w) for i, w in enumerate(reference) if i != 4]
        aligned = vea.align_words(text, observed, 3100)
        results.append({'id': 'synthetic-interpolated-' + language, 'language': language,
                        'kind': 'synthetic_timing', 'alignment_score': aligned['alignment_score'],
                        'interpolated_token_indices': aligned['interpolated_token_indices'],
                        **boundary_metrics(aligned['words'], reference)})
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder); (root/'clip.mp4').write_bytes(b'synthetic-non-media-catalog-fixture')
        asset = {'id': 'a', 'org_id': 'brand', 'path': 'clip.mp4', 'sha256': vea.file_hash(root/'clip.mp4'),
                 'kind': 'video', 'duration_sec': 4, 'width': 1080, 'height': 1920, 'tags': {'en': ['steel hinge']},
                 'product_ids': ['product'], 'rights_confirmed': True, 'permitted_uses': ['advertising']}
        assets = [asset, {**asset, 'id': 'b'}, {**asset, 'id': 'other-org', 'org_id': 'other'},
                  {**asset, 'id': 'other-product', 'product_ids': ['other']},
                  {**asset, 'id': 'no-rights', 'rights_confirmed': False}]
        vea.atomic_json(root/'catalog.json', {'schema_version': 1, 'assets': assets})
        previous = os.environ.get('VEA_ASSET_ROOT'); os.environ['VEA_ASSET_ROOT'] = folder
        try:
            eligible = vea.load_assets('brand', 'product', 'en', verify_media=False)
            ranked = vea.select_matching_broll('steel hinge', 3, eligible, 'en')
            isolated = [a['id'] for a in eligible] == ['a', 'b'] and ranked[0]['id'] == 'a'
            try: vea.select_matching_broll('unrelated beach', 3, eligible, 'en')
            except vea.VeaError as exc: isolated = isolated and exc.code == 'missing_assets'
            else: isolated = False
            results.append({'id': 'catalog-isolation-and-stable-ranking', 'kind': 'synthetic_catalog', 'passed': isolated})
        finally:
            if previous is None: os.environ.pop('VEA_ASSET_ROOT', None)
            else: os.environ['VEA_ASSET_ROOT'] = previous
    return {'evidence': 'synthetic_only_not_speech_quality', 'passed': all(r['passed'] for r in results), 'cases': results}


def corpus_evaluation(path, cache):
    fixtures = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(fixtures, list) or not {'en', 'ru', 'uz'}.issubset({r['language'] for r in fixtures}):
        raise ValueError('Corpus must include annotated English, Russian and Uzbek recordings')
    if not os.getenv('VEA_WHISPER_MODEL'):
        raise ValueError('Configure the provisioned local VEA_WHISPER_MODEL before corpus evaluation')
    results = []
    for fixture in fixtures:
        audio = Path(fixture['audio_path'])
        if not audio.is_absolute(): audio = path.resolve().parent/audio
        if not audio.is_file(): raise ValueError('Corpus references a missing local speech recording')
        aligned = vea.extract_word_timestamps(audio, fixture['approved_text'], fixture['language'], cache)
        results.append({'id': fixture.get('id', audio.name), 'language': fixture['language'],
                        'alignment_score': aligned['alignment_score'], 'anchor_coverage': aligned['anchor_coverage'],
                        'interpolated_token_indices': aligned['interpolated_token_indices'],
                        **boundary_metrics(aligned['words'], fixture['reference_words'])})
    return {'evidence': 'annotated_recorded_speech', 'passed': all(r['passed'] for r in results), 'cases': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path)
    parser.add_argument('--cache', type=Path, default=Path(tempfile.gettempdir())/'vea-eval-cache')
    args = parser.parse_args()
    try:
        report = corpus_evaluation(args.corpus, args.cache) if args.corpus else fixture_evaluation()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'passed': False, 'evidence': 'no_speech_quality_evidence',
                          'error_code': getattr(exc, 'code', 'evaluation_input_missing'),
                          'message': str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
