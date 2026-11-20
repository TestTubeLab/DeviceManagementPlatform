"""Real ZIP/TAR staging and rollback tests with isolated downloads and directories."""

import errno
import gzip
import hashlib
import io
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

from test_log_tasks import load_agent


class CodePackageTests(unittest.TestCase):
    def setUp(self):
        self.agent = load_agent()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.target = self.parent / 'code'
        self.target.mkdir()
        self.runtime = {
            '.env': b'ROOT_ENV=old',
            'localstore/logs/old.log': b'root runtime',
            'server/db.sqlite3': b'root database',
            'server/db.sqlite3-wal': b'root wal',
            'MiddlewareServer/.env': b'PROJECT_ENV=old',
            'MiddlewareServer/localstore/logs/old.log': b'project runtime',
            'MiddlewareServer/server/db.sqlite3': b'project database',
            'MiddlewareServer/server/db.sqlite3-shm': b'project shm',
        }
        self.old = {**self.runtime, 'MiddlewareServer/app.py': b'old code',
                    'MiddlewareServer/config/devices.yml': b'old config',
                    'MiddlewareServer/server/plugins/settings.yml': b'old plugin settings',
                    'obsolete.txt': b'old file'}
        for name, content in self.old.items():
            destination = self.target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        self.original_inode = self.target.stat().st_ino
        self.runtime_inodes = {name: (self.target / name).stat().st_ino for name in self.runtime}
        self.localstore_inode = (self.target / 'MiddlewareServer/localstore').stat().st_ino
        self.original = self.snapshot()

    def snapshot(self):
        return {path.relative_to(self.target).as_posix():
                (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                for path in self.target.rglob('*') if path.is_file()}

    def assert_untouched(self):
        self.assertEqual(self.snapshot(), self.original)
        self.assertEqual(self.target.stat().st_ino, self.original_inode)
        self.assertEqual(list(self.parent.iterdir()), [self.target])

    def zip_data(self, files=None):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_STORED) as archive:
            for name, content in (files or {'MiddlewareServer/app.py': b'NEW-CODE'}).items():
                entry = zipfile.ZipInfo(name)
                entry.create_system = 3
                entry.external_attr = (stat.S_IFREG | 0o751) << 16
                archive.writestr(entry, content)
        return output.getvalue()

    def tar_data(self, files=None):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w') as archive:
            for name, content in (files or {'MiddlewareServer/app.py': b'NEW-CODE'}).items():
                entry = tarfile.TarInfo(name)
                entry.size = len(content)
                entry.mode = 0o751
                archive.addfile(entry, io.BytesIO(content))
        return output.getvalue()

    def deploy(self, content, headers=None, **metadata):
        response = MagicMock(status_code=200)
        response.headers = headers if headers is not None else {'content-length': str(len(content))}
        response.iter_content.return_value = [content[index:index + 23] for index in range(0, len(content), 23)]
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        self.agent.requests.get.return_value = response
        return self.agent.download_and_extract_code_package(
            {'id': 1, 'name': 'synthetic', 'version': '2', **metadata}, str(self.target),
        )

    def test_corrupt_zip_crc_leaves_original_tree_untouched(self):
        data = self.zip_data().replace(b'NEW-CODE', b'BAD-CODE', 1)
        with self.assertRaises(zipfile.BadZipFile):
            self.deploy(data)
        self.assert_untouched()

    def test_corrupt_tar_payload_and_unknown_format_leave_original_tree_untouched(self):
        for data in (self.tar_data({'MiddlewareServer/app.py': b'x' * 2048})[:700], b'not an archive'):
            with self.subTest(data_size=len(data)):
                with self.assertRaises((tarfile.ReadError, OSError)):
                    self.deploy(data)
                self.assert_untouched()

    def test_corrupt_tar_gzip_trailer_and_empty_archives_leave_original_tree_untouched(self):
        compressed = bytearray(gzip.compress(self.tar_data()))
        compressed[-8] ^= 0xff
        empty_zip = io.BytesIO()
        with zipfile.ZipFile(empty_zip, 'w'):
            pass
        empty_tar = io.BytesIO()
        with tarfile.open(fileobj=empty_tar, mode='w'):
            pass
        for data in (bytes(compressed), empty_zip.getvalue(), empty_tar.getvalue()):
            with self.subTest(size=len(data)):
                with self.assertRaises((OSError, ValueError)):
                    self.deploy(data)
                self.assert_untouched()

    def test_zip_and_tar_preserve_hierarchy_runtime_inode_and_update_configuration(self):
        files = {
            'MiddlewareServer/app.py': b'new code',
            'MiddlewareServer/config/devices.yml': b'new config',
            'MiddlewareServer/server/plugins/settings.yml': b'new plugin settings',
            '.env': b'package root env',
            'MiddlewareServer/.env': b'package project env',
            'MiddlewareServer/localstore/logs/package.log': b'package runtime placeholder',
        }
        for builder in (self.zip_data, self.tar_data):
            with self.subTest(format=builder.__name__):
                self.assertTrue(self.deploy(builder(files)))
                self.assertEqual(self.target.stat().st_ino, self.original_inode)
                for name, content in self.runtime.items():
                    self.assertEqual((self.target / name).read_bytes(), content)
                    self.assertEqual((self.target / name).stat().st_ino, self.runtime_inodes[name])
                self.assertEqual((self.target / 'MiddlewareServer/localstore').stat().st_ino, self.localstore_inode)
                for name, content in files.items():
                    if name not in self.runtime and '/localstore/' not in name:
                        self.assertEqual((self.target / name).read_bytes(), content)
                self.assertFalse((self.target / 'app.py').exists())
                self.assertFalse((self.target / 'obsolete.txt').exists())
                self.assertFalse((self.target / 'MiddlewareServer/localstore/logs/package.log').exists())
                self.assertEqual(list(self.parent.iterdir()), [self.target])
                if os.name != 'nt':
                    self.assertEqual(stat.S_IMODE((self.target / 'MiddlewareServer/app.py').stat().st_mode), 0o751)

    def test_zip_and_tar_reject_traversal_absolute_and_windows_paths(self):
        for builder in (self.zip_data, self.tar_data):
            for name in ('../escape', 'MiddlewareServer/../../escape', '/escape', 'C:/escape', '..\\escape'):
                with self.subTest(format=builder.__name__, member=name):
                    with self.assertRaisesRegex(ValueError, 'archive path'):
                        self.deploy(builder({'MiddlewareServer/app.py': b'valid first', name: b'bad'}))
                    self.assert_untouched()

    def test_zip_links_and_tar_links_and_special_files_are_rejected(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            entry = zipfile.ZipInfo('MiddlewareServer/link')
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(entry, '../../escape')
        archives = [output.getvalue()]
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode='w') as archive:
                entry = tarfile.TarInfo('MiddlewareServer/link')
                entry.type = kind
                entry.linkname = '../../escape'
                archive.addfile(entry)
            archives.append(output.getvalue())
        for data in archives:
            with self.subTest(size=len(data)):
                with self.assertRaisesRegex(ValueError, 'links or special files'):
                    self.deploy(data)
                self.assert_untouched()

    def test_size_and_optional_checksum_are_checked_before_replacement(self):
        data = self.zip_data()
        cases = [dict(headers={'content-length': str(len(data) + 1)}),
                 dict(size=len(data) + 1), dict(checksum='0' * 32), dict(checksum='invalid')]
        for metadata in cases:
            with self.subTest(metadata=metadata):
                with self.assertRaises((ValueError, RuntimeError)):
                    self.deploy(data, **metadata)
                self.assert_untouched()
        for digest in (hashlib.md5(data).hexdigest(), hashlib.sha256(data).hexdigest()):
            self.assertTrue(self.deploy(data, size=len(data), checksum=digest))

    def test_extraction_write_failure_leaves_original_tree_untouched(self):
        with patch('shutil.copyfileobj', side_effect=OSError(errno.ENOSPC, 'synthetic staging disk full')):
            with self.assertRaises(OSError):
                self.deploy(self.zip_data())
        self.assert_untouched()

    def test_backup_carry_or_install_replace_failure_restores_original_tree(self):
        real_replace = os.replace
        for phase in ('backup', 'carry', 'install'):
            calls = [0]

            def replace(source, destination):
                if phase == 'backup':
                    selected = Path(source).parent == self.target
                elif phase == 'carry':
                    selected = any(parent.name == 'backup' for parent in Path(source).parents)
                else:
                    selected = Path(source).parent.name == 'stage'
                if selected:
                    calls[0] += 1
                    if calls[0] == 2:
                        raise OSError('synthetic replacement failure')
                return real_replace(source, destination)

            with self.subTest(phase=phase), patch.object(self.agent.os, 'replace', side_effect=replace):
                with self.assertRaisesRegex(OSError, 'synthetic replacement'):
                    self.deploy(self.zip_data())
                self.assert_untouched()

    def test_runtime_write_at_cutover_keeps_latest_bytes_and_original_inode(self):
        real_replace = os.replace

        def replace(source, destination):
            result = real_replace(source, destination)
            if Path(source) == self.target / 'MiddlewareServer':
                database = Path(destination) / 'server/db.sqlite3'
                with database.open('ab') as handle:
                    handle.write(b' latest write')
            return result

        with patch.object(self.agent.os, 'replace', side_effect=replace):
            self.assertTrue(self.deploy(self.zip_data()))
        database = self.target / 'MiddlewareServer/server/db.sqlite3'
        self.assertEqual(database.read_bytes(), b'project database latest write')
        self.assertEqual(database.stat().st_ino, self.runtime_inodes['MiddlewareServer/server/db.sqlite3'])

    def test_incomplete_rollback_keeps_backup_for_recovery(self):
        real_replace = os.replace

        def replace(source, destination):
            if Path(source).parent.name == 'stage':
                raise OSError('synthetic install failure')
            if Path(source).parent.name == 'backup' and Path(source).name == 'MiddlewareServer':
                raise OSError('synthetic rollback failure')
            return real_replace(source, destination)

        with patch.object(self.agent.os, 'replace', side_effect=replace):
            with self.assertRaisesRegex(RuntimeError, 'backup retained'):
                self.deploy(self.zip_data())
        backups = list(self.parent.glob('.code-update-*/backup/MiddlewareServer/app.py'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'old code')
        self.assertEqual(self.target.stat().st_ino, self.original_inode)

    def test_fresh_install_gzip_tar_keeps_top_project_directory(self):
        self.target = self.parent / 'fresh-code'
        self.assertTrue(self.deploy(gzip.compress(self.tar_data())))
        self.assertEqual((self.target / 'MiddlewareServer/app.py').read_bytes(), b'NEW-CODE')
        self.assertFalse((self.target / 'app.py').exists())


if __name__ == '__main__':
    unittest.main()
