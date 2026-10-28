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

from camera_archive import CameraArchive
from frame_buffer import FrameBuffer
from reports import EventStore


class BufferTests(unittest.TestCase):
    def test_time_and_memory_bounds_and_order(self):
        buffer=FrameBuffer()
        for stamp in range(10):buffer.append(stamp,b'frame')
        self.assertEqual([s for s,_ in buffer.snapshot(9)],list(range(4,10)))
        with patch('frame_buffer.MAX_BYTES',12):
            buffer=FrameBuffer()
            for stamp in range(4):buffer.append(stamp,b'12345')
            self.assertEqual(buffer.size,10)
            self.assertEqual([s for s,_ in buffer.snapshot(3)],[2,3])
        buffer.clear();self.assertEqual(buffer.size,0)

    def test_video_survives_six_days_but_expires_after_fifteen(self):
        with tempfile.TemporaryDirectory() as directory:
            store=EventStore(directory);now=time.time()
            with patch('reports.time.time',return_value=now-6*86400):record=store.video_add('owner','id','Camera','a'*32+'.mp4')
            self.assertEqual(len(store.videos('owner')),1)
            with patch('reports.time.time',return_value=now+10*86400):self.assertEqual(store.videos('owner'),[])


class ArchiveFallbackTests(unittest.TestCase):
    def test_failed_export_preserves_original_and_respects_economy(self):
        with tempfile.TemporaryDirectory() as directory:
            store=EventStore(directory);filename='a'*32+'.mp4'
            record=store.video_add('owner','id','Camera',filename)
            folder=Path(directory)/'videos';folder.mkdir();(folder/filename).write_bytes(b'original')
            store.video_finish(record,'ready',120)
            slots=threading.BoundedSemaphore(1);archive=CameraArchive(store,slots)
            stream=SimpleNamespace(report_owner='owner',device_id='id',report_detect=True,archive_account=object(),monitor_until=float('inf'))
            try:
                with patch.object(archive,'export',return_value=None) as export:
                    archive.enqueue(record,stream,time.time()-125,time.time());archive.queue.join()
                    export.assert_called_once()
                self.assertEqual(store.video('owner',record).read_bytes(),b'original')
                self.assertEqual(store.videos('owner')[0]['archive_status'],'unavailable')
                self.assertTrue(slots.acquire(blocking=False));slots.release()
                stream.monitor_until=time.monotonic()-1
                with patch.object(archive,'export') as export:
                    archive.enqueue(record,stream,time.time()-125,time.time());archive.queue.join()
                    export.assert_not_called()
                self.assertEqual(store.videos('owner')[0]['archive_status'],'economy_or_disabled')
            finally:archive.close()


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
class OriginalCodecTests(unittest.TestCase):
    def test_original_h264_is_remuxed_without_lowering_fps(self):
        with tempfile.TemporaryDirectory() as directory:
            store=EventStore(directory);filename='a'*32+'.mp4'
            record=store.video_add('owner','id','Camera',filename)
            folder=Path(directory)/'videos';folder.mkdir();(folder/filename).write_bytes(b'local-fallback')
            store.video_finish(record,'ready',2)
            exported=Path(directory)/'sd.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=s=160x120:r=25','-t','2','-c:v','libx264','-threads','1',str(exported)],check=True,timeout=10)
            archive=CameraArchive(store,threading.BoundedSemaphore(1))
            try:
                self.assertTrue(archive.replace(record,'owner',exported,2))
                path=store.video('owner',record)
                info=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=avg_frame_rate','-of','json',str(path)],capture_output=True,check=True,timeout=5)
                self.assertEqual(json.loads(info.stdout)['streams'][0]['avg_frame_rate'],'25/1')
                self.assertEqual(store.videos('owner')[0]['source'],'sd')
                self.assertFalse((folder/filename).exists())
            finally:archive.close()

class ArchiveTimestampTests(unittest.TestCase):
    def test_export_requires_verified_timestamps_and_keeps_tokens_off_command_line(self):
        import io
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as directory:
            store=EventStore(directory);store.cleanup()
            archive=CameraArchive(store,threading.BoundedSemaphore(1))
            stream=SimpleNamespace(report_owner='owner',device_id='camera',report_detect=True,monitor_until=float('inf'),
                archive_account=SimpleNamespace(access_id='user',access_token='private-test-token'))
            start,end=1800000000.,1800000125.
            (Path(directory)/'archive.mp4').write_bytes(b'export')
            def process(metadata):
                child=MagicMock();child.poll.return_value=0;child.returncode=0
                child.stdin=io.BytesIO();child.stdout=io.BytesIO(metadata);return child
            try:
                with patch('camera_archive.video.readiness',return_value=(True,'')),patch.object(archive,'launch',return_value=process(b'SDTIME 1800000001000 1800000125000\n')) as launch:
                    path,pre_roll=archive.export(stream,start,end,directory)
                    self.assertEqual(path.name,'archive.mp4');self.assertEqual(pre_roll,4)
                    self.assertNotIn('private-test-token',repr(launch.call_args))
                with patch('camera_archive.video.readiness',return_value=(True,'')),patch.object(archive,'launch',return_value=process(b'SDTIME 1700000000000 1700000125000\n')):
                    with self.assertRaisesRegex(RuntimeError,'timestamp_unverified'):archive.export(stream,start,end,directory)
            finally:archive.close()
