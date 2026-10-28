import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from reports import EventStore, ReportMonitor


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=EventStore(Path(self.tmp.name)/'reports')

    def test_owner_isolation_images_and_pagination(self):
        self.store.add('other','id','Private','person',b'private')
        for i in range(25):self.store.add('mine','id','Camera','person',b'jpeg',.9,boxes=[[0,0,.5,.5]])
        rows=self.store.list('mine');self.assertEqual(len(rows),24)
        self.assertNotIn('image',rows[0]);self.assertTrue(rows[0]['has_image'])
        self.assertEqual(len(self.store.list('mine',rows[-1]['id'])),1)
        self.assertIsNone(self.store.image('mine',1))
        self.assertEqual(self.store.image('other',1),b'private')
        self.assertEqual(rows[0]['boxes'],[[0,0,.5,.5]])

    def test_retention_age_and_account_limit(self):
        with patch('reports.time.time',return_value=1):self.store.add('mine','id','Old','person')
        self.store.add('mine','id','New','person')
        self.assertEqual(len(self.store.list('mine')),1)
        with self.store.connect() as db:
            db.executemany('INSERT INTO events(owner,camera,name,created,kind,boxes) VALUES (?,?,?,?,?,?)',
                           [('mine','id','Camera',time.time(),'person','[]')]*1000)
        self.store.add('mine','id','New','person')
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1000)

    def test_legacy_vehicles_are_hidden_and_new_vehicle_events_rejected(self):
        with self.store.connect() as db:
            db.execute('INSERT INTO events(owner,camera,name,created,kind,boxes,image) VALUES (?,?,?,?,?,?,?)',
                       ('mine','id','Camera',time.time(),'vehicle','[]',b'old-photo'))
        self.assertEqual(self.store.list('mine'),[])
        self.assertIsNone(self.store.image('mine',1))
        with self.assertRaises(ValueError):
            self.store.add('mine','id','Camera','vehicle',b'jpeg')
        self.store.add('mine','id','Camera','person',b'person-photo')
        self.assertEqual(self.store.list('mine')[0]['kind'],'person')

    def test_opened_events_are_hidden_and_preferences_survive_reopening(self):
        with self.store.connect() as db:
            db.execute('INSERT INTO events(owner,camera,name,created,kind,boxes) VALUES (?,?,?,?,?,?)',
                       ('mine','id','Camera',time.time(),'opened','[]'))
        self.assertEqual(self.store.list('mine'),[])
        with self.assertRaises(ValueError):self.store.add('mine','id','Camera','opened')
        values={'economy_ids':['id'], 'mosaic_limit':12}
        self.store.preferences('mine',values)
        reopened=EventStore(self.store.root)
        self.assertEqual(reopened.preferences('mine'),values)
        self.assertEqual(reopened.preferences('other'),{'economy_ids':[], 'detection_ids':[], 'mosaic_limit':8})

    def test_monitor_does_not_analyze_disabled_camera(self):
        stream=SimpleNamespace(report_owner='mine',device_id='id',report_detect=False,stopped=threading.Event())
        server=SimpleNamespace(stream_guard=threading.Lock(),active_streams=[stream])
        with patch('reports.readiness',return_value=(True,'ready')),patch('reports.Detector') as detector:
            monitor=ReportMonitor(server,self.store);monitor.start();time.sleep(.3);monitor.close()
            detector.return_value.detect.assert_not_called()
        self.assertEqual(self.store.list('mine'),[])

    def test_monitor_samples_fresh_frames_without_heartbeat_and_suppresses_duplicates(self):
        stream=SimpleNamespace(report_owner='mine',report_name='Camera',device_id='id',report_detect=True,
            condition=threading.Condition(),image=b'jpeg',last_frame=time.monotonic(),stopped=threading.Event())
        server=SimpleNamespace(stream_guard=threading.Lock(),active_streams={})
        server.active_streams=[stream]
        with patch('reports.readiness',return_value=(True,'ready')),patch('reports.RecordingService'),patch('reports.Detector') as detector:
            detector.return_value.detect.return_value=([{'kind':'person','confidence':.9,'box':[0,0,1,1]}, {'kind':'vehicle','confidence':.99,'box':[0,0,1,1]}],None)
            monitor=ReportMonitor(server,self.store);monitor.start()
            deadline=time.monotonic()+2
            while not self.store.list('mine') and time.monotonic()<deadline:time.sleep(.02)
            monitor.last.clear()
            time.sleep(.3);monitor.close()
        rows=self.store.list('mine');self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['kind'],'person')
        self.assertFalse(stream.stopped.is_set())

    def test_person_analysis_samples_new_frames_after_one_second(self):
        stream=SimpleNamespace(report_owner='mine',report_name='Camera',device_id='id',report_detect=True,
            condition=threading.Condition(),image=b'jpeg',last_frame=100.,stopped=threading.Event())
        server=SimpleNamespace(stream_guard=threading.Lock(),active_streams=[stream])
        with patch('reports.RecordingService'),patch('reports.readiness',return_value=(True,'ready')):
            monitor=ReportMonitor(server,self.store)
        from unittest.mock import Mock
        detector=Mock();detector.detect.return_value=([{'kind':'person','confidence':.9,'box':[0,0,1,1]}],None)
        with patch('reports.time.monotonic',return_value=100.):monitor.process(stream,detector)
        with patch('reports.time.monotonic',return_value=100.2):monitor.process(stream,detector)
        stream.last_frame=101.1
        with patch('reports.time.monotonic',return_value=101.1):monitor.process(stream,detector)
        self.assertEqual(detector.detect.call_count,2)
        self.assertEqual(len(self.store.list('mine')),1)
        self.assertEqual(stream.detection_health['people'],1)

    def test_bad_camera_frame_does_not_stop_other_camera_detection(self):
        def stream(device):
            return SimpleNamespace(report_owner='mine',report_name='Camera',device_id=device,report_detect=True,
                condition=threading.Condition(),image=device.encode(),last_frame=time.monotonic(),stopped=threading.Event())
        bad,good=stream('bad'),stream('good')
        server=SimpleNamespace(stream_guard=threading.Lock(),active_streams=[bad,good])
        def detect(image):
            if image==b'bad':raise ValueError('bad image')
            return [{'kind':'person','confidence':.9,'box':[0,0,1,1]}],None
        with patch('reports.readiness',return_value=(True,'ready')),patch('reports.RecordingService'),patch('reports.Detector') as detector:
            detector.return_value.detect.side_effect=detect
            monitor=ReportMonitor(server,self.store);monitor.start()
            deadline=time.monotonic()+2
            while not self.store.list('mine') and time.monotonic()<deadline:time.sleep(.02)
            monitor.close()
        self.assertEqual(self.store.list('mine')[0]['camera'],'good')
        self.assertTrue(bad.detection_health['error'])
        self.assertTrue(monitor.ready)

    def test_faces_are_checked_even_when_body_detector_misses_and_diagnostics_are_scoped(self):
        from unittest.mock import Mock
        stream=SimpleNamespace(report_owner='mine',report_name='Entrada',device_id='a',report_detect=True,
            condition=threading.Condition(),image=b'jpeg',last_frame=time.monotonic(),stopped=threading.Event())
        server=SimpleNamespace(stream_guard=threading.Lock(),active_streams=[stream])
        with patch('reports.RecordingService'),patch('reports.readiness',return_value=(True,'ready')):
            monitor=ReportMonitor(server,self.store)
        monitor.face_ready=True;monitor.faces.enabled('mine',True)
        engine=Mock();engine.extract.return_value=[(b'face',[1.0]+[0.0]*127)];engine.last_reason='Face found'
        monitor.face_engine=engine
        detector=Mock();detector.detect.return_value=([],object())
        monitor.process(stream,detector)
        self.assertEqual(len(monitor.faces.list('mine')),1)
        self.assertEqual(self.store.list('mine'),[])
        self.assertEqual(monitor.face_status('mine')[0]['captured'],1)
        self.assertEqual(monitor.face_status('other'),[])
        rows=monitor.face_status('mine',[{'id':'b','name':'Desativada'}],{'detection_ids':['a']})
        self.assertIn('desativado',rows[-1]['reason'])

    def test_face_runtime_failure_is_visible_without_stopping_person_reports(self):
        from unittest.mock import Mock
        stream=SimpleNamespace(report_owner='mine',report_name='Entrada',device_id='a',report_detect=True,
            condition=threading.Condition(),image=b'jpeg',last_frame=time.monotonic(),stopped=threading.Event())
        server=SimpleNamespace(stream_guard=threading.Lock(),active_streams=[stream])
        with patch('reports.RecordingService'),patch('reports.readiness',return_value=(True,'ready')):
            monitor=ReportMonitor(server,self.store)
        monitor.face_ready=True;monitor.faces.enabled('mine',True)
        engine=Mock();engine.extract.side_effect=RuntimeError('sensitive internal information')
        monitor.face_engine=engine
        detector=Mock();detector.detect.return_value=([{'kind':'person','confidence':.9,'box':[0,0,1,1]}],object())
        monitor.process(stream,detector)
        self.assertEqual(len(self.store.list('mine')),1)
        self.assertFalse(monitor.face_ready)
        diagnostic=monitor.face_status('mine')[0]
        self.assertIn('Falha',diagnostic['reason'])
        self.assertNotIn('sensitive',diagnostic['reason'])
