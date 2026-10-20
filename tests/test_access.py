import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from access import Gate, configure, origin
from server import Workbench


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'access.json'
        self.password='test-only-password-123'
        configure(self.password,self.path)
        self.gate=Gate(self.path)
        self.server=Workbench(('127.0.0.1',0),public_origin='https://monitor.example.test',access_gate=self.gate)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def request(self,path,body=None,cookie=None,**overrides):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=4)
        headers={'Host':'monitor.example.test','X-Forwarded-Proto':'https','Origin':'https://monitor.example.test'}
        if cookie:headers['Cookie']=cookie
        if body is not None:headers['Content-Type']='application/json'
        headers.update(overrides)
        conn.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,headers)
        response=conn.getresponse();result=(response.status,response.getheaders(),response.read());conn.close();return result

    def test_gate_protects_dashboard_apis_and_photos(self):
        self.assertEqual(self.request('/')[0],303)
        self.assertEqual(self.request('/reports')[0],303)
        self.assertEqual(self.request('/api/status')[0],401)
        self.assertEqual(self.request('/api/reports/image/1')[0],401)
        self.assertEqual(self.request('/api/reports/video/1')[0],401)
        self.assertEqual(self.request('/access')[0],200)
        self.assertEqual(len(self.server.sessions),0)
        code,headers,_=self.request('/api/access/login',{'password':self.password})
        self.assertEqual(code,200)
        cookie=next(v for k,v in headers if k=='Set-Cookie')
        self.assertIn('Secure',cookie);self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Strict',cookie)
        cookie=cookie.split(';')[0]
        code,headers,body=self.request('/api/status',cookie=cookie)
        self.assertEqual(code,200)
        self.assertFalse(json.loads(body)['authenticated'])
        self.assertEqual(len([v for k,v in headers if k=='Set-Cookie']),2)
        self.assertEqual(self.request('/api/reports',{},cookie=cookie)[0],403) # provider CSRF still required

    def test_invalid_hosts_http_and_cross_origin_are_rejected(self):
        self.assertEqual(self.request('/access',Host='attacker.example')[0],403)
        self.assertEqual(self.request('/access',**{'X-Forwarded-Proto':'http'})[0],403)
        self.assertEqual(self.request('/api/access/login',{'password':self.password},Origin='https://other.example')[0],403)
        self.assertEqual(self.request('/api/access/login',{'password':'incorrect'})[0],401)
        self.assertNotIn(self.password,self.path.read_text())

    def test_login_rate_limit_and_revocation_on_restart(self):
        for _ in range(5):self.assertEqual(self.request('/api/access/login',{'password':'wrong'})[0],401)
        self.assertEqual(self.request('/api/access/login',{'password':self.password})[0],429)
        token,_=Gate(self.path).login(self.password)
        self.assertFalse(Gate(self.path).valid(token))

    def test_public_origin_must_be_exact_https_and_require_gate(self):
        for invalid in ('http://monitor.test','https://user:password@monitor.test','https://monitor.test/path','https://monitor.test?query=x'):
            with self.assertRaises(ValueError):origin(invalid)
        with self.assertRaises(ValueError):Workbench(('127.0.0.1',0),public_origin='https://monitor.test')
