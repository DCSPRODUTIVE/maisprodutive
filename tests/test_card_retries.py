import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from camera_archive import CameraArchive,MAX_CARD_ATTEMPTS
from reports import EventStore

class RetryBoundsTests(unittest.TestCase):
    def test_repeated_failure_is_limited_to_six_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            archive=CameraArchive(EventStore(directory),threading.BoundedSemaphore(1))
            stream=SimpleNamespace(report_detect=True,monitor_until=float('inf'))
            try:
                with patch.object(archive,'query_records',return_value=[{'start':1800000000,'end':1800000064}]),patch.object(archive,'export_piece',side_effect=RuntimeError('playback_unavailable')) as export,patch.object(archive.stopped,'wait',return_value=False):
                    with self.assertRaisesRegex(RuntimeError,'playback_unavailable'):archive.export(stream,1800000000,1800000064,directory)
                    self.assertEqual(export.call_count,MAX_CARD_ATTEMPTS)
                self.assertFalse(list(Path(directory).glob('piece-*')))
            finally:archive.close()

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
class ResumeTests(unittest.TestCase):
    def run_export(self,pause=False):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        archive=CameraArchive(EventStore(directory.name),threading.BoundedSemaphore(1));self.addCleanup(archive.close)
        stream=SimpleNamespace(report_detect=True,monitor_until=float('inf'))
        base=1800000000.;calls=[]
        def export(source,begin,end,folder,**kwargs):
            calls.append(begin)
            if len(calls)==1 and not pause:raise RuntimeError('playback_unavailable')
            last=min(end,begin+2)
            path=folder/'archive.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=blue:s=160x120:r=25','-t',str(last-begin),'-c:v','libx264','-threads','1',str(path)],check=True,timeout=10)
            source.archive_piece={'first':begin,'last':last,'partial':last<end}
            if pause:source.monitor_until=time.monotonic()
            return path,5
        with patch.object(archive,'query_records',return_value=[{'start':base,'end':base+64}]),patch.object(archive,'export_piece',side_effect=export),patch.object(archive.stopped,'wait',return_value=False):
            path,_=archive.export(stream,base,base+4,directory.name)
        self.assertTrue(path.exists())
        return stream,calls,path

    def test_recovers_after_failure_and_resumes_only_missing_interval(self):
        stream,calls,path=self.run_export()
        self.assertEqual(len(calls),3)
        self.assertEqual(calls[0],calls[1]);self.assertGreater(calls[2],calls[1]+2)
        self.assertFalse(stream.archive_partial);self.assertEqual(stream.archive_actual_end,1800000004)
        output=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(path)],capture_output=True,check=True,timeout=5)
        self.assertAlmostEqual(float(output.stdout),4,delta=.1)

    def test_economy_deadline_prevents_further_attempts_but_preserves_received_part(self):
        stream,calls,_=self.run_export(pause=True)
        self.assertEqual(len(calls),1);self.assertTrue(stream.archive_partial)
        self.assertEqual(stream.archive_actual_end,1800000002)
