import unittest
from runtime_policy import startup_parallelism,encoder_parallelism

class ResourcePolicyTests(unittest.TestCase):
    def test_small_server_leaves_capacity_for_detection_and_streams(self):
        self.assertEqual((startup_parallelism(2),encoder_parallelism(2)),(1,1))
        self.assertEqual((startup_parallelism(4),encoder_parallelism(4)),(2,1))
        self.assertEqual((startup_parallelism(8),encoder_parallelism(8)),(3,2))
