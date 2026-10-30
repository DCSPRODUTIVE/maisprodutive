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
                    path,pre_roll=archive.export_piece(stream,start,end,directory)
                    self.assertEqual(path.name,'archive.mp4');self.assertEqual(pre_roll,4)
                    self.assertNotIn('private-test-token',repr(launch.call_args))
                with patch('camera_archive.video.readiness',return_value=(True,'')),patch.object(archive,'launch',return_value=process(b'SDTIME 1700000000000 1700000125000\n')):
                    with self.assertRaisesRegex(RuntimeError,'timestamp_unverified'):archive.export_piece(stream,start,end,directory)
            finally:archive.close()

class ManualArchiveTests(unittest.TestCase):
    def test_listing_job_is_private_and_cancelled_jobs_do_not_export(self):
        with tempfile.TemporaryDirectory() as directory:
            archive=CameraArchive(EventStore(directory),threading.BoundedSemaphore(1))
            try:
                with patch.object(archive,'list_records',return_value=[{'start':1800000000,'end':1800000060}]):
                    key=archive.submit('owner',object(),{'id':'camera','name':'Camera'},1800000000,1800000060,'list')
                    archive.queue.join()
                self.assertIsNone(archive.job('other',key))
                result=archive.job('owner',key)
                self.assertEqual(result['status'],'done');self.assertEqual(len(result['records']),1)
                self.assertNotIn('stream',result)
                archive.cancel('owner')
                self.assertFalse(archive.jobs[key]['stream'].report_detect)
            finally:archive.close()

    def test_bounded_listing_reads_all_records_without_a_pipe_deadlock(self):
        import io
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as directory:
            archive=CameraArchive(EventStore(directory),threading.BoundedSemaphore(1))
            stream=SimpleNamespace(report_detect=True,monitor_until=float('inf'),device_id='camera',
                archive_account=SimpleNamespace(access_id='user',access_token='private-test-token'))
            child=MagicMock();child.stdin=io.BytesIO();child.returncode=0;child.poll.return_value=0
            start=1800000000.
            payload=b'SDLIST\n'+b''.join(f'{round((start+i)*1000)} {round((start+i+1)*1000)}\n'.encode() for i in range(512))
            def launch(args,**kwargs):
                self.assertNotIn('private-test-token',repr(args))
                kwargs['stdout'].write(payload);kwargs['stdout'].flush()
                return child
            try:
                with patch('camera_archive.video.readiness',return_value=(True,'')),patch.object(archive,'launch',side_effect=launch):
                    records=archive.list_records(stream,start,start+600,directory)
                self.assertEqual(len(records),512)
                self.assertEqual(records[-1]['end'],start+512)
            finally:archive.close()

    def test_listing_failures_distinguish_rejection_timeout_and_callback_format(self):
        import io
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as directory:
            archive=CameraArchive(EventStore(directory),threading.BoundedSemaphore(1))
            stream=SimpleNamespace(report_detect=True,monitor_until=float('inf'),device_id='camera',
                archive_account=SimpleNamespace(access_id='user',access_token='test-token'))
            try:
                for code,reason in ((34,'list_unavailable'),(37,'list_request_rejected'),(38,'list_response_unsupported')):
                    child=MagicMock();child.stdin=io.BytesIO();child.returncode=code;child.poll.return_value=code
                    with self.subTest(code=code),patch('camera_archive.video.readiness',return_value=(True,'')),patch.object(archive,'launch',return_value=child):
                        with self.assertRaisesRegex(RuntimeError,'^'+reason+'$'):
                            archive.list_records(stream,1800000000,1800000060,directory)
            finally:archive.close()

class SegmentPlannerTests(unittest.TestCase):
    def test_detection_window_crosses_two_file_boundaries_without_losing_pre_roll(self):
        from camera_archive import playback_segments
        base=1800000000
        records=[{'start':base+i,'end':base+i+64} for i in (0,64,128)]
        self.assertEqual(playback_segments(records,base+60.125,base+185.125),
            [(base+60.125,base+64),(base+64,base+128),(base+128,base+185.125)])

    def test_gap_is_not_silently_joined_or_filled_with_old_frames(self):
        from camera_archive import playback_segments
        with self.assertRaisesRegex(RuntimeError,'recording_gap'):
            playback_segments([{'start':0,'end':64},{'start':65,'end':128}],60,100)

    def test_overlapping_files_use_the_same_latest_start_rule_as_native(self):
        from camera_archive import playback_segments
        self.assertEqual(playback_segments([{'start':0,'end':120},{'start':50,'end':70}],60,100),[(60,70),(70,100)])

    def test_fragment_limit_is_not_reported_as_a_gap(self):
        from camera_archive import playback_segments
        with self.assertRaisesRegex(RuntimeError,'archive_fragmented'):
            playback_segments([{'start':i,'end':i+1} for i in range(10)],0,10)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
class SegmentedExportTests(unittest.TestCase):
    def test_two_card_files_are_joined_preserving_real_fps(self):
        with tempfile.TemporaryDirectory() as directory:
            archive=CameraArchive(EventStore(directory),threading.BoundedSemaphore(1));start=1800000063.;end=start+2
            stream=SimpleNamespace(report_detect=True,monitor_until=float('inf'))
            intervals=[]
            def export_piece(stream,begin,finish,folder,overall_deadline,file_bounds):
                intervals.append((begin,finish))
                path=folder/'archive.mp4'
                color='red' if len(intervals)==1 else 'blue'
                subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'color={color}:s=160x120:r=25',
                    '-t',str(finish-begin),'-c:v','libx264','-threads','1',str(path)],check=True,timeout=10)
                return path,4.5
            try:
                records=[{'start':1800000000.,'end':1800000064.},{'start':1800000064.,'end':1800000128.}]
                with patch.object(archive,'list_records',return_value=records),patch.object(archive,'export_piece',side_effect=export_piece):
                    path,pre_roll=archive.export(stream,start,end,directory)
                self.assertEqual(intervals,[(start,start+1),(start+1,end)]);self.assertEqual(pre_roll,4.5)
                info=json.loads(subprocess.run(['ffprobe','-v','error','-show_entries','stream=avg_frame_rate:format=duration','-of','json',str(path)],check=True,capture_output=True,timeout=5).stdout)
                self.assertEqual(info['streams'][0]['avg_frame_rate'],'25/1')
                self.assertAlmostEqual(float(info['format']['duration']),2,delta=.1)
                raw=subprocess.run(['ffmpeg','-v','error','-ss','1.5','-i',str(path),'-frames:v','1','-threads','1','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],check=True,capture_output=True,timeout=5).stdout
                self.assertGreater(raw[2],200);self.assertLess(raw[0],20)
            finally:archive.close()


class ArchiveRevisionTests(unittest.TestCase):
    def test_natural_millisecond_file_boundary_is_not_a_missing_recording(self):
        from camera_archive import playback_segments
        base=1800000000.
        parts=playback_segments([{'start':base,'end':base+64.518},{'start':base+64.543,'end':base+128}],base+60,base+125)
        self.assertEqual(parts,[(base+60,base+64.518),(base+64.543,base+125)])
        self.assertAlmostEqual(65-sum(b-a for a,b in parts),.025,places=3)
        with self.assertRaisesRegex(RuntimeError,'recording_gap'):
            playback_segments([{'start':base,'end':base+64},{'start':base+64.251,'end':base+128}],base+60,base+125)

    def test_timeout_retry_is_bounded_and_economy_can_cancel_it(self):
        from camera_archive import ArchiveFailure
        with tempfile.TemporaryDirectory() as directory:
            archive=CameraArchive(EventStore(directory),threading.BoundedSemaphore(1))
            stream=SimpleNamespace(report_detect=True,monitor_until=float('inf'))
            try:
                result=[{'start':1800000000,'end':1800000064}]
                with patch.object(archive,'list_records',side_effect=[ArchiveFailure('list_incomplete'),result]) as query,patch.object(archive.stopped,'wait',return_value=False):
                    self.assertEqual(archive.query_records(stream,1800000000,1800000064,directory),result)
                    self.assertEqual(query.call_count,2)
                stream.monitor_until=time.monotonic()
                with patch.object(archive,'list_records',side_effect=ArchiveFailure('list_incomplete')) as query:
                    with self.assertRaisesRegex(RuntimeError,'economy_or_disabled'):archive.query_records(stream,1800000000,1800000064,directory)
                    self.assertEqual(query.call_count,1)
            finally:archive.close()

    def test_sanitized_diagnostic_persists_for_owner_without_vendor_output(self):
        from camera_archive import native_failure
        failure=native_failure(33,b'SDFAIL1 33 3 -1 0 0 0 0 12 0\n')
        self.assertEqual(failure.diagnostic['stage'],3);self.assertEqual(failure.diagnostic['frames'],12)
        self.assertEqual(native_failure(33,b'private-token vendor-output').diagnostic,{})
        with tempfile.TemporaryDirectory() as directory:
            store=EventStore(directory);archive=CameraArchive(store,threading.BoundedSemaphore(1))
            try:
                record=store.video_add('owner','id','Camera','a'*32+'.mp4')
                archive.status(record,'timestamp_unverified',failure.diagnostic)
                self.assertEqual(store.videos('owner')[0]['archive_diagnostic']['frames'],12)
                self.assertEqual(store.videos('other'),[])
            finally:archive.close()

    def test_known_file_export_reuses_bounds_without_another_lookup(self):
        import io
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as directory:
            store=EventStore(directory);archive=CameraArchive(store,threading.BoundedSemaphore(1))
            stream=SimpleNamespace(report_detect=True,monitor_until=float('inf'),device_id='camera',
                archive_account=SimpleNamespace(access_id='user',access_token='private-test-token'))
            (Path(directory)/'archive.mp4').write_bytes(b'export')
            child=MagicMock();child.poll.return_value=0;child.returncode=0
            child.stdin=io.BytesIO();child.stdout=io.BytesIO(b'SDTIME 1800000000000 1800000064000\n')
            try:
                with patch('camera_archive.video.readiness',return_value=(True,'')),patch.object(archive,'launch',return_value=child) as launch,patch.object(archive,'list_records') as lookup:
                    result=archive.export_piece(stream,1800000000,1800000064,directory,file_bounds=(1800000000,1800000064))
                    self.assertIsNotNone(result);lookup.assert_not_called()
                    self.assertEqual(launch.call_args.args[0][-1],'--archive-known')
                    self.assertNotIn('private-test-token',repr(launch.call_args))
            finally:archive.close()

    def test_partial_response_is_retried_once_and_complete_list_replaces_it(self):
        with tempfile.TemporaryDirectory() as directory:
            archive=CameraArchive(EventStore(directory),threading.BoundedSemaphore(1))
            stream=SimpleNamespace(report_detect=True,monitor_until=float('inf'))
            records=[{'start':1800000000,'end':1800000064}]
            count=[0]
            def query(*args):
                count[0]+=1;stream.archive_list_partial=count[0]==1
                return records if stream.archive_list_partial else records+[{'start':1800000064,'end':1800000128}]
            try:
                with patch.object(archive,'list_records',side_effect=query),patch.object(archive.stopped,'wait',return_value=False):
                    result=archive.query_records(stream,1800000000,1800000128,directory)
                self.assertEqual(count[0],2);self.assertEqual(len(result),2);self.assertFalse(stream.archive_list_partial)
            finally:archive.close()

    def test_automatic_failure_keeps_local_video_and_stores_diagnostic(self):
        from camera_archive import ArchiveFailure
        with tempfile.TemporaryDirectory() as directory:
            store=EventStore(directory);filename='a'*32+'.mp4';record=store.video_add('owner','camera','Camera',filename)
            path=Path(directory)/'videos'/filename;path.parent.mkdir();path.write_bytes(b'original-local')
            store.video_finish(record,'ready',120)
            archive=CameraArchive(store,threading.BoundedSemaphore(1))
            stream=SimpleNamespace(report_owner='owner',device_id='camera',report_detect=True,archive_account=object(),monitor_until=float('inf'))
            try:
                with patch.object(archive,'export',side_effect=ArchiveFailure('timestamp_unverified',{'stage':3,'frames':12})):
                    archive.enqueue(record,stream,1800000000,1800000120);archive.queue.join()
                self.assertEqual(store.video('owner',record).read_bytes(),b'original-local')
                row=store.videos('owner')[0];self.assertEqual(row['archive_status'],'timestamp_unverified')
                self.assertEqual(row['archive_diagnostic']['frames'],12)
            finally:archive.close()

class PartialProtocolTests(unittest.TestCase):
    def test_confirmed_partial_is_accepted_but_short_complete_and_wrong_dates_are_rejected(self):
        import io
        from unittest.mock import MagicMock
        with tempfile.TemporaryDirectory() as directory:
            archive=CameraArchive(EventStore(directory),threading.BoundedSemaphore(1))
            stream=SimpleNamespace(report_detect=True,monitor_until=float('inf'),device_id='camera',
                archive_account=SimpleNamespace(access_id='user',access_token='private-test-token'))
            (Path(directory)/'archive.mp4').write_bytes(b'export')
            try:
                for metadata,accepted in ((b'SDPART 1800000000000 1800000056762 1\n',True),
                    (b'SDPART 1800000005800 1800000056762 1 SETUP 5800\n',True),
                    (b'SDTIME 1800000000000 1800000056762\n',False),
                    (b'SDTIME 1800000005800 1800000063960 SETUP 5800\n',False),
                    (b'SDPART 1700000000000 1700000056762 1\n',False)):
                    child=MagicMock();child.poll.return_value=0;child.returncode=0
                    child.stdin=io.BytesIO();child.stdout=io.BytesIO(metadata)
                    with patch('camera_archive.video.readiness',return_value=(True,'')),patch.object(archive,'launch',return_value=child):
                        if accepted:
                            self.assertIsNotNone(archive.export_piece(stream,1800000000,1800000063.960,directory))
                            self.assertTrue(stream.archive_piece['partial'])
                            self.assertEqual(stream.archive_piece['record_setup_ms'],5800 if b'SETUP' in metadata else 0)
                        else:
                            with self.assertRaisesRegex(RuntimeError,'timestamp_unverified'):
                                archive.export_piece(stream,1800000000,1800000063.960,directory)
            finally:archive.close()


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
class PartialStorageTests(unittest.TestCase):
    def test_automatic_partial_is_downloadable_separately_and_does_not_replace_local(self):
        with tempfile.TemporaryDirectory() as directory:
            store=EventStore(directory);filename='a'*32+'.mp4';record=store.video_add('owner','camera','Camera',filename)
            original=Path(directory)/'videos'/filename;original.parent.mkdir();original.write_bytes(b'original-local')
            store.video_finish(record,'ready',64)
            partial=Path(directory)/'partial.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=blue:s=160x120:r=25',
                '-t','2','-c:v','libx264','-threads','1',str(partial)],check=True,timeout=10)
            archive=CameraArchive(store,threading.BoundedSemaphore(1))
            stream=SimpleNamespace(report_owner='owner',report_name='Camera',device_id='camera',report_detect=True,
                archive_account=object(),monitor_until=float('inf'))
            def export(*args):
                stream.archive_partial=True;stream.archive_actual_start=1800000000;stream.archive_actual_end=1800000002
                stream.archive_gap_seconds=0
                return partial,5
            try:
                with patch.object(archive,'export',side_effect=export):
                    archive.enqueue(record,stream,1800000000,1800000064);archive.queue.join()
                self.assertEqual(store.video('owner',record).read_bytes(),b'original-local')
                rows=store.videos('owner');self.assertEqual(len(rows),2)
                saved=next(r for r in rows if r['source']=='sd_partial')
                self.assertEqual(saved['status'],'partial');self.assertAlmostEqual(saved['duration'],2,delta=.1)
                self.assertEqual(saved['pre_roll'],5)
                self.assertEqual(saved['archive_start'],1800000000);self.assertEqual(saved['archive_end'],1800000002)
                self.assertIsNotNone(store.video('owner',saved['id']))
                self.assertEqual(next(r for r in rows if r['id']==record)['archive_status'],'partial_saved')
            finally:archive.close()
