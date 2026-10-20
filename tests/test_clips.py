import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from clips import Recorder, RecordingService
from reports import EventStore


class RetentionTests(unittest.TestCase):
    def test_photos_and_videos_have_separate_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            store=EventStore(directory)
            now=time.time()
            with patch('reports.time.time',return_value=now-6*86400):
                video_id=store.video_add('owner','id','Camera','a'*32+'.mp4')
                store.add('owner','id','Camera','person',b'photo')
            path=Path(directory)/'videos'/('a'*32+'.mp4');path.parent.mkdir();path.write_bytes(b'video')
            store.cleanup()
            self.assertFalse(path.exists());self.assertEqual(store.videos('owner'),[])
            self.assertEqual(len(store.list('owner')),1)
            with patch('reports.time.time',return_value=now+31*86400):store.cleanup()
            self.assertEqual(store.list('owner'),[])

    def test_disabled_camera_never_starts_recording(self):
        service=RecordingService(None)
        service.trigger(SimpleNamespace(report_owner='owner',device_id='id',report_detect=False))
        self.assertEqual(service.active,{})
        service.close()


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg tools required')
class EncoderTests(unittest.TestCase):
    def test_existing_jpeg_frames_become_playable_h264_clip(self):
        image=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=red:s=64x48',
            '-frames:v','1','-threads','1','-f','image2pipe','-vcodec','mjpeg','pipe:1'],capture_output=True,check=True,timeout=5).stdout
        with tempfile.TemporaryDirectory() as directory:
            store=EventStore(directory)
            stream=SimpleNamespace(report_owner='owner',device_id='id',report_name='Camera',report_detect=True,
                stopped=threading.Event(),condition=threading.Condition(),image=image,last_frame=time.monotonic())
            closed=[]
            with patch('clips.DURATION',2):
                recorder=Recorder(store,stream,lambda:closed.append(True));recorder.start();recorder.thread.join(timeout=8)
            self.assertFalse(recorder.thread.is_alive());self.assertEqual(closed,[True])
            row=store.videos('owner')[0];self.assertEqual(row['status'],'ready');self.assertGreater(row['duration'],1.5)
            path=store.video('owner',row['id']);self.assertIsNotNone(path)
            probe=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=codec_name','-of','csv=p=0',str(path)],capture_output=True,check=True,timeout=5)
            self.assertEqual(probe.stdout.strip(),b'h264')
            self.assertFalse(list((Path(directory)/'videos').glob('*.part.mp4')))

    def test_economy_pause_finishes_a_partial_clip(self):
        image=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','color=blue:s=64x48',
            '-frames:v','1','-threads','1','-f','image2pipe','-vcodec','mjpeg','pipe:1'],capture_output=True,check=True,timeout=5).stdout
        with tempfile.TemporaryDirectory() as directory:
            store=EventStore(directory)
            stream=SimpleNamespace(report_owner='owner',device_id='id',report_name='Camera',report_detect=True,
                stopped=threading.Event(),condition=threading.Condition(),image=image,last_frame=time.monotonic())
            with patch('clips.DURATION',10):
                recorder=Recorder(store,stream,lambda:None);recorder.start()
                time.sleep(.8);stream.stopped.set();recorder.thread.join(timeout=8)
            self.assertFalse(recorder.thread.is_alive())
            row=store.videos('owner')[0]
            self.assertEqual(row['status'],'partial')
            self.assertLess(row['duration'],10)
            self.assertIsNotNone(store.video('owner',row['id']))
