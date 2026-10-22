import time
import threading
import unittest
from types import SimpleNamespace
from health import jpeg_size, snapshot

class HealthTests(unittest.TestCase):
    def test_geometry_and_measured_rate_without_exposing_private_state(self):
        jpeg=b'\xff\xd8\xff\xc0\x00\x0b\x08\x02\xd0\x05\x00\x01\x01\x11\x00\xff\xd9'
        self.assertEqual(jpeg_size(jpeg),[1280,720])
        self.assertIsNone(jpeg_size(jpeg[:8]))
        now=time.monotonic()
        stream=SimpleNamespace(condition=threading.Condition(),resolution=[1280,720],frame_times=[now-.2,now-.1,now],definition=1,
            detection_health={'analyzed_at':now-.5,'people':1},_payload=b'secret')
        result=snapshot(stream)
        self.assertEqual(result['fps'],10)
        self.assertEqual(result['resolution'],[1280,720])
        self.assertNotIn('analyzed_at',result['detection'])
        self.assertNotIn('_payload',result)
