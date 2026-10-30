import json
import tempfile
import unittest
from diagnostics import Diagnostics
from reports import EventStore

class DiagnosticHistoryTests(unittest.TestCase):
    def test_events_are_scoped_persistent_and_never_store_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            store=EventStore(directory);log=Diagnostics(store)
            try:
                log.record('owner','123','connection_lost',code='video_stale',frames=5,password='private-password',token='private-token',message='private-token')
                log.record('other','999','camera_state',state='receiving')
                log.pending.join()
                events,counts=log.history('owner')
                raw=json.dumps((events,counts));self.assertNotIn('999',raw);self.assertNotIn('private',raw)
                self.assertEqual({k:v for k,v in events[0]['details'].items() if k!='load1'},{'code':'video_stale','frames':5})
            finally:log.close()
            reloaded=Diagnostics(store)
            try:self.assertEqual(len(reloaded.history('owner')[0]),1)
            finally:reloaded.close()

    def test_arbitrary_vendor_messages_and_codes_are_not_collected(self):
        with tempfile.TemporaryDirectory() as directory:
            log=Diagnostics(EventStore(directory))
            try:
                log.record('owner','123','source_closed',code='private-token',state={'password':'secret'},image=b'jpeg',frames=1)
                log.record('owner','123','untrusted-event',code='video_stale')
                log.pending.join();events,_=log.history('owner')
                self.assertEqual(len(events),1);self.assertEqual(events[0]['details'],{'frames':1})
            finally:log.close()

    def test_open_failures_and_recorder_setup_are_retained_without_vendor_text(self):
        with tempfile.TemporaryDirectory() as directory:
            log=Diagnostics(EventStore(directory))
            try:
                log.record('owner','123','connection_failed',code='video_timeout')
                log.record('owner','123','card_attempt_result',record_setup_ms=5800,message='private-vendor-text')
                log.pending.join();events,counts=log.history('owner')
                self.assertIn('connection_failed',[event['event'] for event in events])
                self.assertTrue(any(event['details'].get('record_setup_ms')==5800 for event in events))
                self.assertNotIn('private-vendor-text',json.dumps(events))
            finally:log.close()
