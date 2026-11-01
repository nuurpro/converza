"""Snapshot safety gates operate without Docker or application credentials."""
import importlib.util
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('renderer_snapshot', Path(__file__).resolve().parents[2] / 'scripts/snapshot_renderer_volume.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RendererSnapshotTests(unittest.TestCase):
    def test_confirmation_and_destination_are_required_before_docker_access(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(module.subprocess, 'check_output') as docker:
            root = Path(folder)
            with self.assertRaises(ValueError): module.snapshot('renderer', root / 'backup', root)
            with self.assertRaises(ValueError): module.snapshot('renderer', root, root, confirmed=True)
            with self.assertRaises(ValueError): module.snapshot('renderer', root.parent / 'outside', root, confirmed=True)
            project=Path(module.__file__).resolve().parents[1]
            with self.assertRaises(ValueError): module.snapshot('renderer',project/'private-backup',project.parent,confirmed=True)
            docker.assert_not_called()

    def test_running_or_wrong_volume_is_rejected_without_copying(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(module.subprocess, 'run') as copy:
            config={'State':{'Running':True},'Mounts':[]}
            with patch.object(module.subprocess,'check_output',return_value=json.dumps([config]).encode()):
                with self.assertRaises(ValueError): module.snapshot('renderer',Path(folder)/'backup',Path(folder),confirmed=True)
            config['State']['Running']=False
            with patch.object(module.subprocess,'check_output',return_value=json.dumps([config]).encode()):
                with self.assertRaises(ValueError): module.snapshot('renderer',Path(folder)/'backup',Path(folder),confirmed=True)
            copy.assert_not_called()

    def test_receipt_summary_is_read_only_and_does_not_expose_content(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'receipts.sqlite3'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
                db.execute('INSERT INTO tasks VALUES(?,?)',('task',json.dumps({'state':1,'private':'do-not-print'})))
                db.commit()
            before=module.digest(path)
            summary=module.receipt_summary(path)
            self.assertEqual(summary['integrity'],'ok')
            self.assertEqual(summary['receipts'],1)
            self.assertEqual(summary['states'],{'1':1})
            self.assertNotIn('do-not-print',json.dumps(summary))
            self.assertEqual(module.digest(path),before)

    def test_full_snapshot_preserves_private_inspection_and_verifies_media(self):
        config={'State':{'Running':False},'Image':'sha256:old-image','Config':{'Env':['KEY=private-fixture']},
                'Mounts':[{'Destination':'/MoneyPrinterTurbo/storage','Type':'volume','Name':'converza-vea-storage'}]}
        def copy(args,**_):
            target=Path(args[3])
            if args[2].endswith('/storage/.'):
                (target/'final.mp4').write_bytes(b'verified-media')
                with closing(sqlite3.connect(target/'renderer-state.sqlite3')) as db:
                    db.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
                    db.execute('INSERT INTO tasks VALUES(?,?)',('task','{"state":1}'))
                    db.commit()
            else: target.write_text('[app]\napproved_only=true\n')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); destination=root/'snapshot'
            with patch.object(module.subprocess,'check_output',side_effect=[json.dumps([config]).encode(),b'']), \
                    patch.object(module.subprocess,'run',side_effect=copy), \
                    patch.object(module,'secure_directory',side_effect=lambda p:p.mkdir()):
                report=module.snapshot('renderer',destination,root,confirmed=True)
            self.assertEqual(report['files'],2)
            self.assertEqual(report['receipts'],1)
            self.assertNotIn('private-fixture',json.dumps(report))
            self.assertEqual(json.loads((destination/'docker-inspect.json').read_text())[0],config)
            manifest=json.loads((destination/'files.json').read_text())
            self.assertTrue(all(module.digest(destination/'storage'/item['path'])==item['sha256'] for item in manifest))
