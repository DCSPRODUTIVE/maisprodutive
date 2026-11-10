from pathlib import Path
import tempfile
import unittest

from configure_startup import units, quote, validate_tunnel


class StartupTests(unittest.TestCase):
    def test_units_run_as_owner_and_restart_without_credentials(self):
        result=units('/home/test/My Project','/home/test','test','/usr/bin/python3',
                     '/usr/bin/cloudflared','https://cameras.example.test',8097)
        app=result['dcs-control.service'];tunnel=result['dcs-tunnel.service']
        self.assertIn('User=test',app)
        self.assertIn('WorkingDirectory=/home/test/My Project\n',app)
        self.assertIn('KillSignal=SIGINT',app)
        self.assertIn('Restart=always',app);self.assertIn('Restart=always',tunnel)
        self.assertIn('WantedBy=multi-user.target',app)
        self.assertIn('"/home/test/My Project/server.py"',app)
        self.assertIn('--public-origin "https://cameras.example.test"',app)
        self.assertIn('"/home/test/.cloudflared/config.yml" run torre-dcs',tunnel)
        self.assertNotIn('remote_access.py',tunnel)
        self.assertNotIn('sudo',app)
        self.assertNotIn('password',app.lower())
        self.assertNotIn('token',tunnel.lower())

    def test_values_are_escaped_for_systemd_and_unsafe_input_rejected(self):
        self.assertEqual(quote('a%$"b'), '"a%%$$\\"b"')
        for value in ('a\nb','a\rb','a\0b'):
            with self.assertRaises(ValueError):quote(value)
        with self.assertRaises(ValueError):units('/tmp','/tmp','root\nOther=x','python','cloudflared','https://example.test',8097)
        with self.assertRaises(ValueError):units('/tmp','/tmp','test','python','cloudflared','http://example.test',8097)

    def test_tunnel_validation_does_not_require_reading_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.yml'
            path.write_text('tunnel: test-id\ningress:\n  - service: http://127.0.0.1:8097\n')
            self.assertIn('test-id',validate_tunnel(path))
            path.write_text('unrelated: value')
            with self.assertRaises(ValueError):validate_tunnel(path)

    def test_independent_watchdog_runs_unprivileged_and_recovery_is_a_fixed_command(self):
        result=units('/home/test/project','/home/test','test','/usr/bin/python3','/usr/bin/cloudflared','https://cameras.example.test',8097)
        watch=result['dcs-watchdog.service'];recover=result['dcs-recover.service']
        self.assertIn('User=test',watch);self.assertIn('SuccessExitStatus=1',watch)
        self.assertIn('OnFailure=dcs-recover.service',watch)
        self.assertIn('ExecStart=/usr/bin/systemctl restart --no-block dcs-control.service',recover)
        self.assertNotIn('python',recover);self.assertIn('StartLimitBurst=1',recover)
