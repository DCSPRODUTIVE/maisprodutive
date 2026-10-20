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

    def create_stream(self, expires=None):
        closed = []
        with patch('live.video.readiness', return_value=(True, '')):
            stream = LiveStream(DesktopAccount('123', 'live-token-test'), 'owned',
                                expires or time.monotonic()+10, lambda: closed.append(True))
        original = stream._launch
        launched = []
        def launch(args, **kwargs):
            self.assertNotIn('live-token-test', repr(args))
            self.assertNotIn('live-token-test', repr(kwargs))
            if args[-1] == '--stream':
                args = [sys.executable, '-u', '-c', self.source]
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
