"""Opt-in real FFmpeg/MoviePy composition, using local synthetic assets only.

Run with MPT_RUN_MEDIA_TESTS=1 in a provider environment. No TTS, stock search,
LLM call, or social publishing request is made. Proof media stays in temp.
"""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).parents[2]


@unittest.skipUnless(os.getenv('MPT_RUN_MEDIA_TESTS') == '1', 'Opt-in local media composition')
class ApprovedSceneMediaTests(unittest.TestCase):
    def test_real_overlay_composition_displays_all_languages_on_approved_timeline(self):
        import numpy as np
        from moviepy import ColorClip, VideoFileClip
        sys.path.insert(0, str(ROOT))
        with patch.dict(sys.modules, {'app.config':SimpleNamespace(config=SimpleNamespace(ui={},app={}))}):
            renderer=importlib.import_module('app.services.video')
            schema=importlib.import_module('app.models.schema')
            helper=importlib.import_module('app.services.approved_scenes')
        folder=Path(tempfile.mkdtemp(prefix='milo-render-proof-'))
        source=folder/'source.mp4'; audio=folder/'audio.wav'; output=folder/'approved.mp4'
        background=ColorClip(size=(1080,1920),color=(24,32,48)).with_duration(3)
        background.write_videofile(str(source),fps=10,codec='libx264',audio=False,logger=None,threads=2)
        background.close()
        rate=44100
        samples=(np.sin(2*np.pi*220*np.arange(rate*3)/rate)*5000).astype('<i2')
        with wave.open(str(audio),'wb') as handle:
            handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(rate); handle.writeframes(samples.tobytes())
        scenes=[
            {'spoken_narration':'Tested steel.','visual_broll_cues':'steel hinge','on_screen_text':'STEEL\n\nTESTED'},
            {'spoken_narration':'Проверено.','visual_broll_cues':'laboratory','on_screen_text':'ПРОВЕРЕНО'},
            {'spoken_narration':"Sinab ko‘ring.",'visual_broll_cues':'demonstration','on_screen_text':"Sinab ko‘ring"},
        ]
        cues=[((0.15,0.9),'Tested steel.'),((1.05,1.9),'Проверено.'),((2.05,2.9),"Sinab ko‘ring.")]
        subtitles=helper.write_scene_overlays(str(folder/'approved.json'),scenes,cues)
        params=schema.VideoParams(video_subject='Local rendering proof',
            video_script='\n\n'.join(scene['spoken_narration'] for scene in scenes),
            video_terms=[scene['visual_broll_cues'] for scene in scenes],approved_scenes=scenes,
            font_name='DejaVuSans.ttf',font_size=54,bgm_type='',bgm_volume=0,n_threads=2)
        renderer.generate_video(str(source),str(audio),subtitles,str(output),params)
        with VideoFileClip(str(output)) as result:
            baseline=result.get_frame(0.05).astype(float)
            frames=[result.get_frame(time).astype(float) for time in (0.5,1.5,2.5)]
            differences=[float(np.abs(frame-baseline).mean()) for frame in frames]
            self.assertTrue(all(delta>0.05 for delta in differences),differences)
            self.assertTrue(all(float(np.abs(a-b).mean())>0.02 for a,b in zip(frames,frames[1:])))
            self.assertGreaterEqual(result.duration,2.9)
            self.assertAlmostEqual(result.audio.duration,3,delta=0.15)
            from PIL import Image
            for index,frame in enumerate(frames,1):Image.fromarray(frame.astype('uint8')).save(folder/f'scene-{index}.png')
            print(json.dumps({'proof_directory':str(folder),'frame_differences':differences,
                'video_duration':result.duration,'audio_duration':result.audio.duration}))
