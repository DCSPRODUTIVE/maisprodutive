import io
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from desktop import DesktopAccount
from live import LiveStream, jpeg_frames
from yoosee import IntegrationError


class ChunkPipe:
    def __init__(self, chunks): self.chunks = iter(chunks)
    def read1(self, size): return next(self.chunks, b'')


class JpegTests(unittest.TestCase):
    def test_split_markers_and_multiple_frames(self):
        frames = list(jpeg_frames(ChunkPipe([b'\xff', b'\xd8one\xff', b'\xd9\xff\xd8two\xff\xd9'])))
        self.assertEqual(frames, [b'\xff\xd8one\xff\xd9', b'\xff\xd8two\xff\xd9'])

    def test_truncated_garbage_and_oversized_images_are_rejected(self):
        for chunks in ([b'vendor-secret'], [b'\xff\xd8unfinished'], [b'\xff\xd8'+b'x'*32]):
            with self.subTest(chunks=chunks), patch('live.MAX_JPEG', 16):
                with self.assertRaises(IntegrationError) as error:
                    list(jpeg_frames(ChunkPipe(chunks)))
                self.assertNotIn('vendor-secret', str(error.exception))


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg needed for real local pipeline')
class LivePipelineTests(unittest.TestCase):
    # A local source produces changing synthetic YUV; no network or camera used.
    source = '''import sys,time
for i in range(3): sys.stdin.buffer.readline()
sys.stdout.buffer.write(b'YUV4MPEG2 W16 H16 F5:1 Ip A1:1 C420jpeg\\n')
for i in range(150):
 sys.stdout.buffer.write(b'FRAME\\n'+bytes([30+i%7*25])*256+b'\\x80'*128)
 sys.stdout.buffer.flush()
 time.sleep(.05)
'''

    def create_stream(self, expires=None, preview_width=960, source=None):
        closed = []
        with patch('live.video.readiness', return_value=(True, '')):
            stream = LiveStream(DesktopAccount('123', 'live-token-test'), 'owned',
                                expires or time.monotonic()+10, lambda: closed.append(True), preview_width=preview_width)
        original = stream._launch
        launched = []
        def launch(args, **kwargs):
            self.assertNotIn('live-token-test', repr(args))
            self.assertNotIn('live-token-test', repr(kwargs))
            if args[-1] == '--stream':
                args = [sys.executable, '-u', '-c', source or self.source]
            process = original(args, **kwargs)
            launched.append((process, kwargs.get('cwd')))
            return process
        stream._launch = launch
        return stream, closed, launched

    def test_changing_frames_share_one_pipeline_and_stop_cleans_processes(self):
        stream, closed, processes = self.create_stream()
        images, sequence = [], 0
        try:
            stream.start()
            limit = time.monotonic()+5
            while len(images)<3 and time.monotonic()<limit:
                data = stream.frame(sequence)
                if data['image']:
                    sequence = data['sequence']
                    images.append(data['image'])
            self.assertEqual(len(images), 3)
            self.assertGreater(len(set(images)), 1)
            self.assertEqual(len(processes), 2)
            self.assertIsNone(stream._payload)
            for p, _ in processes: self.assertIsNone(p.poll())
        finally:
            stream.stop()
        self.assertTrue(stream.done.is_set())
        self.assertEqual(closed, [True])
        self.assertIsNone(stream.image)
        for p, cwd in processes:
            self.assertIsNotNone(p.poll())
            if cwd: self.assertFalse(Path(cwd).exists())
        with self.assertRaises(IntegrationError): stream.frame(sequence)

    def test_original_preserves_source_resolution_while_mosaic_reduces_it(self):
        import base64
        source = """import sys,time
for i in range(3): sys.stdin.buffer.readline()
sys.stdout.buffer.write(b'YUV4MPEG2 W1280 H720 F5:1 Ip A1:1 C420jpeg\\n')
for i in range(40):
 sys.stdout.buffer.write(b'FRAME\\n'+bytes([90])*921600+b'\\x80'*460800)
 sys.stdout.buffer.flush()
 time.sleep(.1)
"""
        for width, expected in ((640, '640,360'), (0, '1280,720')):
            stream, _, _ = self.create_stream(preview_width=width, source=source)
            try:
                stream.start()
                limit = time.monotonic()+5
                image = None
                while not image and time.monotonic()<limit:
                    image = stream.frame(0)['image']
                self.assertIsNotNone(image)
                raw = base64.b64decode(image.split(',',1)[1])
                result = subprocess.run(['ffprobe','-v','error','-select_streams','v:0',
                    '-show_entries','stream=width,height','-of','csv=p=0','pipe:0'],
                    input=raw, capture_output=True, timeout=5, check=True)
                self.assertEqual(result.stdout.decode().strip(), expected)
            finally:
                stream.stop()

    def test_background_ignores_viewer_idle_and_session_expiry_but_respects_window(self):
        stream, closed, processes=self.create_stream(expires=time.monotonic()+.1)
        stream.background=True
        stream.monitor_until=time.monotonic()+1.2
        with patch('live.IDLE_TIMEOUT',.1):
            try:
                stream.start()
                self.assertFalse(stream.done.wait(.5))
                self.assertTrue(stream.done.wait(4))
                self.assertEqual(stream.error.kind,'video_stopped')
            finally:stream.stop()
        self.assertEqual(closed,[True])

    def test_idle_and_expired_sessions_stop_without_browser_requests(self):
        for kind in ('video_idle', 'authentication'):
            stream, closed, processes = self.create_stream(time.monotonic()+.1 if kind=='authentication' else None)
            with self.subTest(kind=kind), patch('live.IDLE_TIMEOUT', .1):
                try:
                    stream.start()
                    self.assertTrue(stream.done.wait(4))
                    self.assertEqual(stream.error.kind, kind)
                    self.assertEqual(closed, [True])
                finally:
                    stream.stop()
                self.assertTrue(all(p.poll() is not None for p, _ in processes))

    def test_frame_sequence_rejects_invalid_input(self):
        stream, _, _ = self.create_stream()
        for value in (-1, True, '0', None):
            with self.assertRaises(IntegrationError):stream.frame(value)


    def test_queued_camera_does_not_start_processes_or_consume_first_frame_timeout(self):
        gate = threading.BoundedSemaphore(1)
        gate.acquire()
        stream, closed, processes = self.create_stream()
        stream.startup_gate = gate
        with patch('live.FIRST_FRAME_TIMEOUT', .05):
            try:
                stream.start()
                self.assertEqual(stream.frame(0, wait=False)['state'], 'queued')
                self.assertFalse(stream.done.wait(.35))
                self.assertIsNone(stream.error)
                self.assertIsNone(stream.connect_started)
                self.assertEqual(processes, [])
            finally:
                stream.stop()
        self.assertEqual(closed, [True])
        self.assertFalse(gate.acquire(blocking=False))
        gate.release()

    def test_startup_slot_is_released_after_first_frame_while_stream_remains_open(self):
        gate = threading.BoundedSemaphore(1)
        one, _, _ = self.create_stream()
        two, _, _ = self.create_stream()
        one.startup_gate = two.startup_gate = gate
        try:
            one.start(); two.start()
            deadline = time.monotonic()+5
            while (not one.sequence or not two.sequence) and time.monotonic()<deadline:
                one.frame(0, wait=False);two.frame(0, wait=False)
                time.sleep(.03)
            self.assertGreater(one.sequence,0)
            self.assertGreater(two.sequence,0)
            self.assertFalse(one.stopped.is_set())
            self.assertFalse(two.stopped.is_set())
            self.assertTrue(gate.acquire(blocking=False))
            gate.release()
        finally:
            one.stop();two.stop()

    def test_eight_real_conversion_pipelines_keep_receiving_with_bounded_threads(self):
        source = '''import sys,time
for i in range(3):sys.stdin.buffer.readline()
sys.stdout.buffer.write(b'YUV4MPEG2 W640 H360 F5:1 Ip C420jpeg\\n')
for i in range(100):
 sys.stdout.buffer.write(b'FRAME\\n'+bytes([40+i%5*20])*(640*360)+b'\\x80'*(640*360//2))
 sys.stdout.buffer.flush()
 time.sleep(.2)
'''
        streams=[]
        with patch.object(self,'source',source):
            try:
                for _ in range(8):
                    stream,_,processes=self.create_stream(preview_width=640)
                    streams.append((stream,processes));stream.start()
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    for stream,_ in streams:stream.frame(0,wait=False)
                    if all(s.sequence>=2 for s,_ in streams):break
                    time.sleep(.05)
                self.assertTrue(all(s.sequence>=2 for s,_ in streams))
                self.assertTrue(all(s.error is None and not s.stopped.is_set() for s,_ in streams))
                for _,processes in streams:
                    encoder=processes[1][0]
                    path=Path(f'/proc/{encoder.pid}/status')
                    if path.exists():
                        threads=int(next(line.split(':')[1] for line in path.read_text().splitlines() if line.startswith('Threads:')))
                        self.assertLessEqual(threads,8)
            finally:
                for stream,_ in streams:stream.stop()


class EncoderDiagnosticTests(unittest.TestCase):
    def create_stream(self):
        with patch('live.video.readiness',return_value=(True,'')):
            return LiveStream(DesktopAccount('123','private-token'),'owned',time.monotonic()+10,lambda:None)

    def test_resource_error_is_classified_without_forwarding_stderr(self):
        stream=self.create_stream()
        stream._read_encoder_errors(ChunkPipe([b'private-token resource tempor',b'arily unavailable']))
        error=stream._pipeline_error(21,1)
        self.assertEqual(error.kind,'video_resources')
        self.assertNotIn('private-token',str(error))
        self.assertFalse(hasattr(stream,'stderr'))

    def test_encoder_exit_code_is_reported_instead_of_assuming_clean_native_exit(self):
        error=self.create_stream()._pipeline_error(0,1)
        self.assertIn('código 1',str(error))
        self.assertNotIn('interrompida antes',str(error))

@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
class WebcamPipelineTests(unittest.TestCase):
    def test_server_webcam_captures_without_sdk_and_stops_when_disabled(self):
        closed=[]
        with patch('live.webcam.device',return_value='/dev/video0'), patch('live.video.readiness',return_value=(False,'No SDK')):
            stream=LiveStream(None,'webcam:video0',time.monotonic()+10,lambda:closed.append(True),local_device=True)
        original=stream._launch
        def launch(args,**kwargs):
            self.assertIn('/dev/video0',args)
            return original([shutil.which('ffmpeg'),'-v','error','-re','-f','lavfi','-i','testsrc2=s=640x480:r=10',
                '-threads','1','-f','image2pipe','-vcodec','mjpeg','pipe:1'],**kwargs)
        stream._launch=launch;stream.report_detect=True
        try:
            stream.start();limit=time.monotonic()+4
            while stream.sequence<2 and time.monotonic()<limit:time.sleep(.05)
            self.assertGreaterEqual(stream.sequence,2)
            image,sequence=stream.jpeg_frame(0)
            self.assertTrue(image.startswith(b'\xff\xd8'))
            self.assertTrue(stream.history.snapshot(time.monotonic()))
            self.assertEqual(stream.resolution,[640,480])
        finally:stream.stop()
        self.assertEqual(closed,[True]);self.assertTrue(stream.done.is_set())
        self.assertTrue(all(p.poll() is not None for p in stream.processes))
