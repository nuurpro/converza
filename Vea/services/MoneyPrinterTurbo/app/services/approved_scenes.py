"""Deterministic alignment of approved overlays to existing narration timings.

Scene boundaries inside a subtitle cue are interpolated by spoken character
position. Cue boundaries themselves retain the TTS timing. Alignment failures
raise rather than silently replacing approved scene text with narration.
"""
from html import unescape
import json
import re
import unicodedata


def _normalized(text):
    return ''.join(char.casefold() for char in unicodedata.normalize('NFKC', unescape(text)) if char.isalnum())


def scene_overlays(scenes, cues):
    expected = [_normalized(scene['spoken_narration']) for scene in scenes]
    timed = [(start, end, _normalized(text)) for ((start, end), text) in cues]
    timed = [(start, end, text) for start, end, text in timed if text]
    if not timed or any(not text for text in expected) or ''.join(expected) != ''.join(text for _, _, text in timed):
        raise ValueError('Cannot align approved scene text to narration subtitle timing')
    spans = []
    cursor = 0
    for start, end, text in timed:
        if end <= start:
            raise ValueError('Cannot align invalid narration subtitle timing')
        spans.append((cursor, cursor + len(text), start, end))
        cursor += len(text)

    def boundary(position, is_end=False):
        candidates = reversed(spans) if not is_end else iter(spans)
        for left, right, start, end in candidates:
            if left <= position <= right:
                return start + (end - start) * (position - left) / (right - left)
        raise ValueError('Cannot align approved scene boundary')

    result = []
    cursor = 0
    for scene, text in zip(scenes, expected):
        start = boundary(cursor)
        cursor += len(text)
        end = boundary(cursor, is_end=True)
        if scene['on_screen_text']:
            result.append(((start, end), scene['on_screen_text']))
    return result


def read_subtitle_cues(filename):
    """Read SRT timings without importing the media stack in contract tests."""
    with open(filename, encoding='utf-8-sig') as handle:
        content = handle.read()
    def seconds(value):
        hours, minutes, rest = value.replace(',', '.').split(':')
        return int(hours) * 3600 + int(minutes) * 60 + float(rest)
    cues = []
    for block in re.split(r'\n\s*\n', content.strip()):
        lines = block.splitlines()
        timing_index = next((index for index, line in enumerate(lines) if ' --> ' in line), None)
        if timing_index is None:
            raise ValueError('Cannot align invalid narration subtitle format')
        start, end = lines[timing_index].split(' --> ', 1)
        cues.append(((seconds(start), seconds(end)), '\n'.join(lines[timing_index + 1:])))
    return cues


def write_scene_overlays(filename, scenes, cues):
    """JSON keeps multiline copy separate from SRT's blank-line delimiters."""
    rows = [{'start': start, 'end': end, 'text': text}
            for ((start, end), text) in scene_overlays(scenes, cues)]
    with open(filename, 'w', encoding='utf-8') as handle:
        json.dump(rows, handle, ensure_ascii=False)
    return filename


def read_scene_overlays(filename):
    with open(filename, encoding='utf-8') as handle:
        rows = json.load(handle)
    if not isinstance(rows, list):
        raise ValueError('Invalid approved overlay timeline')
    cues = []
    for row in rows:
        start, end, text = row['start'], row['end'], row['text']
        if not isinstance(text, str) or not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or start < 0 or end <= start:
            raise ValueError('Invalid approved overlay timing or text')
        cues.append(((start, end), text))
    return cues
