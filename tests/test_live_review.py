import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from live_review import LiveReview,live_selector
from google_ai import AIError


class LiveReviewTests(unittest.TestCase):
    def test_select_is_owner_scoped_and_ambiguous_names_are_rejected(self):
        def source(owner,name,id):
            return SimpleNamespace(report_owner=owner,report_name=name,device_id=id,stopped=threading.Event(),image=b'jpeg',last_frame=time.monotonic())
        server=SimpleNamespace(stream_snapshot=lambda:[source('owner','Frente 1','1'),source('owner','Frente 2','2'),source('other','Secret Camera','3')])
        review=LiveReview(server,lambda image:image)
        self.assertEqual(len(review.select('owner','todas')),2)
        self.assertEqual(review.select('owner','veja agora a câmera frente 2')[0]['id'],'2')
        with self.assertRaises(AIError):review.select('owner','Secret Camera')
        with self.assertRaises(AIError):review.select('owner','frente')
        self.assertEqual(live_selector('Veja todas as câmeras ao vivo'),'todas')
        self.assertEqual(live_selector('/ao_vivo Portão'),'portao')
        self.assertIsNone(live_selector('O que aconteceu ontem?'))

    def test_samples_all_cameras_over_one_window_and_rejects_old_or_repeated_images(self):
        clock=SimpleNamespace(now=1000)
        class Stop:
            def is_set(self):return False
            def wait(self,seconds):clock.now+=seconds
        review=LiveReview(SimpleNamespace(),lambda image:image)
        def rows(owner):
            return {r['id']:r for r in [
                {'id':'1','name':'Atual','active':True,'stamp':clock.now,'image':str(clock.now).encode()},
                {'id':'2','name':'Repetida','active':True,'stamp':clock.now,'image':b'same'},
                {'id':'3','name':'Antiga','active':True,'stamp':900,'image':b'old'},
                {'id':'4','name':'Pausa','active':False,'stamp':clock.now,'image':b'paused','economy_paused':True}]}
        with patch.object(review,'sources',side_effect=rows),patch('live_review.time.monotonic',side_effect=lambda:clock.now),patch.object(review,'encode',return_value=b'mp4') as encoder:
            result=review.capture('owner','todas',Stop())
        self.assertEqual(clock.now,1006)
        self.assertEqual(result[0]['quadros_distintos'],6)
        self.assertEqual(result[0]['clip'],b'mp4')
        self.assertEqual(result[1]['quadros_distintos'],1)
        self.assertNotIn('clip',result[1]);self.assertNotIn('clip',result[2]);self.assertNotIn('clip',result[3])
        self.assertEqual(result[3]['status'],'pausa_economia');self.assertEqual(encoder.call_count,1)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg needed')
    def test_clip_is_real_playable_mp4_with_preserved_aspect_ratio(self):
        jpeg=subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=red:s=320x240','-frames:v','1','-threads','1','-f','image2pipe','-vcodec','mjpeg','pipe:1'],capture_output=True,check=True).stdout
        clip=LiveReview.encode([(0,jpeg),(1,jpeg),(2,jpeg)])
        self.assertIsNotNone(clip)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'clip.mp4';path.write_bytes(clip)
            raw=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_name,width,height','-of','json',str(path)],capture_output=True,check=True).stdout
            stream=json.loads(raw)['streams'][0]
            self.assertEqual((stream['width'],stream['height']),(640,360));self.assertEqual(stream['codec_name'],'h264')
