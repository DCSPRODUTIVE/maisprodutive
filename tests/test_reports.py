import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from reports import EventStore, ReportMonitor, plate_candidate


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=EventStore(Path(self.tmp.name)/'reports')

    def test_owner_isolation_images_and_pagination(self):
        self.store.add('other','id','Private','person',b'private')
        for i in range(25):self.store.add('mine','id','Camera','vehicle',b'jpeg',.9,boxes=[[0,0,.5,.5]])
        rows=self.store.list('mine');self.assertEqual(len(rows),24)
        self.assertNotIn('image',rows[0]);self.assertTrue(rows[0]['has_image'])
        self.assertEqual(len(self.store.list('mine',rows[-1]['id'])),1)
        self.assertIsNone(self.store.image('mine',1))
        self.assertEqual(self.store.image('other',1),b'private')
        self.assertEqual(rows[0]['boxes'],[[0,0,.5,.5]])

    def test_retention_age_and_account_limit(self):
        with patch('reports.time.time',return_value=1):self.store.add('mine','id','Old','opened')
        self.store.add('mine','id','New','opened')
        self.assertEqual(len(self.store.list('mine')),1)
        with self.store.connect() as db:
            db.executemany('INSERT INTO events(owner,camera,name,created,kind,boxes) VALUES (?,?,?,?,?,?)',
                           [('mine','id','Camera',time.time(),'opened','[]')]*1000)
        self.store.add('mine','id','New','opened')
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1000)

    def test_plate_candidates_are_suggestions_with_brazilian_patterns(self):
        self.assertEqual(plate_candidate('ABC1D23'),'ABC1D23')
        self.assertEqual(plate_candidate('XYZ-1234'),'XYZ-1234')
        self.assertIsNone(plate_candidate('TEXT 123'))
        self.assertIsNone(plate_candidate('XABC1D23Y'))

    def test_monitor_samples_fresh_frames_without_heartbeat_and_suppresses_duplicates(self):
        stream=SimpleNamespace(report_owner='mine',report_name='Camera',device_id='id',
            condition=threading.Condition(),image=b'jpeg',last_frame=time.monotonic(),stopped=threading.Event())
        server=SimpleNamespace(stream_guard=threading.Lock(),active_streams={})
        server.active_streams=[stream]
        with patch('reports.readiness',return_value=(True,'ready')),patch('reports.Detector') as detector:
            detector.return_value.detect.return_value=([{'kind':'person','confidence':.9,'box':[0,0,1,1]}],None)
            monitor=ReportMonitor(server,self.store);monitor.start()
            deadline=time.monotonic()+2
            while not self.store.list('mine') and time.monotonic()<deadline:time.sleep(.02)
            monitor.last.clear()
            time.sleep(.3);monitor.close()
        rows=self.store.list('mine');self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['kind'],'person')
        self.assertFalse(stream.stopped.is_set())
