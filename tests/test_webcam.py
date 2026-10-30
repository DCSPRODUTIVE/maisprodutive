import unittest
from unittest.mock import patch
import webcam

class WebcamTests(unittest.TestCase):
    def test_only_enumerated_server_devices_are_accepted(self):
        with patch('webcam.cameras',return_value=[{'id':'webcam:video0'}]):
            self.assertEqual(webcam.device('webcam:video0'),'/dev/video0')
            for invalid in ('/dev/video0','webcam:../../etc/passwd','webcam:video1',None):
                with self.subTest(invalid=invalid),self.assertRaises(ValueError):webcam.device(invalid)
