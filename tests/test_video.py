import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from desktop import DesktopAccount, DesktopClient, DesktopProfile
from yoosee import IntegrationError
import video


class VideoTests(unittest.TestCase):
    def test_only_devices_returned_for_this_account_can_be_captured(self):
        client = DesktopClient(DesktopProfile('a'*32, 'b'*64))
        client.account = DesktopAccount('123', 'sensitive-token')
        client.device_ids = {'owned-device'}
        with patch('video.capture', return_value={'image': 'test'}) as capture:
            for device in ('someone-else', None, ['owned-device']):
                with self.assertRaises(IntegrationError):
                    client.snapshot(device)
            capture.assert_not_called()
            self.assertEqual(client.snapshot('owned-device'), {'image': 'test'})
            capture.assert_called_once_with(client.account, 'owned-device')

    def test_unprepared_runtime_does_not_launch_native_code(self):
        with patch('video.readiness', return_value=(False, 'Prepare primeiro')), patch('video.subprocess.Popen') as launch:
            with self.assertRaises(IntegrationError):
                video.capture(DesktopAccount('123', 'secret'), 'device')
            launch.assert_not_called()

    def test_session_fields_cannot_inject_additional_native_commands(self):
        with patch('video.readiness', return_value=(True, '')), patch('video.subprocess.Popen') as launch:
            with self.assertRaises(IntegrationError):
                video.capture(DesktopAccount('123', 'secret\nanother-device'), 'device')
            launch.assert_not_called()

    def test_capture_uses_stdin_and_returns_only_converted_image(self):
        process = MagicMock(pid=987654321, returncode=0)
        process.communicate.return_value = (b'YUV4MPEG2 W16 H16 F1:1 Ip C420jpeg\nFRAME\n'+b'\x80'*384, None)
        jpeg = b'\xff\xd8synthetic-image\xff\xd9'
        account = DesktopAccount('123', 'secret-session')
        with patch('video.readiness', return_value=(True, '')), patch('video.shutil.which', side_effect=lambda name: '/usr/bin/'+name), patch('video.subprocess.Popen', return_value=process) as launch, patch('video.os.killpg'), patch('video.subprocess.run', return_value=subprocess.CompletedProcess([], 0, jpeg, b'')) as convert:
            data = video.capture(account, 'device')
            args, options = launch.call_args
            self.assertNotIn('secret-session', repr(args))
            self.assertNotIn('secret-session', repr(options))
            self.assertEqual(process.communicate.call_args.kwargs['timeout'], 45)
            self.assertEqual(process.communicate.call_args.args[0], b'123\nsecret-session\ndevice\n')
            self.assertTrue(data['image'].startswith('data:image/jpeg;base64,'))
            self.assertNotIn('secret-session', json.dumps(data))
            self.assertIn('não uma transmissão', data['message'])
            self.assertIn('pipe', convert.call_args.args[0])
            self.assertFalse(Path(options['cwd']).exists())

    def test_timeout_terminates_child_and_hides_native_output(self):
        process = MagicMock(pid=987654321)
        process.communicate.side_effect = [subprocess.TimeoutExpired('secret-command',45), (b'',None)]
        with patch('video.readiness', return_value=(True, '')), patch('video.shutil.which', return_value='/usr/bin/wine'), patch('video.subprocess.Popen', return_value=process), patch('video.os.killpg') as kill:
            with self.assertRaises(IntegrationError) as error:
                video.capture(DesktopAccount('123', 'secret-session'), 'device')
            self.assertEqual(error.exception.kind, 'video_timeout')
            self.assertNotIn('secret', str(error.exception))
            kill.assert_called()

    def test_vendor_output_is_not_forwarded_on_native_failure(self):
        process = MagicMock(pid=987654321, returncode=14)
        process.communicate.return_value = (b'account-secret-session',None)
        with patch('video.readiness', return_value=(True, '')), patch('video.shutil.which', return_value='/usr/bin/wine'), patch('video.subprocess.Popen', return_value=process), patch('video.os.killpg'):
            with self.assertRaises(IntegrationError) as error:
                video.capture(DesktopAccount('123', 'secret-session'), 'device')
            self.assertNotIn('secret-session', str(error.exception))
            self.assertIn('registro da sessão', str(error.exception))

    def test_runtime_rejects_changed_bridge_or_vendor_library(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'manifest.json').write_text(json.dumps({'source_sha256':'incorrect','bridge_sha256':'incorrect'}))
            with patch('video.NATIVE', root), patch('video.shutil.which', return_value='/tool'), patch('video.platform.system', return_value='Linux'), patch('video.platform.machine', return_value='x86_64'):
                ready, _ = video.readiness()
                self.assertFalse(ready)
