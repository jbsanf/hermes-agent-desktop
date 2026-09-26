"""A failed export must never be followed by an installation attempt."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LocalFlow(unittest.TestCase):
    def test_export_failure_stops_installation(self):
        self.exercise(export_status=42)

    def test_skip_build_exports_before_installing(self):
        self.exercise(export_status=0)

    def exercise(self, export_status):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ('scripts', 'bin', 'build-dir/files/bin'):
                (root / folder).mkdir(parents=True)
            shutil.copy2(ROOT / 'scripts/build-local.sh', root / 'scripts/build-local.sh')
            (root / 'build-dir/metadata').touch()
            launcher = root / 'build-dir/files/bin/hermes-desktop'
            launcher.touch()
            launcher.chmod(0o755)
            commands = {
                'scripts/local-key.sh': 'echo test-key',
                'bin/python3': f'echo export >> "$TRACE"; exit {export_status}',
                'scripts/install-local.sh': 'echo install >> "$TRACE"',
            }
            for filename, body in commands.items():
                file = root / filename
                file.write_text('#!/bin/sh\n' + body + '\n')
                file.chmod(0o755)
            env = {**os.environ, 'PATH': str(root / 'bin') + ':' + os.environ['PATH'],
                   'TRACE': str(root / 'trace')}
            result = subprocess.run([str(root / 'scripts/build-local.sh'), '--skip-build'],
                                    cwd='/tmp', env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, export_status, result.stderr)
            self.assertEqual((root / 'trace').read_text().splitlines(),
                             ['export'] if export_status else ['export', 'install'])
