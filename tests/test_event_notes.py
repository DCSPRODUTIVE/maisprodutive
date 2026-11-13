import json
import tempfile
import time
import unittest
from unittest.mock import patch

from event_notes import EventNotes
from event_grouping import EventGrouping
from reports import EventStore


class NotesTests(unittest.TestCase):
    def test_user_annotations_lookup_and_reply_binding_are_owner_scoped_and_persistent(self):
        with tempfile.TemporaryDirectory() as root:
            store=EventStore(root);notes=EventNotes(store)
            event=store.add('owner','1','Portão','person',b'jpeg')
            self.assertIn('não verificado',notes.annotate('owner',event,'João'))
            self.assertEqual(store.list('owner')[0]['user_annotation'],'João')
            notes.bind('bot-secret','123',70,'owner',event)
            self.assertEqual(EventNotes(EventStore(root)).resolve('bot-secret','123',70,'owner'),event)
            for token,chat,owner in [('other','123','owner'),('bot-secret','456','owner'),('bot-secret','123','other')]:
                self.assertIsNone(notes.resolve(token,chat,70,owner))
            self.assertNotIn('bot-secret',(store.root/'events.sqlite3').read_bytes().decode('latin1'))
            self.assertIn('Portão',notes.lookup('owner','joão'))
            self.assertNotIn('João',notes.lookup('other'))
            with self.assertRaises(ValueError):notes.annotate('other',event,'Maria')
            new=store.add('owner','1','Portão','person',b'jpeg')
            self.assertEqual(store.list('owner')[0]['user_annotation'],'') # no inference for a new photo
            self.assertIn('1 anotação',notes.forget('owner','João'))
            self.assertIsNotNone(store.image('owner',event))

    def test_expired_event_cannot_be_annotated_or_replied_to(self):
        with tempfile.TemporaryDirectory() as root:
            store=EventStore(root);notes=EventNotes(store)
            event=store.add('owner','1','Portão','person',b'jpeg');notes.bind('bot','1',1,'owner',event)
            with patch('reports.time.time',return_value=time.time()+31*86400):store.cleanup()
            self.assertIsNone(notes.resolve('bot','1',1,'owner'))
            with self.assertRaises(ValueError):notes.annotate('owner',event,'João')


class GroupingTests(unittest.TestCase):
    def test_only_nearby_presence_notifications_group_not_dwell_or_other_cameras(self):
        groups=EventGrouping()
        self.assertIsNone(groups.group(('owner','1'),1,b'photo',['presence'],100))
        self.assertEqual(groups.group(('owner','1'),2,b'photo',['presence'],110),1)
        self.assertIsNone(groups.group(('owner','2'),3,b'photo',['presence'],110))
        self.assertIsNone(groups.group(('owner','1'),4,b'photo',['dwell'],111))
        self.assertIsNone(groups.group(('owner','1'),5,b'photo',['presence'],150))
