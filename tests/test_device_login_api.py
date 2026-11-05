import importlib.util
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from desktop import DesktopAccount,DesktopClient,DesktopProfile
from reports import EventStore
from server import Workbench

PROFILE=DesktopProfile('a'*32,'b'*64)

@unittest.skipUnless(importlib.util.find_spec('cryptography'),'cryptography required for trusted devices')
class DeviceLoginApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.config=patch('server.current_config',return_value=PROFILE);self.config.start();self.addCleanup(self.config.stop)
        self.store=patch('server.EventStore',side_effect=lambda:EventStore(Path(self.temp.name)/'reports'));self.store.start();self.addCleanup(self.store.stop)
        def login(client,*args):client.account=DesktopAccount('account-id','private-provider-session-token')
        self.login=patch.object(DesktopClient,'login',autospec=True,side_effect=login).start()
        self.addCleanup(patch.stopall)
        def devices(client):client.device_ids={'cam'};return [{'id':'cam','name':'Camera'}]
        patch.object(DesktopClient,'devices',devices).start()
        self.start()

    def start(self):
        self.server=Workbench(('127.0.0.1',0))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def tearDown(self):self.stop()

    def request(self,path,body=None,cookie=None,csrf=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        host='127.0.0.1:'+str(self.server.server_port)
        headers={'Host':host,'Origin':'http://'+host}
        if cookie:headers['Cookie']=cookie
        if csrf:headers['X-CSRF-Token']=csrf
        if body is not None:headers['Content-Type']='application/json'
        conn.request('GET' if body is None else 'POST',path,json.dumps(body) if body is not None else None,headers)
        response=conn.getresponse();raw=response.read();cookies=[value.split(';')[0] for key,value in response.getheaders() if key=='Set-Cookie']
        result=response.status,json.loads(raw),cookies;conn.close()
        self.assertNotIn(b'private-provider-session-token',raw)
        return result

    def authorize(self):
        code,data,cookies=self.request('/api/status');cookie=cookies[0];csrf=data['csrf']
        self.assertEqual(self.request('/api/login',{'username':'user@example.test','password':'private-test-password','remember':True},cookie,csrf)[0],200)
        self.assertEqual(self.request('/api/devices',{},cookie,csrf)[0],200)
        return cookie,csrf

    def test_browser_and_service_restart_restore_without_password_or_provider_login(self):
        cookie,csrf=self.authorize();other,other_csrf=self.authorize()
        self.assertEqual(self.login.call_count,1) # same valid proof, separate device bindings
        self.stop();self.start()
        code,status,_=self.request('/api/status',cookie=cookie)
        self.assertEqual(code,200);self.assertTrue(status['authenticated']);self.assertTrue(status['remembered'])
        self.assertEqual(status['devices'][0]['id'],'cam');self.assertNotEqual(status['csrf'],csrf)
        self.assertEqual(self.login.call_count,1)
        self.assertFalse(self.request('/api/status',cookie='workbench='+'z'*43)[1]['authenticated'])
        self.assertTrue(self.request('/api/status',cookie=other)[1]['authenticated'])

    def test_forgetting_one_device_preserves_another_and_does_not_stop_monitoring(self):
        first,csrf=self.authorize();second,_=self.authorize()
        with patch.object(self.server.background,'remove') as remove:
            self.assertEqual(self.request('/api/logout',{},first,csrf)[0],200);remove.assert_not_called()
        self.stop();self.start()
        self.assertFalse(self.request('/api/status',cookie=first)[1]['authenticated'])
        self.assertTrue(self.request('/api/status',cookie=second)[1]['authenticated'])
