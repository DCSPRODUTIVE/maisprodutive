import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from archive_frames import read_frames,capture

START=1800000000

def packet(offset,fill=128):
    data=bytes([fill])*384
    return f'DCSYUV1 16 16 {round((START+offset)*1000)} 384\n'.encode()+data

class FrameReaderTests(unittest.TestCase):
    def test_camera_timestamps_survive_irregular_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            rows=read_frames(io.BytesIO(packet(.2)+packet(.7)+packet(1.5)),directory,START,START+3,lambda *args:b'jpeg')
            self.assertEqual([round(stamp-START,2) for stamp,_ in rows],[.2,.7,1.5])
            self.assertEqual(len(list(Path(directory).glob('*.jpg'))),3)

    def test_wrong_dates_nonmonotonic_and_oversized_data_are_rejected(self):
        for data in (packet(-10),packet(0)+packet(1)+packet(.5),b'DCSYUV1 4096 4096 1800000000000 25165824\n'):
            with self.subTest(data=data[:70]),tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(RuntimeError,'timestamp_unverified|invalid_video'):
                    read_frames(io.BytesIO(data),directory,START,START+10,lambda *args:b'jpeg')

    def test_large_gap_and_truncated_final_frame_preserve_only_valid_prefix(self):
        for tail in (packet(5),packet(1.5)[:-100]):
            with tempfile.TemporaryDirectory() as directory:
                rows=read_frames(io.BytesIO(packet(0)+packet(1)+tail),directory,START,START+10,lambda *args:b'jpeg')
                self.assertEqual(len(rows),2)
                self.assertEqual(rows[-1][0],START+1)

try:import cv2,numpy
except ImportError:cv2=numpy=None

@unittest.skipUnless(cv2 and shutil.which('ffmpeg') and shutil.which('ffprobe'),'OpenCV and FFmpeg required')
class FrameCaptureTests(unittest.TestCase):
    def test_real_mp4_preserves_playback_clock_and_partial_interval(self):
        from camera_archive import CameraArchive
        from reports import EventStore
        with tempfile.TemporaryDirectory() as directory:
            archive=CameraArchive(EventStore(directory),threading.BoundedSemaphore(1))
            original=archive.launch;launched=[]
            def launch(args,**kwargs):
                if args[-1]=='--archive-frames-known':
                    # Fictitious SDK playback begins late and has variable intervals.
                    script="import sys;sys.stdin.buffer.read();"+"sys.stdout.buffer.write("+repr(packet(.5,80)+packet(1,128)+packet(2,180))+ ");sys.stdout.buffer.flush()"
                    args=[sys.executable,'-c',script]
                result=original(args,**kwargs);launched.append(result);return result
            archive.launch=launch
            stream=SimpleNamespace(report_detect=True,monitor_until=float('inf'),archive_account=object())
            try:
                result=capture(archive,stream,START,START+5,Path(directory),'private-token\n',{},time.monotonic()+15)
                self.assertTrue(result[0].is_file());self.assertTrue(stream.archive_piece['partial'])
                self.assertEqual(stream.archive_piece['first'],START+.5)
                self.assertEqual(stream.archive_piece['last'],START+2)
                self.assertEqual(stream.archive_piece['frame_count'],3)
                self.assertTrue(archive.probe_piece(result[0],1.5))
                self.assertTrue(all(child.poll() is not None for child in launched))
            finally:archive.close()

    def test_unavailable_file_list_falls_back_to_clock_checked_playback(self):
        from camera_archive import CameraArchive,ArchiveFailure
        from reports import EventStore
        with tempfile.TemporaryDirectory() as directory:
            archive=CameraArchive(EventStore(directory),threading.BoundedSemaphore(1))
            original=archive.launch;modes=[]
            def launch(args,**kwargs):
                self.assertNotIn('private-test-token',repr(args))
                if args[-1]=='--archive-frames':
                    modes.append(args[-1]);script="import sys;sys.stdin.buffer.read();sys.stdout.buffer.write("+repr(packet(.5,80)+packet(1,128)+packet(2,180))+");sys.stdout.buffer.flush()"
                    args=[sys.executable,'-c',script]
                return original(args,**kwargs)
            archive.launch=launch
            stream=SimpleNamespace(device_id='camera',report_detect=True,monitor_until=float('inf'),archive_account=SimpleNamespace(access_id='owner',access_token='private-test-token'))
            try:
                with patch.object(archive,'query_records',side_effect=ArchiveFailure('list_incomplete')),patch('camera_archive.video.readiness',return_value=(True,'')),patch('camera_archive.MAX_CARD_ATTEMPTS',1):
                    result=archive.export(stream,START,START+5,Path(directory))
                self.assertTrue(result[0].is_file());self.assertTrue(stream.archive_partial)
                self.assertEqual(stream.archive_actual_start,START+.5)
                self.assertEqual(stream.archive_actual_end,START+2)
                self.assertEqual(modes,['--archive-frames'])
            finally:archive.close()

class DeadlineTests(unittest.TestCase):
    def test_silent_pipe_never_blocks_archive_worker_past_deadline(self):
        import os
        from archive_frames import BoundedPipe
        read,write=os.pipe()
        try:
            with os.fdopen(read,'rb',buffering=0) as pipe:
                archive=SimpleNamespace(stopped=threading.Event(),allowed=lambda stream:True)
                before=time.monotonic();bounded=BoundedPipe(pipe,archive,None,before+.05)
                self.assertEqual(bounded.readline(160),b'')
                self.assertLess(time.monotonic()-before,1)
        finally:os.close(write)
