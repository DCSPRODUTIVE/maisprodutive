import threading
import unittest
from types import SimpleNamespace

from background import BackgroundMonitor
from desktop import DesktopAccount
from yoosee import IntegrationError


class FakeNative:
    def __init__(self, entry, clock):
        self.device_id, self.report_owner = entry.device_id, entry.owner
        self.report_name, self.report_detect = entry.name, True
        self.background = True
        self.preview_width, self.definition = entry.width, entry.definition
        self.stopped = threading.Event()
        self.condition = threading.Condition()
        self.image = b'jpeg'
        self.sequence = 1
        self.last_frame = clock()
        self.connect_started = clock()
        self.error = None
    def stop(self, wait=True):
        self.stopped.set();self.image=None


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.now=1000.
        self.created=[]
        self.account=DesktopAccount('id','test-token')
        def factory(entry):
            stream=FakeNative(entry,lambda:self.now);self.created.append(stream);return stream
        self.manager=BackgroundMonitor(factory,lambda:[],clock=lambda:self.now)
        self.addCleanup(self.manager.close)
        self.devices=[{'id':'a','name':'Camera A'},{'id':'b','name':'Camera B'}]

    def configure(self,economy=True):
        self.manager.configure('owner',self.account,self.devices,{'detection_ids':['a'],'economy_ids':['a'] if economy else []})

    def test_economy_runs_without_browser_and_pauses_for_twenty_five_minutes(self):
        self.configure();self.manager.tick()
        first=self.created[0]
        self.assertFalse(first.stopped.is_set())
        self.now+=299;self.manager.tick();self.assertEqual(len(self.created),1)
        self.now+=1;self.manager.tick();self.assertTrue(first.stopped.is_set())
        frame=self.manager.frame('owner','a',0)
        self.assertEqual(frame['state'],'paused');self.assertEqual(frame['next_open_seconds'],1500)
        self.assertIsNotNone(frame['image'])
        self.now+=1499;self.manager.tick();self.assertEqual(len(self.created),1)
        self.now+=1;self.manager.tick();self.assertEqual(len(self.created),2)
        self.assertFalse(self.created[1].stopped.is_set())

    def test_reopening_browser_preserves_schedule_and_shares_connection(self):
        self.configure();self.manager.tick()
        view1=self.manager.view('owner','a',640,0)
        view1.stop()
        self.assertFalse(self.created[0].stopped.is_set())
        self.now+=400;self.manager.tick()
        self.configure() # A second access loads the same preferences.
        view2=self.manager.view('owner','a',640,0)
        self.manager.tick()
        self.assertEqual(len(self.created),1)
        self.assertEqual(view2.frame(0)['state'],'paused')
        self.assertEqual(view2.frame(0)['next_open_seconds'],1400)

    def test_native_failures_retry_inside_window_but_never_during_pause(self):
        self.configure();self.manager.tick()
        self.created[0].error=IntegrationError('video_timeout','No frame')
        self.created[0].stop()
        self.manager.tick();self.now+=5;self.manager.tick()
        self.assertEqual(len(self.created),2)
        self.now=1299
        self.created[1].stop();self.manager.tick()
        self.now=1300;self.manager.tick()
        self.now=1400;self.manager.tick();self.assertEqual(len(self.created),2)
        self.now=2800;self.manager.tick();self.assertEqual(len(self.created),3)

    def test_disabling_detection_or_logging_out_stops_native(self):
        self.configure(False);self.manager.tick()
        stream=self.created[0]
        self.manager.configure('owner',self.account,self.devices,{'detection_ids':[],'economy_ids':[]})
        self.assertTrue(stream.stopped.is_set());self.manager.tick();self.assertEqual(len(self.created),1)
        self.configure(False);self.manager.tick()
        self.manager.remove('owner');self.assertTrue(self.created[-1].stopped.is_set())
        self.assertEqual(self.manager.status('owner')['configured'],0)

    def test_unenabled_camera_is_not_opened_and_quality_does_not_reset_window(self):
        self.configure();self.manager.tick()
        self.now+=200
        self.manager.view('owner','a',0,2)
        self.manager.tick()
        self.assertEqual(len(self.created),2)
        self.now+=100;self.manager.tick()
        self.assertTrue(self.created[-1].stopped.is_set())
        with self.assertRaises(IntegrationError):self.manager.view('owner','b',640,0)

    def test_independent_watchdog_recovers_stale_source_without_resetting_economy(self):
        self.configure();self.manager.tick()
        first=self.created[0];first.managed_watchdog=True
        self.now+=9;self.manager.tick()
        self.assertTrue(first.stopped.is_set())
        self.now+=2;self.manager.tick()
        self.assertEqual(len(self.created),2)
        self.now=1300;self.manager.tick()
        self.assertTrue(self.created[-1].stopped.is_set())
        self.assertEqual(self.manager.frame('owner','a',0)['state'],'paused')

    def test_webcam_requires_explicit_enable_and_can_run_without_detection(self):
        devices=[{'id':'webcam:video0','name':'Servidor','local':True}]
        self.manager.configure('owner',self.account,devices,{'detection_ids':['webcam:video0']})
        self.manager.tick();self.assertEqual(len(self.created),0)
        self.manager.configure('owner',self.account,devices,{'webcam_enabled_ids':['webcam:video0'],'detection_ids':[]})
        self.manager.tick();self.assertEqual(len(self.created),1)
        self.assertFalse(self.manager.entries[('owner','webcam:video0')].detection)
        self.manager.configure('owner',self.account,devices,{'webcam_enabled_ids':[]})
        self.assertTrue(self.created[0].stopped.is_set())
