import os
from pathlib import Path
import tempfile
import unittest
from runtime_health import snapshot

class RuntimeHealthTests(unittest.TestCase):
    def test_numeric_pressure_and_process_totals_do_not_read_private_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);pid=os.getpid();proc=root/str(pid)
            (proc/'task'/str(pid)).mkdir(parents=True)
            (proc/'status').write_text('Name: private-name\nVmRSS: 2048 kB\nThreads: 9\n')
            (proc/'cmdline').write_bytes(b'private-token-and-password')
            (proc/'task'/str(pid)/'children').write_text('99999')
            child=root/'99999';child.mkdir();(child/'status').write_text('VmRSS: 1024 kB\nThreads: 3\n')
            (root/'uptime').write_text('123.5 300.0')
            (root/'vmstat').write_text('oom_kill 2\n')
            (root/'pressure').mkdir();(root/'pressure'/'cpu').write_text('some avg10=76.5 avg60=4 total=500\n')
            result=snapshot(root)
            self.assertEqual(result['known_rss_mib'],3)
            self.assertEqual(result['known_process_threads'],12)
            self.assertEqual(result['oom_kills_since_boot'],2)
            self.assertEqual(result['cpu_some_pressure_avg10'],76.5)
            self.assertTrue(all(type(value) in (int,float) for value in result.values()))
            self.assertNotIn('private',str(result))
