import importlib.util
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from remembered import DeviceVault,TTL
from provider_sessions import ProviderSessions
from desktop import DesktopClient,DesktopAccount,DesktopProfile
from yoosee import IntegrationError
from access import Gate,configure

PROFILE=DesktopProfile('a'*32,'b'*64)

@unittest.skipUnless(importlib.util.find_spec('cryptography'),'cryptography required for trusted devices')
class RememberedTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name);self.vault=DeviceVault(self.root)
        self.auth=ProviderSessions(self.vault,'scope',lambda:PROFILE)

    def state(self):
        client=DesktopClient(PROFILE);client.account=DesktopAccount('owner-id','private-provider-token');client.device_ids={'123'}
        return {'client':client,'report_owner':'a'*64,'devices':[{'id':'123','name':'Camera'}],'remember':True,'remember_until':time.time()+TTL}

    def test_restart_restores_only_bound_device_and_never_stores_password_or_plain_token(self):
        token='x'*43;state=self.state()
        self.assertTrue(self.auth.save(token,state))
        raw=self.vault.path.read_bytes()
        self.assertNotIn(b'private-provider-token',raw);self.assertNotIn(token.encode(),raw)
        restored=ProviderSessions(DeviceVault(self.root),'scope',lambda:PROFILE).restore(token)
        self.assertEqual(restored[0].account.access_token,'private-provider-token')
        self.assertEqual(restored[0].device_ids,{'123'})
        self.assertIsNone(self.auth.restore('y'*43))
        self.assertIsNone(ProviderSessions(self.vault,'other-scope',lambda:PROFILE).restore(token))
        self.assertEqual(self.vault.path.stat().st_mode&0o777,0o600)
        self.auth.forget(token);self.assertIsNone(self.auth.restore(token))

    def test_ciphertext_tampering_and_expiry_fail_closed(self):
        token='x'*43;state=self.state();self.auth.save(token,state)
        with self.vault.connect() as db:db.execute("UPDATE devices SET payload=zeroblob(length(payload))")
        self.assertIsNone(self.auth.restore(token))
        self.auth.save(token,state)
        with self.vault.connect() as db:db.execute('UPDATE devices SET expires=expires+86400')
        self.assertIsNone(self.auth.restore(token))
        state['remember_until']=time.time()-1;self.auth.save(token,state)
        self.assertIsNone(self.auth.restore(token))

    def test_same_valid_credentials_reuse_session_but_wrong_password_does_not(self):
        def accepted(client,*args):client.account=DesktopAccount('owner-id','private-provider-token')
        with patch.object(DesktopClient,'login',accepted) as login:
            first,owner=self.auth.login(PROFILE,'user@example.test','correct-password')
            with patch.object(DesktopClient,'login',side_effect=AssertionError('Must not call provider')):
                second,owner2=self.auth.login(PROFILE,'user@example.test','correct-password')
                self.assertEqual(first.account.access_token,second.account.access_token)
                self.assertIsNot(first,second);self.assertEqual(owner,owner2)
                self.assertEqual(self.auth.stats[owner]['provider_login_requests'],1)
                self.assertEqual(self.auth.stats[owner]['session_reuses'],1)
        with patch.object(DesktopClient,'login',side_effect=IntegrationError('provider','Rejected')) as login:
            with self.assertRaises(IntegrationError):self.auth.login(PROFILE,'user@example.test','incorrect-password')
            with self.assertRaisesRegex(IntegrationError,'Aguarde'):self.auth.login(PROFILE,'user@example.test','incorrect-password')
            self.assertEqual(login.call_count,1)

    def test_rejected_provider_token_is_not_restored_after_restart(self):
        token='x'*43;state=self.state();self.auth.save(token,state)
        self.auth.reject(state['client'])
        self.assertIsNone(ProviderSessions(DeviceVault(self.root),'scope',lambda:PROFILE).restore(token))

    def test_renewed_session_recovers_only_previously_bound_devices_of_same_owner(self):
        first='x'*43;second='y'*43;foreign='z'*43
        state=self.state();self.auth.save(first,state)
        other=self.state();other['report_owner']='b'*64;self.auth.save(foreign,other)
        self.auth.reject(state['client'])
        renewed=self.state();renewed['client'].account=DesktopAccount('owner-id','renewed-provider-token')
        self.auth.save(second,renewed)
        restored=ProviderSessions(DeviceVault(self.root),'scope',lambda:PROFILE)
        self.assertEqual(restored.restore(first)[0].account.access_token,'renewed-provider-token')
        self.assertIsNone(restored.restore(foreign))
        self.assertIsNone(restored.restore('q'*43))
        self.auth.forget(first);self.assertIsNone(restored.restore(first))

    def test_gate_remembers_restart_and_password_change_revokes_old_device(self):
        path=self.root/'access.json';configure('test-password-123',path)
        gate=Gate(path);token,code=gate.login('test-password-123',remember=True)
        self.assertEqual(code,200);self.assertTrue(Gate(path).valid(token))
        self.assertGreater(gate.cookie_ttl(token),TTL-5)
        gate.revoke(token);self.assertFalse(gate.valid(token));self.assertFalse(Gate(path).valid(token))
        token,_=gate.login('test-password-123',remember=True)
        configure('changed-password-123',path);self.assertFalse(Gate(path).valid(token))
