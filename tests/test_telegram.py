import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from reports import EventStore
from telegram_alerts import TelegramAlerts

TOKEN = '123456789:' + 'A'*35


class TelegramTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.alerts = TelegramAlerts(EventStore(Path(self.temp.name)), 'https://cameras.example.com')

    def tearDown(self):
        self.alerts.close()
        self.temp.cleanup()

    def config(self):
        self.alerts.config('owner', {'enabled': True, 'token': TOKEN, 'chat_id': '12345'})

    def test_opt_in_validation_and_owner_isolation(self):
        self.assertFalse(self.alerts.enqueue('owner'))
        with self.assertRaises(ValueError):
            self.alerts.config('owner', {'enabled': True, 'token': TOKEN+'/evil', 'chat_id': '12345'})
        self.config()
        status=self.alerts.status('owner')
        self.assertNotIn(TOKEN,json.dumps(status))
        self.assertFalse(self.alerts.status('other')['configured'])
        self.alerts.config('owner', {'enabled':False,'token':'','chat_id':'12345'})
        self.assertEqual(self.alerts.config('owner')['token'],TOKEN)
        self.assertFalse(self.alerts.enqueue('owner'))

    @patch('telegram_alerts.urllib.request.build_opener')
    def test_photo_and_protected_reports_link(self, opener):
        import time
        self.config()
        opener.return_value.open.return_value.__enter__.return_value.read.return_value=b'{"ok":true}'
        self.alerts.deliver('owner','Portão',b'jpeg',.93,time.time())
        request=opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url,'https://api.telegram.org/bot'+TOKEN+'/sendPhoto')
        self.assertIn(b'jpeg', request.data)
        self.assertIn(b'https://cameras.example.com/reports#videos',request.data)
        self.assertNotIn(TOKEN.encode(),request.data)
        self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'],15)

    @patch('telegram_alerts.urllib.request.build_opener')
    def test_delivery_failure_is_sanitized_and_worker_survives(self, opener):
        self.config()
        opener.return_value.open.side_effect=RuntimeError(TOKEN)
        self.assertTrue(self.alerts.enqueue('owner'))
        self.alerts.jobs.join()
        status=self.alerts.status('owner')
        self.assertIn('falhou',status['message'])
        self.assertNotIn(TOKEN,json.dumps(status))
        self.assertTrue(self.alerts.thread.is_alive())
