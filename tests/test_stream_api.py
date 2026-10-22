import json
import threading
import time
import types
import tempfile
from reports import EventStore, ReportMonitor
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
        self.condition=threading.Condition();self.image=None;self.last_frame=None;self.sequence=0
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
        client.device_ids={str(i) for i in range(13)}
        self.state['client']=client
        self.state['devices']=[{'id':str(i),'name':'Camera '+str(i)} for i in range(13)]
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
        for i in range(12):
            code,data=self.post('/api/video/start',{'device_id':str(i), 'mosaic': i==0})
            self.assertEqual(code,200);handles[str(i)]=data['stream_id']
        self.assertEqual(FakeStream.instances[0].preview_width,640)
        self.assertEqual(FakeStream.instances[1].preview_width,960)
        self.assertEqual(len(self.server.active_streams),12)
        self.assertEqual(self.post('/api/video/start',{'device_id':'12'})[0],422)
        self.assertEqual(self.post('/api/video/start',{'device_id':'0'})[1]['stream_id'],handles['0'])
        self.assertEqual(len(FakeStream.instances),12)
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
        self.assertEqual(self.post('/api/video/start',{'device_id':'12'})[0],200)
        self.assertEqual(len(self.server.active_streams),12)
        self.assertEqual(self.post('/api/logout',{})[0],200)
        self.assertTrue(all(s.stopped.is_set() for s in FakeStream.instances))
        self.assertEqual(len(self.server.active_streams),0)
        self.assertIsNone(self.state['client'])

    def test_telegram_config_requires_account_and_csrf_and_hides_token(self):
        token='123456789:'+ 'A'*35
        values={'enabled':True,'token':token,'chat_id':'12345'}
        self.assertEqual(self.post('/api/telegram/save',values,csrf='invalid')[0],403)
        cookie,csrf,state=self.new_session()
        self.assertEqual(self.post('/api/telegram/status',{},cookie,csrf)[0],422)
        code,data=self.post('/api/telegram/save',values)
        self.assertEqual(code,200)
        self.assertTrue(data['configured'])
        self.assertNotIn(token,json.dumps(data))
        with patch.object(self.server.telegram,'enqueue',return_value=True) as enqueue:
            self.assertEqual(self.post('/api/telegram/test',{})[0],200)
            self.assertEqual(self.post('/api/telegram/test',{})[0],429)
            enqueue.assert_called_once()
        self.post('/api/telegram/save',{'enabled':False,'token':'','chat_id':'12345'})
        self.assertFalse(self.post('/api/telegram/status',{})[1]['enabled'])

    def test_faces_routes_are_account_scoped_and_support_manual_learning(self):
        self.assertEqual(self.post('/api/faces/settings',{'enabled':True},csrf='invalid')[0],403)
        self.assertEqual(self.post('/api/faces/settings',{'enabled':True})[0],200)
        owner=__import__('hashlib').sha256(b'123').hexdigest()
        self.server.reports.faces.add(owner,'0','Entrada',b'face-photo',[1.0]+[0.0]*127)
        row=self.post('/api/faces/list',{})[1]['events'][0]
        self.assertNotIn('embedding',row)
        self.assertEqual(self.post('/api/faces/label',{'id':row['id'],'name':'Ana'})[0],200)
        self.assertEqual(self.post('/api/faces/list',{})[1]['events'][0]['label'],'Ana')
        request=urllib.request.Request(self.base+'/api/faces/image/'+str(row['id']),headers={'Cookie':self.cookie})
        with urllib.request.urlopen(request) as response:self.assertEqual(response.read(),b'face-photo')
        cookie,csrf,state=self.new_session()
        state['client']=DesktopClient(DesktopProfile('a'*32,'b'*64))
        state['client'].account=DesktopAccount('456','other-token')
        self.assertEqual(self.post('/api/faces/list',{},cookie,csrf)[1]['events'],[])
        self.assertEqual(self.post('/api/faces/label',{'id':row['id'],'name':'Bia'},cookie,csrf)[0],400)
        request=urllib.request.Request(self.base+'/api/faces/image/'+str(row['id']),headers={'Cookie':cookie})
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
        self.assertEqual(error.exception.code,404)
        self.assertEqual(self.post('/api/faces/settings',{})[0],400)
        self.assertEqual(self.post('/api/faces/clear',{})[0],200)
        self.assertEqual(self.post('/api/faces/list',{})[1]['events'],[])
        self.assertFalse(self.post('/api/faces/status',{})[1]['enabled'])

    def test_slow_frame_does_not_block_other_cameras_in_same_account(self):
        first=self.post('/api/video/start',{'device_id':'0'})[1]['stream_id']
        second=self.post('/api/video/start',{'device_id':'1'})[1]['stream_id']
        entered,release=threading.Event(),threading.Event()
        source=self.state['streams']['0'];original=source.frame
        def slow(*args,**kwargs):
            entered.set();release.wait(3);return original(*args,**kwargs)
        source.frame=slow
        result=[]
        worker=threading.Thread(target=lambda:result.append(self.post('/api/video/frame',{'device_id':'0','stream_id':first})))
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            started=time.monotonic()
            code,_=self.post('/api/video/frame',{'device_id':'1','stream_id':second})
            self.assertEqual(code,200);self.assertLess(time.monotonic()-started,1)
        finally:release.set();worker.join(4)
        self.assertEqual(result[0][0],200)

    def test_report_records_and_images_are_session_scoped(self):
        self.post('/api/video/start', {'device_id':'0'})
        code,data=self.post('/api/reports', {})
        self.assertEqual(code,200)
        self.assertEqual(data['events'],[])
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

    def test_preferences_validate_known_cameras_and_persist_per_account(self):
        values={'economy_ids':['0','1'],'detection_ids':['1'],'mosaic_limit':12}
        self.assertEqual(self.post('/api/preferences',values)[0],200)
        request=urllib.request.Request(self.base+'/api/status',headers={'Cookie':self.cookie})
        with urllib.request.urlopen(request) as response:self.assertEqual(json.load(response)['preferences'],values)
        self.assertEqual(self.post('/api/preferences',{'economy_ids':['foreign'],'mosaic_limit':12})[0],422)
        self.assertEqual(self.post('/api/preferences',{'economy_ids':[],'mosaic_limit':13})[0],422)
        other_cookie,other_csrf,_=self.new_session()
        self.assertEqual(self.post('/api/preferences',values,other_cookie,other_csrf)[0],422)

    def test_video_history_access_and_byte_ranges_are_account_scoped(self):
        owner=__import__('hashlib').sha256(b'123').hexdigest()
        store=self.server.reports.store
        filename='a'*32+'.mp4'
        video_id=store.video_add(owner,'0','Camera',filename)
        path=store.root/'videos'/filename;path.parent.mkdir(exist_ok=True);path.write_bytes(b'video-bytes')
        store.video_finish(video_id,'ready',120)
        code,data=self.post('/api/reports/videos',{})
        self.assertEqual(code,200);self.assertEqual(data['events'][0]['duration'],120)
        request=urllib.request.Request(self.base+'/api/reports/video/'+str(video_id),headers={'Cookie':self.cookie,'Range':'bytes=0-4'})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status,206);self.assertEqual(response.read(),b'video')
            self.assertEqual(response.headers['Content-Range'],'bytes 0-4/11')
        other_cookie,_,_=self.new_session()
        request=urllib.request.Request(self.base+'/api/reports/video/'+str(video_id),headers={'Cookie':other_cookie})
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
        self.assertEqual(error.exception.code,403)

    def test_background_survives_page_close_and_session_expiration(self):
        values={'economy_ids':[], 'detection_ids':['0'], 'mosaic_limit':8}
        self.assertEqual(self.post('/api/preferences',values)[0],200)
        self.server.background.tick()
        native=FakeStream.instances[-1]
        code,data=self.post('/api/video/start',{'device_id':'0','mosaic':True})
        self.assertEqual(code,200);self.assertTrue(data['background'])
        self.post('/api/video/stop',{}) # Same request sent by pagehide.
        self.assertFalse(native.stopped.is_set())
        self.state['expires']=time.monotonic()-1
        self.assertEqual(self.post('/api/video/frame',{'device_id':'0','mosaic':True})[0],403)
        self.assertFalse(native.stopped.is_set())
        self.assertEqual(self.server.background.status(__import__('hashlib').sha256(b'123').hexdigest())['configured'],1)
        self.server.background.remove(__import__('hashlib').sha256(b'123').hexdigest())
        self.assertTrue(native.stopped.is_set())

    def test_background_economy_pause_blocks_snapshot_and_extra_connection(self):
        now=[1000.]
        self.server.background.clock=lambda:now[0]
        values={'economy_ids':['0'], 'detection_ids':['0'], 'mosaic_limit':8}
        self.post('/api/preferences',values);self.server.background.tick()
        code,data=self.post('/api/video/start',{'device_id':'0','mosaic':True})
        self.assertEqual(code,200)
        before=len(FakeStream.instances)
        now[0]+=300;self.server.background.tick()
        self.assertEqual(self.post('/api/video/frame',{'device_id':'0','stream_id':data['stream_id']})[1]['state'],'paused')
        self.assertEqual(self.post('/api/video/snapshot',{'device_id':'0'})[0],422)
        self.post('/api/video/stop',{})
        self.post('/api/video/start',{'device_id':'0'})
        self.server.background.tick()
        self.assertEqual(len(FakeStream.instances),before)

    def test_person_reports_continue_without_browser_session(self):
        store=self.server.reports.store
        self.server.reports.close()
        with patch('reports.readiness',return_value=(True,'Ready')), patch('reports.Detector') as detector, patch('reports.RecordingService') as recorders:
            detector.return_value.detect.return_value=([{'kind':'person','confidence':.9,'box':[0,0,1,1]}],None)
            self.server.reports=ReportMonitor(self.server,store)
            self.server.reports.start()
            try:
                values={'economy_ids':[], 'detection_ids':['0'], 'mosaic_limit':8}
                self.post('/api/preferences',values);self.server.background.tick()
                native=FakeStream.instances[-1]
                self.post('/api/video/stop',{})
                self.state['expires']=time.monotonic()-1
                self.assertEqual(self.post('/api/video/frame',{'device_id':'0'})[0],403)
                native.image=b'background-frame';native.last_frame=time.monotonic();native.sequence=1
                owner=__import__('hashlib').sha256(b'123').hexdigest()
                deadline=time.monotonic()+3
                while not store.list(owner) and time.monotonic()<deadline:time.sleep(.02)
                self.assertEqual(store.list(owner)[0]['kind'],'person')
                recorders.return_value.trigger.assert_called_with(native)
                self.assertFalse(native.stopped.is_set())
            finally:self.server.reports.close()

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
