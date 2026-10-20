"""Produce inspectable deterministic media evidence using synthetic inputs.

This verifies codecs, caption layout and timing, not TTS/ASR speech quality.
No generated media or runtime asset catalog is checked into source control.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import vea


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve(); root.mkdir(parents=True, exist_ok=True)
    vea.run_media(['-f', 'lavfi', '-i', 'testsrc2=size=360x640:rate=30:duration=3',
                   '-c:v', 'libx264', '-pix_fmt', 'yuv420p', root / 'source.mp4'])
    vea.run_media(['-f', 'lavfi', '-i', 'sine=frequency=440:duration=3', '-c:a', 'libmp3lame', root / 'voice.mp3'])
    duration = vea.media_duration(root / 'voice.mp3')
    asset = {'id': 'diagnostic-clip', 'kind': 'video', 'path': str(root/'source.mp4'),
             'sha256': vea.file_hash(root/'source.mp4'), 'duration_sec': 3, 'tags': {'und': ['product']}}
    scenes = [{'spoken_narration': text, 'visual_broll_cues': 'product', 'on_screen_text': overlay} for text, overlay in [
        ('Approved words stay exact.', 'VEA / DETERMINISTIC PRESET\n\nSYNTHETIC MEDIA PROOF'),
        ('Точный текст одобренного сценария.', 'ОДОБРЕННЫЙ ТЕКСТ\n\nБез изменения формулировок'),
        ("Tasdiqlangan so‘zlar aniq saqlanadi.", "TASDIQLANGAN MATN\n\nO‘zbekcha yozuv")]]
    timings = []
    for scene in scenes:
        timing = [{'word': word, 'start_ms': 200 + index * 600, 'end_ms': 700 + index * 600}
                  for index, word in enumerate(scene['spoken_narration'].split())]
        timings.append(vea.align_words(scene['spoken_narration'], timing, round(duration*1000)))
    for label, color in [('dark-brand', '#112233'), ('bright-brand', '#FFE147')]:
        folder = root / label; folder.mkdir(exist_ok=True)
        manifest = vea.compile_composition(scenes, timings, [duration]*len(scenes), [asset],
                        vea.load_preset('high_velocity_d2c'), {'revision': 1, 'hex_colors': [color]}, 'en')
        vea.atomic_json(folder/'composition.json', manifest)
        outputs = vea.render_video_composition([root/'voice.mp3']*len(scenes), manifest, [asset], folder)
        for language, seconds in [('en', 1.0), ('ru', duration + 1.0), ('uz', duration*2 + 1.0)]:
            vea.run_media(['-ss', seconds, '-i', outputs['video'], '-frames:v', '1', '-update', '1', folder/f'frame-{language}.jpg'])
        print(outputs['video'])


if __name__ == '__main__': main()
