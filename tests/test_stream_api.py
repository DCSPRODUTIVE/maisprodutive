import json
import threading
import time
import types
import tempfile
from reports import EventStore
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from desktop import DesktopAccount, DesktopClient, DesktopProfile
from server import Workbench
from yoosee import IntegrationError


class FakeStream:
    instances = []
    def __init__(self, account, device_id, expires, on_close, preview_width=960, definition=0):
        self.definition = definition
        self.preview_width = preview_width
        self.device_id, self.expires, self.callback = device_id, expires, on_close
        self.handle = 'local-handle-'+device_id+'-'+str(len(self.instances))
        self.stopped = threading.Event()
        self.worker = types.SimpleNamespace(ident=1)
        self.instances.append(self)
    def start(self): pass
    def stop(self, wait=True):
        if not self.stopped.is_set():
            self.stopped.set()
            self.callback()
    def frame(self, after, wait=True):
        if self.stopped.is_set(): raise IntegrationError('video_stopped','stopped')
        return {'device_id':self.device_id,'sequence':1,'image':'data:image/jpeg;base64,test','age_seconds':0,'state':'receiving'}


class StreamApiTests(unittest.TestCase):
    def setUp(self):
        FakeStream.instances=[]
        self.report_tmp=tempfile.TemporaryDirectory()
        self.store_patch=patch('server.EventStore', return_value=EventStore(self.report_tmp.name))
        self.store_patch.start()
        self.patch=patch('server.LiveStream',FakeStream);self.patch.start()
        self.server=Workbench(('127.0.0.1',0))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.cookie,self.csrf,self.state=self.new_session()
        client=DesktopClient(DesktopProfile('a'*32,'b'*64))
        client.account=DesktopAccount('123','private-account-token')
        client.device_ids={str(i) for i in range(9)}
        self.state['client']=client
        self.state['devices']=[{'id':str(i),'name':'Camera '+str(i)} for i in range(9)]
    def new_session(self):
        with urllib.request.urlopen(self.base+'/api/status') as r:
            status=json.load(r);cookie=r.headers['Set-Cookie'].split(';')[0]
        return cookie,status['csrf'],self.server.sessions[cookie.split('=',1)[1]]
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.patch.stop();self.store_patch.stop();self.report_tmp.cleanup()
    def post(self,path,body,cookie=None,csrf=None):
        headers={'Cookie':cookie or self.cookie,'X-CSRF-Token':csrf or self.csrf,'Origin':self.base,'Content-Type':'application/json'}
        request=urllib.request.Request(self.base+path,data=json.dumps(body).encode(),headers=headers)
        try:
            with urllib.request.urlopen(request,timeout=4) as r:code,raw=r.status,r.read()
        except urllib.error.HTTPError as r:
            with r:code,raw=r.code,r.read()
        self.assertNotIn(b'private-account-token',raw)
        return code,json.loads(raw)

    def test_mosaic_capacity_camera_ownership_handles_and_stop_are_session_scoped(self):
        self.assertEqual(self.post('/api/video/start',{'device_id':'foreign'})[0],422)
        self.assertEqual(len(FakeStream.instances),0)
        handles={}
        for i in range(8):
            code,data=self.post('/api/video/start',{'device_id':str(i), 'mosaic': i==0})
            self.assertEqual(code,200);handles[str(i)]=data['stream_id']
        self.assertEqual(FakeStream.instances[0].preview_width,640)
        self.assertEqual(FakeStream.instances[1].preview_width,960)
        self.assertEqual(len(self.server.active_streams),8)
        self.assertEqual(self.post('/api/video/start',{'device_id':'8'})[0],422)
        self.assertEqual(self.post('/api/video/start',{'device_id':'0'})[1]['stream_id'],handles['0'])
        self.assertEqual(len(FakeStream.instances),8)
        self.assertEqual(self.post('/api/video/frame',{'device_id':'0','stream_id':handles['0']})[0],200)
        self.assertEqual(self.post('/api/video/frame',{'device_id':'0','stream_id':'old-handle'})[0],422)
        other_cookie,other_csrf,_=self.new_session()
        self.assertEqual(self.post('/api/video/frame',{'device_id':'0','stream_id':handles['0']},other_cookie,other_csrf)[0],422)
        self.assertEqual(self.post('/api/video/frame',{'device_id':'0','stream_id':handles['0']},csrf='invalid')[0],403)
        self.post('/api/video/stop',{'device_id':'0','stream_id':'old-handle'})
        self.assertFalse(FakeStream.instances[0].stopped.is_set())
        self.post('/api/video/stop',{'device_id':'0','stream_id':handles['0']})
        self.assertTrue(FakeStream.instances[0].stopped.is_set())
        self.assertFalse(FakeStream.instances[1].stopped.is_set())
        self.assertEqual(self.post('/api/video/start',{'device_id':'8'})[0],200)
        self.assertEqual(len(self.server.active_streams),8)
        self.assertEqual(self.post('/api/logout',{})[0],200)
        self.assertTrue(all(s.stopped.is_set() for s in FakeStream.instances))
        self.assertEqual(len(self.server.active_streams),0)
        self.assertIsNone(self.state['client'])

    def test_report_records_and_images_are_session_scoped(self):
        self.post('/api/video/start', {'device_id':'0'})
        code,data=self.post('/api/reports', {})
        self.assertEqual(code,200)
        self.assertEqual(data['events'][0]['kind'],'opened')
        owner=__import__('hashlib').sha256(b'123').hexdigest()
        self.server.reports.store.add(owner,'0','Camera','person',b'jpeg',.9)
        event_id=self.post('/api/reports',{})[1]['events'][0]['id']
        request=urllib.request.Request(self.base+'/api/reports/image/'+str(event_id),headers={'Cookie':self.cookie})
        with urllib.request.urlopen(request) as response:self.assertEqual(response.read(),b'jpeg')
        other_cookie,other_csrf,other_state=self.new_session()
        other_state['client']=DesktopClient(DesktopProfile('a'*32,'b'*64))
        other_state['client'].account=DesktopAccount('456','other-token')
        self.assertEqual(self.post('/api/reports',{},other_cookie,other_csrf)[1]['events'],[])
        request=urllib.request.Request(self.base+'/api/reports/image/'+str(event_id),headers={'Cookie':other_cookie})
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
        self.assertEqual(error.exception.code,404)

    def test_active_session_renews_cookie_and_live_lease(self):
        self.post('/api/video/start', {'device_id':'0'})
        stream = FakeStream.instances[-1]
        old = self.state['expires'] = time.monotonic()+1
        request = urllib.request.Request(self.base+'/api/status', headers={'Cookie':self.cookie})
        with urllib.request.urlopen(request) as response:
            self.assertIn('Max-Age=1200', response.headers['Set-Cookie'])
            self.assertTrue(json.load(response)['authenticated'])
        self.assertGreater(self.state['expires'], old+1000)
        self.assertEqual(stream.expires, self.state['expires'])
        self.assertFalse(stream.stopped.is_set())

    def test_quality_requests_preserve_original_size_and_validate_values(self):
        for quality, definition in (("hd", 1), ("fhd", 2), ("original", 0)):
            with self.subTest(quality=quality):
                code, data = self.post('/api/video/start', {'device_id':'0', 'quality':quality})
                self.assertEqual(code, 200)
                self.assertEqual(FakeStream.instances[-1].preview_width, 0)
                self.assertEqual(FakeStream.instances[-1].definition, definition)
                self.post('/api/video/stop', {'device_id':'0', 'stream_id':data['stream_id']})
        self.assertEqual(self.post('/api/video/start', {'device_id':'0', 'quality':'unknown'})[0], 422)
        self.assertEqual(len(self.server.active_streams), 0)
        self.assertEqual(self.post('/api/video/start', {'device_id':'0'})[0], 200)

    def test_expiry_and_server_close_release_active_streams(self):
        self.post('/api/video/start',{'device_id':'0'})
        self.state['expires']=time.monotonic()-1
        self.assertEqual(self.post('/api/video/frame',{'device_id':'0'})[0],403)
        self.assertTrue(FakeStream.instances[0].stopped.is_set())
        self.assertEqual(len(self.server.active_streams),0)
        self.cookie,self.csrf,self.state=self.new_session()
        client=DesktopClient(DesktopProfile('a'*32,'b'*64));client.account=DesktopAccount('123','private-account-token');client.device_ids={'0'}
        self.state['client']=client
        self.post('/api/video/start',{'device_id':'0'})
        self.server.server_close()
        self.assertTrue(FakeStream.instances[-1].stopped.is_set())
