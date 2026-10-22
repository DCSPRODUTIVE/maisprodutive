import math
import tempfile
import time
import unittest
from unittest.mock import patch

from faces import FaceStore, identify, vector
from reports import EventStore


def feature(index):
    return [float(i==index) for i in range(128)]


class FaceLearningTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.store=FaceStore(EventStore(self.directory.name))
        self.store.enabled('mine',True)

    def test_enrollment_changes_future_matches_but_does_not_self_train(self):
        self.assertFalse(self.store.enabled('new-account'))
        self.store.enabled('mine',True)
        self.store.add('mine','a','Entrada',b'crop',feature(0))
        row=self.store.list('mine')[0]
        self.assertEqual(row['state'],'unrecognized')
        self.store.label('mine',row['id'],'Ana')
        self.store.add('mine','b','Garagem',b'new crop',feature(0))
        result=self.store.list('mine')[0]
        self.assertEqual(result['state'],'known');self.assertEqual(result['name'],'Ana')
        self.assertEqual(result['label'],'')
        self.assertNotIn('embedding',result)
        self.assertEqual(result['camera_name'],'Garagem')
        self.store.label('mine',row['id'],'')
        self.assertEqual(self.store.list('mine')[0]['state'],'unrecognized')

    def test_owner_isolation_correction_deletion_and_clear(self):
        self.store.add('mine','a','Entrada',b'private',feature(0))
        row=self.store.list('mine')[0]
        self.assertIsNone(self.store.image('other',row['id']))
        with self.assertRaises(ValueError):self.store.label('other',row['id'],'Ana')
        self.store.label('mine',row['id'],'Ana')
        self.store.label('mine',row['id'],'Bia')
        self.assertEqual(self.store.list('mine')[0]['label'],'Bia')
        self.store.delete('other',row['id']);self.assertEqual(len(self.store.list('mine')),1)
        self.store.clear('mine');self.assertEqual(self.store.list('mine'),[])
        self.assertFalse(self.store.enabled('mine'))

    def test_duplicate_capture_retention_and_named_examples_persist(self):
        self.store.add('mine','a','Entrada',b'crop',feature(0))
        self.store.add('mine','a','Entrada',b'crop2',feature(0))
        self.assertEqual(len(self.store.list('mine')),1)
        row=self.store.list('mine')[0];self.store.label('mine',row['id'],'Ana')
        self.store.add('mine','a','Entrada',b'unknown',feature(1))
        with patch('faces.time.time',return_value=time.time()+31*86400):
            rows=self.store.list('mine')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['label'],'Ana')

    def test_ambiguous_or_distant_faces_remain_unrecognized(self):
        query=vector([1,1]+[0]*126)
        result=identify(query,[('Ana',feature(0)),('Bia',feature(1))])
        self.assertEqual(result['state'],'unrecognized')
        self.assertEqual(identify(feature(2),[('Ana',feature(0))])['state'],'unrecognized')
        self.assertEqual(identify(feature(0),[('Ana',feature(0)),('Ana',feature(1))])['state'],'known')
        for bad in ([],[math.nan]*128,[0]*128):
            with self.assertRaises(ValueError):vector(bad)


class FaceQualityTests(unittest.TestCase):
    def test_only_sharp_large_faces_create_crops_and_normalized_descriptors(self):
        try:
            import cv2
            import numpy as np
        except ImportError:self.skipTest('OpenCV and NumPy required for crop quality test')
        from faces import FaceEngine
        from unittest.mock import Mock
        engine=FaceEngine.__new__(FaceEngine);engine.cv=cv2
        engine.detector=Mock();engine.recognizer=Mock()
        face=np.array([10,10,80,80]+[20,20,70,20,45,40,25,70,65,70]+[.99],dtype=np.float32)
        engine.detector.detect.return_value=(None,np.array([face]))
        frame=np.random.default_rng(42).integers(50,200,(100,100,3),dtype=np.uint8)
        engine.recognizer.feature.return_value=np.array([feature(0)],dtype=np.float32)
        crops=engine.extract(frame,[[0,0,1,1]])
        self.assertEqual(len(crops),1)
        self.assertEqual(crops[0][1],feature(0))
        self.assertGreater(len(crops[0][0]),100)
        self.assertEqual(engine.extract(np.full((100,100,3),128,dtype=np.uint8),[[0,0,1,1]]),[])
        face[2:4]=30
        engine.detector.detect.return_value=(None,np.array([face]))
        self.assertEqual(engine.extract(frame,[[0,0,1,1]]),[])
