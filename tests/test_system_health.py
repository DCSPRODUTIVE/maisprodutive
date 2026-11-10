import tempfile
import unittest
from unittest.mock import patch,MagicMock
from pathlib import Path
from system_health import Outage
from watchdog import check

class OutageTests(unittest.TestCase):
    def test_five_active_minutes_alarm_recovery_and_economy_pause(self):
        state=Outage();key=('owner','cam')
        for now in range(0,300,5):self.assertIsNone(state.update(key,True,False,now))
        self.assertEqual(state.update(key,True,False,300),'outage')
        self.assertIsNone(state.update(key,True,False,305))
        self.assertEqual(state.update(key,True,True,310),'recovered')
        for now in range(315,1815,5):self.assertIsNone(state.update(key,False,False,now))
        self.assertEqual(state.rows[key]['bad'],0)
        self.assertIsNone(state.update(key,True,False,1815))

    def test_watchdog_requires_three_failures_and_requests_one_restart(self):
        with tempfile.TemporaryDirectory() as root,patch('watchdog.urllib.request.build_opener') as opener,patch('watchdog.TelegramAlerts') as alerts:
            opener.return_value.open.side_effect=OSError('offline')
            self.assertEqual(check(1,Path(root),True),1)
            self.assertEqual(check(1,Path(root),True),1)
            self.assertEqual(check(1,Path(root),True),2)
            self.assertEqual(check(1,Path(root),True),1)
            response=MagicMock();response.read.return_value=b'{"ok":true}'
            opener.return_value.open.side_effect=None;opener.return_value.open.return_value.__enter__.return_value=response
            self.assertEqual(check(1,Path(root),True),0)
