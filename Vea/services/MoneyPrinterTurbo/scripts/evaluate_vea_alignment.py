"""Evaluate local annotated speech recordings without downloading ASR models.

Each JSON record has audio_path, approved_text, language and reference_words
[{word,start_ms,end_ms}]. Relative audio paths resolve beside the annotations.
Synthetic unit fixtures test the evaluator, not real speech recognition quality.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import vea


def boundary_metrics(actual, reference, tolerance_ms=200):
    if len(actual) != len(reference) or not reference:
        raise ValueError('Reference and approved word counts must match')
    errors = []
    for measured, expected in zip(actual, reference):
        if measured['word'] != expected['word']:
            raise ValueError('Reference wording must exactly match approved caption tokens')
        errors.extend(abs(measured[field] - expected[field]) for field in ('start_ms', 'end_ms'))
    fraction = sum(error <= tolerance_ms for error in errors) / len(errors)
    return {'boundary_count': len(errors), f'within_{tolerance_ms}ms_fraction': fraction,
            'within_tolerance_fraction': fraction, 'tolerance_ms': tolerance_ms,
            'maximum_error_ms': max(errors), 'mean_error_ms': sum(errors)/len(errors), 'passed': fraction >= .95}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('annotations', type=Path)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--tolerance-ms', type=int, default=150)
    args = parser.parse_args()
    fixtures = json.loads(args.annotations.read_text(encoding='utf-8'))
    if not fixtures: parser.error('Provide at least one annotated recording')
    results = []
    for fixture in fixtures:
        path = Path(fixture['audio_path'])
        if not path.is_absolute(): path = args.annotations.resolve().parent / path
        try:
            result = vea.extract_word_timestamps(path, fixture['approved_text'], fixture['language'], args.cache)
            metrics = boundary_metrics(result['words'], fixture['reference_words'], args.tolerance_ms)
            results.append({'id': fixture.get('id', path.name), 'language': fixture['language'],
                            'alignment_score': result['alignment_score'], 'anchor_coverage': result['anchor_coverage'],
                            'interpolated_token_indices': result['interpolated_token_indices'],
                            'reference_source': fixture.get('reference_source', 'unspecified'), **metrics})
        except vea.VeaError as exc:
            results.append({'id': fixture.get('id', path.name), 'language': fixture['language'], 'passed': False, 'error_code': exc.code})
    print(json.dumps({'passed': all(row['passed'] for row in results), 'recordings': results}, ensure_ascii=False, indent=2))
    return 0 if all(row['passed'] for row in results) else 1


if __name__ == '__main__': raise SystemExit(main())
