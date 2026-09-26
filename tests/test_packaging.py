import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BackendContract(unittest.TestCase):
    def test_private_launcher_only_accepts_headless_backend(self):
        backend = load("private_backend", "packaging/hermes-backend.py")
        for arguments in (["serve", "--port", "0"], ["--profile", "work", "serve"], ["--version"]):
            backend.validate_args(arguments)
        for arguments in ([], ["chat"], ["--tui"], ["update"], ["desktop"], ["--profile", "work", "update"]):
            with self.assertRaises(ValueError):
                backend.validate_args(arguments)


class SignedRepositoryContract(unittest.TestCase):
    def test_invalid_repository_preserves_existing_artifacts(self):
        publisher = load("publisher_preflight", "scripts/publish-repo.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "build-dir").mkdir()
            (root / "build-dir/metadata").touch()
            (root / "repo").mkdir()  # Missing OSTree config: intentionally invalid.
            release = root / "dist/release"
            release.mkdir(parents=True)
            sentinel = release / "previous.flatpak"
            sentinel.write_bytes(b"previous artifact")
            original_cwd = Path.cwd()
            try:
                with patch.object(publisher, "ROOT", root), \
                        patch.object(sys, "argv", ["publish-repo.py", "--key", "unused"]), \
                        contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    publisher.main()
                self.assertEqual(error.exception.code, 2)
                self.assertEqual(sentinel.read_bytes(), b"previous artifact")
            finally:
                os.chdir(original_cwd)

    def test_bundle_origin_signature_and_successive_exports(self):
        publisher = load("publisher", "scripts/publish-repo.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "gnupg"
            home.mkdir(mode=0o700)
            env = {**os.environ, "GNUPGHOME": str(home)}
            subprocess.run(["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "",
                            "--quick-generate-key", "Flatpak integration test", "ed25519", "sign", "0"],
                           check=True, env=env, capture_output=True)
            listing = subprocess.check_output(["gpg", "--list-secret-keys", "--with-colons"], env=env, text=True)
            key = next(line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:"))
            build = root / "build-dir"
            (build / "files/bin").mkdir(parents=True)
            (build / "export").mkdir()
            executable = build / "files/bin/hermes-desktop"
            executable.write_text("#!/bin/sh\necho fixture-one\n")
            executable.chmod(0o755)
            app = publisher.CONFIG["app_id"]
            (build / "metadata").write_text(
                f"[Application]\nname={app}\nruntime=org.freedesktop.Platform/x86_64/25.08\n"
                "sdk=org.freedesktop.Sdk/x86_64/25.08\ncommand=hermes-desktop\n")
            original_cwd = Path.cwd()
            try:
                with patch.object(publisher, "ROOT", root), patch.dict(os.environ, env), \
                        patch.object(sys, "argv", ["publish-repo.py", "--key", key]), contextlib.redirect_stdout(io.StringIO()):
                    publisher.main()
                    first = json.loads((root / "dist/release/provenance.json").read_text())["ostree_commit"]
                    executable.write_text("#!/bin/sh\necho fixture-two\n")
                    publisher.main()
                second = json.loads((root / "dist/release/provenance.json").read_text())["ostree_commit"]
                self.assertNotEqual(first, second)
                parent = subprocess.check_output(["ostree", f"--repo={root / 'repo'}", "rev-parse", second + "^"], text=True).strip()
                self.assertEqual(parent, first)
                subprocess.run(["ostree", f"--repo={root / 'repo'}", "remote", "add",
                                f"--gpg-import={root / 'dist/release/repository.gpg'}", "test", publisher.CONFIG["repo_url"]], check=True)
                subprocess.run(["ostree", f"--repo={root / 'repo'}", "show", "--gpg-verify-remote=test", second], check=True, capture_output=True)
                bundle = next((root / "dist/release").glob("*.flatpak"))
                import gi
                gi.require_version("Flatpak", "1.0")
                from gi.repository import Flatpak, Gio
                reference = Flatpak.BundleRef.new(Gio.File.new_for_path(str(bundle)))
                self.assertEqual(reference.get_origin(), publisher.CONFIG["repo_url"])
                self.assertEqual(reference.get_commit(), second)
                self.assertEqual(reference.get_runtime_repo_url(), "https://flathub.org/repo/flathub.flatpakrepo")
                self.assertTrue((root / "dist/pages/repo/summary.sig").is_file())
                self.assertEqual(json.loads((root / "dist/pages/published.json").read_text())["ostree_commit"], second)
            finally:
                os.chdir(original_cwd)
                subprocess.run(["gpgconf", "--kill", "gpg-agent"], env=env, check=False)


if __name__ == "__main__":
    unittest.main()
