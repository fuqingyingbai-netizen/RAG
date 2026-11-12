"""Exercise UI publication against a disposable release, without business services."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.name == 'posix', 'Publisher uses Linux deployment locks')
class WorkspacePublicationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.release = self.root / 'releases' / ('a' * 40)
        (self.release / 'frontend').mkdir(parents=True)
        (self.release / 'backend').mkdir()
        (self.release / 'backend/app.py').write_text('original backend')
        (self.root / 'current').symlink_to(self.release, target_is_directory=True)
        (self.root / '.deployment-owned').touch()
        self.package = self.root / 'staging' / 'workspace'
        (self.package / 'frontend').mkdir(parents=True)
        (self.release / 'frontend/index.html').write_text('old entrypoint')
        (self.release / 'frontend/script.js').write_text('old source')
        (self.release / 'release-manifest.json').write_text(json.dumps({'commit':'a' * 40, 'files':[]}))
        spec = importlib.util.spec_from_file_location('workspace_publisher', Path(__file__).resolve().parents[1] / 'deploy/publish-project-workspace.py')
        self.publisher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.publisher)
        payloads = {'frontend/script.js':b'new script', 'frontend/project-workspace.js':b'new workspace', 'frontend/project-workspace.css':b'new styles'}
        hashed = self.publisher.digest(payloads['frontend/project-workspace.js'])[:12]
        payloads['frontend/project-workspace.' + hashed + '.js'] = b'new workspace'
        payloads['frontend/index.html'] = ('<script src="project-workspace.' + hashed + '.js"></script><a :href="source.url">Source</a>').encode()
        for name, data in payloads.items():
            (self.package / name).write_bytes(data)
        manifest = {'commit':'b' * 40, 'expected_release':str(self.release), 'baseline':{name:self.publisher.digest((self.release / name).read_bytes()) for name in ('frontend/index.html', 'frontend/script.js')}, 'files':[{'path':name, 'sha256':self.publisher.digest(data)} for name,data in payloads.items()]}
        (self.package / 'project-workspace-manifest.json').write_text(json.dumps(manifest))
        self.old_cwd = Path.cwd()
        os.chdir(self.release)
        self.addCleanup(os.chdir, self.old_cwd)

    def run_publish(self, served=None):
        def response(*args, **kwargs):
            return io.BytesIO((self.release / 'frontend/index.html').read_bytes() if served is None else served)
        with patch.object(self.publisher, 'ROOT', self.root), patch.object(self.publisher.os, 'geteuid', return_value=0), patch.object(self.publisher, 'runtime', return_value=(os.getpid(), {'instance_id':'same-instance'})), patch.object(self.publisher.urllib.request, 'urlopen', side_effect=response):
            self.publisher.publish(self.package)

    def test_verified_assets_publish_without_restarting_or_changing_backend(self):
        self.run_publish()
        self.assertEqual((self.release / 'frontend/script.js').read_text(), 'new script')
        self.assertEqual((self.release / 'backend/app.py').read_text(), 'original backend')
        manifest = json.loads((self.release / 'release-manifest.json').read_text())
        self.assertEqual(manifest['project_workspace_commit'], 'b' * 40)
        backup = next((self.root / 'backups').iterdir())
        self.assertEqual((backup / 'frontend/index.html').read_text(), 'old entrypoint')
        self.assertEqual(json.loads((backup / 'receipt.json').read_text())['instance_id'], 'same-instance')

    def test_concurrent_frontend_change_is_rejected_before_backup_or_publication(self):
        (self.release / 'frontend/index.html').write_text('concurrent update')
        with self.assertRaisesRegex(RuntimeError, 'changed during validation'):
            self.run_publish()
        self.assertEqual((self.release / 'frontend/script.js').read_text(), 'old source')
        self.assertFalse((self.root / 'backups').exists())

    def test_failed_served_entrypoint_check_restores_original_sources_and_manifest(self):
        original = (self.release / 'release-manifest.json').read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'Served entrypoint differs'):
            self.run_publish(b'wrong document')
        self.assertEqual((self.release / 'frontend/index.html').read_text(), 'old entrypoint')
        self.assertEqual((self.release / 'frontend/script.js').read_text(), 'old source')
        self.assertEqual((self.release / 'release-manifest.json').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
