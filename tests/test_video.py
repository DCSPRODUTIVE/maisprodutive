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

    def test_native_metadata_is_strictly_numeric_and_matches_exit_reason(self):
        for raw, code, expected in (
            (b'MPVD1 17 7 1920 1080\n', 17, 'formato 7; dimensões 1920x1080'),
            (b'MPVD1 18 0 0 1080\n', 18, 'formato 0; dimensões 0x1080'),
            (b'secret-session MPVD1 17 7 1920 1080\n', 17, None),
            (b'MPVD1 17 7 1920 1080\n', 20, None),
            (b'MPVD1 17 99999999999999999 1920 1080\n', 17, None),
        ):
            process = MagicMock(pid=987654321, returncode=code)
            process.communicate.return_value = (raw, None)
            with self.subTest(raw=raw), patch('video.readiness', return_value=(True,'')), patch('video.shutil.which', return_value='/usr/bin/wine'), patch('video.subprocess.Popen', return_value=process), patch('video.os.killpg'):
                with self.assertRaises(IntegrationError) as error:
                    video.capture(DesktopAccount('123','secret-session'),'device')
                message = str(error.exception)
                self.assertNotIn('secret-session',message)
                if expected:
                    self.assertIn(expected,message)
                else:
                    self.assertNotIn('Diagnóstico:',message)

    def test_transfer_failure_is_not_reported_as_unsupported_format(self):
        process = MagicMock(pid=987654321, returncode=21)
        process.communicate.return_value = (b'YUV4MPEG2 partial',None)
        with patch('video.readiness', return_value=(True,'')), patch('video.shutil.which', return_value='/usr/bin/wine'), patch('video.subprocess.Popen', return_value=process), patch('video.os.killpg'):
            with self.assertRaises(IntegrationError) as error:
                video.capture(DesktopAccount('123','secret'),'device')
            self.assertIn('transferir o quadro',str(error.exception))
            self.assertNotIn('formato',str(error.exception))


class VideoUpdateTests(unittest.TestCase):
    def prepare_fixture(self, directory):
        import hashlib
        import configure_video
        root = Path(directory)
        native = root/'video'
        native.mkdir()
        (root/'native').mkdir()
        (root/'native'/'yoosee_snapshot.c').write_bytes(b'new-source')
        source = root/'installer.exe'
        source.write_bytes(b'synthetic-installer')
        dll = b'synthetic-dll'
        (native/'IotVideoSDK.dll').write_bytes(dll)
        (native/'yoosee_snapshot.exe').write_bytes(b'old-bridge')
        (native/'manifest.json').write_text(json.dumps({'source_sha256':'old-source', 'bridge_sha256':hashlib.sha256(b'old-bridge').hexdigest()}))
        def run(args, **kwargs):
            if args[0]=='/tools/7z':
                dest=Path(next(s[2:] for s in args if s.startswith('-o')))
                (dest/'IotVideoSDK.dll').write_bytes(dll)
            else:
                Path(args[args.index('-o')+1]).write_bytes(b'new-bridge')
            return subprocess.CompletedProcess(args,0,b'',b'')
        patches = [patch('configure_video.ROOT',root),patch('configure_video.NATIVE',native),
                   patch('configure_video.INSTALLER_SHA256',hashlib.sha256(source.read_bytes()).hexdigest()),
                   patch('configure_video.DLL_HASHES',{'IotVideoSDK.dll':hashlib.sha256(dll).hexdigest()}),
                   patch('configure_video.shutil.which',side_effect=lambda name:'/tools/'+name),
                   patch('configure_video.subprocess.run',side_effect=run)]
        return configure_video, source, native, patches

    def test_update_preserves_old_adapter_and_is_idempotent(self):
        from contextlib import ExitStack, redirect_stdout
        import io
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack, redirect_stdout(io.StringIO()):
            module, source, native, patches = self.prepare_fixture(directory)
            for p in patches: stack.enter_context(p)
            module.prepare(source,update=True)
            self.assertEqual((native/'yoosee_snapshot.exe').read_bytes(),b'new-bridge')
            backups=list(Path(directory).glob('video-backup-*'))
            self.assertEqual(len(backups),1)
            self.assertEqual((backups[0]/'yoosee_snapshot.exe').read_bytes(),b'old-bridge')
            module.prepare(source,update=True)
            self.assertEqual(len(list(Path(directory).glob('video-backup-*'))),1)

    def test_update_refuses_unknown_files_and_preserves_old_adapter(self):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            module, source, native, patches = self.prepare_fixture(directory)
            for p in patches: stack.enter_context(p)
            (native/'keep.txt').write_text('keep this')
            with self.assertRaises(ValueError):module.prepare(source,update=True)
            self.assertEqual((native/'keep.txt').read_text(),'keep this')
            self.assertEqual((native/'yoosee_snapshot.exe').read_bytes(),b'old-bridge')
            self.assertFalse(list(Path(directory).glob('video-backup-*')))
