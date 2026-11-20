"""Isolated Agent log-task tests; no host logging, HTTP, systemd or metrics access."""

import base64
import importlib.util
import io
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch
import zipfile


def load_agent():
    # Test-only source lookup. Do not import the daemon's /var/log FileHandler.
    path = Path(__file__).resolve().parents[1] / 'device-agent.py'
    spec = importlib.util.spec_from_file_location('isolated_log_task_agent', path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'requests': types.ModuleType('requests'),
                                  'psutil': types.ModuleType('psutil')}), \
            patch('logging.FileHandler', return_value=logging.NullHandler()), \
            patch('logging.StreamHandler', return_value=logging.NullHandler()), \
            patch('logging.basicConfig'):
        spec.loader.exec_module(module)
    module.requests.get = MagicMock()
    module.requests.post = MagicMock()
    module.logger = MagicMock()
    return module


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.agent = load_agent()
        self.runner = patch.object(self.agent, '_bounded_log_process')
        self.run = self.runner.start()
        self.addCleanup(self.runner.stop)
        self.run.return_value = (b'new\nold\n', b'', 0, False)

    def test_sources_are_fixed_units_and_system_has_no_unit(self):
        for source, unit in [('agent', 'device-agent.service'), ('frpc', 'frpc.service'),
                             ('docker', 'docker.service'), ('system', None)]:
            with self.subTest(source=source):
                self.run.reset_mock()
                self.run.side_effect = ([(b'loaded\n', b'', 0, False)] if unit else []) + [
                    (b'new\nold\n', b'', 0, False)]
                result = self.agent.collect_journal_logs({'source': source})
                self.assertEqual(result['content'], 'old\nnew')
                self.assertEqual(result['returned_lines'], 2)
                self.assertEqual(result['source'], source)
                self.assertFalse(result['truncated'])
                self.assertTrue(result['collected_at'].endswith('+00:00'))
                command = self.run.call_args.args[0]
                self.assertIn('--lines=500', command)
                self.assertEqual([arg for arg in command if arg.startswith('--unit=')],
                                 [f'--unit={unit}'] if unit else [])
                if unit:
                    self.assertEqual(self.run.call_args_list[0].args[0],
                                     ['systemctl', 'show', '--property=LoadState', '--value', unit])
                    self.assertEqual(self.run.call_args_list[0].args[1],
                                     self.run.call_args_list[1].args[1])

    def test_frpc_service_suffix_is_not_duplicated(self):
        self.agent.FRP_SERVICE_NAME = 'frpc.service'
        self.run.side_effect = [(b'loaded', b'', 0, False), (b'', b'', 0, False)]
        self.assertNotIn('error', self.agent.collect_journal_logs({'source': 'frpc'}))
        self.assertIn('--unit=frpc.service', self.run.call_args.args[0])

    def test_journal_supports_strings_without_python39_removesuffix(self):
        class Python38String(str):
            removesuffix = None

        for name in ('frpc', 'frpc.service'):
            with self.subTest(name=name):
                self.agent.FRP_SERVICE_NAME = Python38String(name)
                self.run.side_effect = [(b'loaded', b'', 0, False), (b'', b'', 0, False)]
                self.assertNotIn('error', self.agent.collect_journal_logs({'source': 'frpc'}))
                self.assertIn('--unit=frpc.service', self.run.call_args.args[0])

    def test_time_normalization_level_and_line_cap(self):
        result = self.agent.collect_journal_logs({
            'source': 'system', 'lines': 99999, 'level': 'ERROR',
            'start_time': '2026-11-18T12:30:00+08:00',
            'end_time': '2026-11-18T05:30:00Z'})
        self.assertNotIn('error', result)
        command = self.run.call_args.args[0]
        self.assertIn('--since=2026-11-18 04:30:00.000000 UTC', command)
        self.assertIn('--until=2026-11-18 05:30:00.000000 UTC', command)
        self.assertIn('--priority=3..3', command)
        self.assertIn('--lines=2000', command)

    def test_all_levels_use_exact_priority(self):
        for level, number in self.agent.JOURNAL_PRIORITIES.items():
            self.agent.collect_journal_logs({'source': 'system', 'level': level})
            self.assertIn(f'--priority={number}..{number}', self.run.call_args.args[0])

    def test_blank_level_from_platform_means_no_filter(self):
        result = self.agent.collect_journal_logs({'source': 'system', 'level': ''})
        self.assertEqual(result['returned_lines'], 2)
        self.assertFalse(any(arg.startswith('--priority=') for arg in self.run.call_args.args[0]))

    def test_utf8_output_remains_within_text_cap(self):
        encoded = ('\u6d4b\u8bd5\n' * 100000).encode('utf-8')[:512 * 1024]
        self.run.return_value = (encoded, b'', -9, True)
        result = self.agent.collect_journal_logs({'source': 'system', 'lines': 2000})
        self.assertLessEqual(len(result['content'].encode('utf-8')), 512 * 1024)
        self.assertLessEqual(result['returned_lines'], 2000)
        self.assertTrue(result['truncated'])

    def test_validation_rejects_untrusted_parameters(self):
        invalid = [None, {}, {'source': '../system'}, {'source': ['system']},
                   {'source': 'system', 'command': 'id'}, {'source': 'system', 'unit': 'ssh'},
                   {'source': 'system', 'path': '/etc/passwd'},
                   {'source': 'system', 'level': '3;id'}, {'source': 'system', 'level': []},
                   {'source': 'system', 'keyword': 'x' * 1025},
                   {'source': 'system', 'keyword': []}]
        invalid += [{'source': 'system', 'lines': value} for value in (0, -1, True, '10', 1.5)]
        invalid += [{'source': 'system', 'start_time': value} for value in (
            '@123456', 'yesterday', '--since=now', '2026-11-18', '2026-02-30T00:00:00Z',
            '2026-11-18T00:00:00Z;id', 1234, '', '2026-11-18T00:00:00\n')]
        invalid.append({'source': 'system', 'start_time': '2026-11-19T00:00:00Z',
                        'end_time': '2026-11-18T00:00:00Z'})
        for params in invalid:
            with self.subTest(params=params):
                self.assertIn('error', self.agent.collect_journal_logs(params))
        self.run.assert_not_called()

    def test_keyword_is_literal_and_limited_to_returned_window(self):
        self.run.return_value = (b'new $(id)\nnew other\nold $(id)\n', b'', 0, False)
        result = self.agent.collect_journal_logs({'source': 'system', 'lines': 2, 'keyword': '$(id)'})
        self.assertEqual(result['content'], 'new $(id)')
        self.assertEqual(result['returned_lines'], 1)
        self.assertTrue(result['truncated'])
        self.assertFalse(any('$(id)' in arg for arg in self.run.call_args.args[0]))

    def test_no_entries_is_success(self):
        for output in (b'', b'-- No entries --\n', b'-- Journal begins at date, ends at date. --\n-- No entries --\n'):
            self.run.return_value = (output, b'', 0, False)
            result = self.agent.collect_journal_logs({'source': 'system'})
            self.assertEqual(result['content'], '')
            self.assertEqual(result['returned_lines'], 0)

    def test_diagnostics_and_runtime_failures_are_actionable(self):
        for diagnostic, expected in [(b'Permission denied', 'permission denied'),
                                      (b'Hint: You are currently not seeing messages from other users and the system.', 'permission denied'),
                                      (b'No journal files were found.', 'Journal unavailable'),
                                      (b'corrupt journal', 'journalctl failed')]:
            with self.subTest(diagnostic=diagnostic):
                self.run.return_value = (b'', diagnostic, 1, False)
                self.assertIn(expected, self.agent.collect_journal_logs({'source': 'system'})['error'])
        for failure, expected in [(FileNotFoundError(), 'Journal unavailable'),
                                  (PermissionError(), 'permission denied'),
                                  (OSError('disk failed'), 'disk failed'),
                                  (subprocess.TimeoutExpired('journalctl', 15), '15 seconds')]:
            self.run.side_effect = failure
            self.assertIn(expected, self.agent.collect_journal_logs({'source': 'system'})['error'])

    def test_absent_service_and_unavailable_systemd_are_distinct(self):
        for state, code, expected in [(b'not-found', 0, 'is absent'),
                                       (b'', 1, 'Service lookup unavailable')]:
            self.run.return_value = (state, b'', code, False)
            self.assertIn(expected, self.agent.collect_journal_logs({'source': 'agent'})['error'])

    def test_truncation_survives_killed_journal_exit_status(self):
        self.run.return_value = (b'new\nold\n', b'', -9, True)
        result = self.agent.collect_journal_logs({'source': 'system'})
        self.assertTrue(result['truncated'])
        self.assertEqual(result['content'], 'old\nnew')


class StreamingTests(unittest.TestCase):
    def setUp(self):
        self.agent = load_agent()
        self.process = MagicMock()
        self.process.stdout = io.BytesIO(b'x' * (512 * 1024 + 100))
        self.process.stderr = io.BytesIO()
        self.process.poll.return_value = None
        self.process.returncode = 0
        self.mapping = {}
        self.selector = MagicMock()
        self.selector.register.side_effect = lambda file, event, data: self.mapping.update({
            file: types.SimpleNamespace(fileobj=file, data=data)})
        self.selector.unregister.side_effect = self.mapping.pop
        self.selector.get_map.side_effect = lambda: self.mapping
        self.selector.select.side_effect = lambda timeout: [(v, 1) for v in list(self.mapping.values())]
        self.patches = [patch.object(self.agent.subprocess, 'Popen', return_value=self.process),
                        patch.object(self.agent.selectors, 'DefaultSelector'),
                        patch.object(self.agent.os, 'read')]
        self.popen, selector_factory, self.read = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)
        selector_factory.return_value.__enter__.return_value = self.selector
        # fileno is unavailable on BytesIO, so use tiny file doubles around real buffers.
        self.buffers = {10: self.process.stdout, 11: self.process.stderr}
        self.process.stdout = MagicMock()
        self.process.stdout.fileno.return_value = 10
        self.process.stderr = MagicMock()
        self.process.stderr.fileno.return_value = 11
        self.read.side_effect = lambda fd, count: self.buffers[fd].read(count)

    def test_streaming_byte_limit_and_cleanup_without_capture_output(self):
        out, err, code, clipped = self.agent._bounded_log_process(
            ['journalctl', '--lines=2000'], self.agent.time.monotonic() + 15)
        self.assertEqual(len(out), 512 * 1024)
        self.assertEqual(err, b'')
        self.assertTrue(clipped)
        self.process.kill.assert_called()
        self.process.wait.assert_called()
        self.process.stdout.close.assert_called_once()
        self.process.stderr.close.assert_called_once()
        self.assertTrue(all(call.args[1] <= 8192 for call in self.read.call_args_list))
        self.assertFalse(self.popen.call_args.kwargs['shell'])
        self.assertNotIn('capture_output', self.popen.call_args.kwargs)

    def test_wait_timeout_kills_and_reaps(self):
        self.buffers[10] = io.BytesIO()
        self.process.wait.side_effect = [subprocess.TimeoutExpired('journalctl', 15), 0]
        with self.assertRaises(subprocess.TimeoutExpired):
            self.agent._bounded_log_process(['journalctl'], self.agent.time.monotonic() + 15)
        self.process.kill.assert_called_once()
        self.assertEqual(self.process.wait.call_count, 2)

    def test_deadline_kills_and_reaps_even_without_pipe_activity(self):
        self.selector.select.return_value = []
        self.selector.select.side_effect = None
        with patch.object(self.agent.time, 'monotonic', side_effect=[0, 16]):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.agent._bounded_log_process(['journalctl'], 15)
        self.selector.select.assert_called_once_with(15)
        self.process.kill.assert_called_once()
        self.process.wait.assert_called_once_with(timeout=1)
        self.process.stdout.close.assert_called_once()

    def test_small_stdout_and_stderr_drain_to_eof(self):
        self.buffers[10] = io.BytesIO(b'log\n')
        self.buffers[11] = io.BytesIO(b'diagnostic')
        self.process.poll.return_value = 0
        out, err, code, clipped = self.agent._bounded_log_process(
            ['journalctl'], self.agent.time.monotonic() + 15)
        self.assertEqual((out, err, code, clipped), (b'log\n', b'diagnostic', 0, False))
        self.process.kill.assert_not_called()

    def test_stderr_is_also_bounded(self):
        self.buffers[10] = io.BytesIO()
        self.buffers[11] = io.BytesIO(b'e' * (512 * 1024 + 100))
        out, err, code, clipped = self.agent._bounded_log_process(
            ['journalctl'], self.agent.time.monotonic() + 15)
        self.assertEqual(len(out) + len(err), 512 * 1024)
        self.assertTrue(clipped)


class BusinessLogTests(unittest.TestCase):
    def setUp(self):
        self.agent = load_agent()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'logs'
        self.date = '2026-11-18'
        self.day = self.root / self.date
        self.day.mkdir(parents=True)
        self.agent.MIDDLEWARE_LOG_DIR = str(self.root)
        self.file = self.day / 'sample.log'
        self.file.write_bytes(b'[INFO] first\n[ERROR] Needle\n[ERROR] needle\n')

    def read(self, **kwargs):
        return self.agent.read_log_file({'date': self.date, 'file': 'sample.log', **kwargs})

    def test_list_and_missing_date_contract(self):
        self.assertEqual(self.agent.list_log_files({}), {
            'dates': [self.date], 'files': {self.date: ['sample.log']}})
        self.assertEqual(self.agent.list_log_files({'date': '2026-11-17'}), {'dates': [], 'files': {}})

    def test_business_logs_work_without_python39_path_is_relative_to(self):
        with patch.object(self.agent.Path, 'is_relative_to', None, create=True):
            self.assertEqual(self.agent.list_log_files({})['files'][self.date], ['sample.log'])
            self.assertEqual(self.read()['returned_lines'], 3)
            self.assertEqual(self.agent.search_logs({'keyword': 'needle'})['returned_matches'], 2)
            archive = self.agent.download_log_files({'date': self.date, 'files': ['sample.log']})
            self.assertNotIn('error', archive)

    def test_read_head_tail_and_legacy_zero_lines(self):
        result = self.read(lines=0)
        self.assertEqual(result['total_lines'], 3)
        self.assertTrue(result['total_lines_exact'])
        self.assertEqual(result['returned_lines'], 3)
        self.assertEqual(self.read(lines=1)['content'], '[INFO] first\n')
        self.assertEqual(self.read(lines=1, tail=True)['content'], '[ERROR] needle\n')

    def test_read_caps_lines_bytes_and_single_huge_line(self):
        self.file.write_bytes(b'x\n' * 2500)
        result = self.read(lines=9000)
        self.assertEqual(result['returned_lines'], 2000)
        self.assertEqual(result['total_lines'], 2500)
        self.assertTrue(result['truncated'])
        self.file.write_bytes(b'x' * (600 * 1024) + b'\nlast\n')
        result = self.read()
        self.assertLessEqual(len(result['content'].encode()), 512 * 1024)
        self.assertTrue(result['truncated'])
        self.assertEqual(self.read(lines=1, tail=True)['content'], 'last\n')

    def test_read_scan_cap_and_tail_of_large_file(self):
        self.file.write_bytes(b'first\n' + b'x\n' * 50 + b'last\n')
        with patch.object(self.agent, 'MAX_LOG_SCAN_BYTES', 32):
            head = self.read(lines=1)
            tail = self.read(lines=1, tail=True)
        self.assertEqual(head['content'], 'first\n')
        self.assertEqual(tail['content'], 'last\n')
        self.assertFalse(head['total_lines_exact'])
        self.assertFalse(tail['total_lines_exact'])
        self.assertTrue(tail['truncated'])

    def test_head_preserves_contiguous_prefix_at_byte_cap(self):
        self.file.write_bytes(b'first\n' + b'x' * 20 + b'\nlast\n')
        with patch.object(self.agent, 'MAX_LOG_TEXT_BYTES', 24):
            result = self.read()
        self.assertEqual(result['content'], 'first\n')
        self.assertTrue(result['truncated'])

    def test_search_contract_level_case_and_date_range(self):
        result = self.agent.search_logs({'keyword': 'NEEDLE', 'level': 'ERROR',
                                         'start_date': self.date, 'end_date': self.date})
        self.assertEqual(result['total_matches'], 2)
        self.assertEqual(result['returned_matches'], 2)
        self.assertEqual(result['matches'][0], {'date': self.date, 'file': 'sample.log',
                                               'line_num': 2, 'content': '[ERROR] Needle'})
        exact = self.agent.search_logs({'keyword': 'Needle', 'case_sensitive': True})
        self.assertEqual(exact['total_matches'], 1)

    def test_search_blank_level_from_platform_means_no_filter(self):
        self.assertEqual(self.agent.search_logs({'keyword': 'needle', 'level': ''})['total_matches'], 2)

    def test_search_caps_matches_text_and_scanning(self):
        self.file.write_bytes(b'needle\n' * 1000)
        result = self.agent.search_logs({'keyword': 'needle'})
        self.assertEqual(result['returned_matches'], 500)
        self.assertTrue(result['truncated'])
        with patch.object(self.agent, 'MAX_LOG_SCAN_BYTES', 10):
            result = self.agent.search_logs({'keyword': 'needle'})
        self.assertLess(result['returned_matches'], 3)
        self.assertTrue(result['truncated'])
        self.file.write_bytes((b'needle' + b'x' * 299994 + b'\n') * 2)
        result = self.agent.search_logs({'keyword': 'needle'})
        self.assertLessEqual(sum(len(m['content'].encode()) for m in result['matches']), 512 * 1024)
        self.assertTrue(result['truncated'])

    def test_download_contract_archive_contents_and_missing_file_compatibility(self):
        result = self.agent.download_log_files({'date': self.date, 'files': ['sample.log', 'missing.log']})
        archive = base64.b64decode(result['content'])
        self.assertEqual(result['filename'], f'logs_{self.date}.zip')
        self.assertEqual(result['size'], len(archive))
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            self.assertEqual(zipped.namelist(), ['sample.log'])
            self.assertEqual(zipped.read('sample.log'), self.file.read_bytes())

    def test_download_raw_and_archive_caps(self):
        with patch.object(self.agent, 'MAX_LOG_ARCHIVE_BYTES', 10):
            self.assertIn('16 MiB', self.agent.download_log_files({
                'date': self.date, 'files': ['sample.log']})['error'])
        self.file.write_bytes(b'a')
        with patch.object(self.agent, 'MAX_LOG_ARCHIVE_BYTES', 100):
            self.assertIn('archive exceeds', self.agent.download_log_files({
                'date': self.date, 'files': ['sample.log']})['error'])

    def test_download_growth_cannot_bypass_scan_cap(self):
        with patch.object(self.agent, 'MAX_LOG_SCAN_BYTES', 8):
            result = self.agent.download_log_files({'date': self.date, 'files': ['sample.log']})
        self.assertIn('exceeds', result['error'])

    def test_all_helpers_reject_traversal_absolute_paths_and_bad_calendar_dates(self):
        for value in ('../escape', '/tmp', 'C:\\logs', '2026-2-03', '2026-02-30', '2026-11-18/..'):
            for call in (lambda: self.agent.list_log_files({'date': value}),
                         lambda: self.agent.read_log_file({'date': value, 'file': 'sample.log'}),
                         lambda: self.agent.search_logs({'keyword': 'x', 'start_date': value}),
                         lambda: self.agent.download_log_files({'date': value, 'files': ['sample.log']})):
                with self.subTest(date=value):
                    self.assertIn('error', call())
        for filename in ('../secret', '/etc/passwd', 'C:\\secret', '..\\secret', '.', '..', 'file:stream', '\x00'):
            with self.subTest(filename=filename):
                self.assertIn('error', self.agent.read_log_file({'date': self.date, 'file': filename}))
                self.assertIn('error', self.agent.download_log_files({'date': self.date, 'files': [filename]}))

    def test_symlink_escape_is_rejected_and_not_listed_or_searched(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (outside / 'secret.log').write_bytes(b'private needle\n')
        try:
            (self.day / 'escape.log').symlink_to(outside / 'secret.log')
            (self.root / '2026-11-17').symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f'OS does not permit test symlinks: {exc}')
        self.assertIn('error', self.agent.read_log_file({'date': self.date, 'file': 'escape.log'}))
        self.assertIn('error', self.agent.download_log_files({'date': self.date, 'files': ['escape.log']}))
        self.assertIn('error', self.agent.list_log_files({'date': '2026-11-17'}))
        self.assertNotIn('escape.log', self.agent.list_log_files({})['files'][self.date])
        self.assertEqual(self.agent.search_logs({'keyword': 'private'})['matches'], [])

    def test_resolved_file_and_date_containment_without_symlink_privileges(self):
        outside = Path(self.temp.name) / 'outside'
        for resolved in ([self.root, outside], [self.root, self.day, outside / 'secret.log']):
            with patch.object(self.agent.Path, 'resolve', side_effect=resolved):
                with self.assertRaisesRegex(ValueError, 'escapes'):
                    self.agent._log_path(self.date, 'sample.log')

    def test_non_regular_files_are_rejected(self):
        with self.assertRaises(ValueError):
            # os.devnull opens on both Windows and Linux but is not a regular file.
            self.agent._open_log(os.devnull)

    def test_scan_duration_and_directory_entry_limits(self):
        with patch.object(self.agent, 'LOG_SCAN_SECONDS', -1):
            self.assertTrue(self.read()['truncated'])
            self.assertIn('limit', self.agent.list_log_files({})['error'])
            self.assertIn('timed out', self.agent.download_log_files({
                'date': self.date, 'files': ['sample.log']})['error'])
        with self.assertRaisesRegex(ValueError, 'scan limit'):
            self.agent._log_entries(self.day, {'entries': 0, 'names': 100, 'deadline': float('inf')})

    def test_missing_files_permission_errors_and_invalid_options(self):
        self.assertIn('not found', self.agent.read_log_file({'date': self.date, 'file': 'missing'})['error'])
        for lines in (-1, '500', True):
            self.assertIn('error', self.read(lines=lines))
        with patch.object(self.agent, '_open_log', side_effect=PermissionError('permission denied')):
            self.assertIn('permission denied', self.read()['error'])
            self.assertIn('permission denied', self.agent.search_logs({'keyword': 'needle'})['error'])
        self.assertIn('error', self.agent.search_logs({'keyword': 'x', 'start_date': '2026-11-19', 'end_date': self.date}))
        self.assertIn('error', self.agent.download_log_files({'date': self.date, 'files': ['a'] * 101}))


class PollTests(unittest.TestCase):
    def test_all_task_types_keep_report_contract_and_failures(self):
        agent = load_agent()
        handlers = {'list': 'list_log_files', 'read': 'read_log_file',
                    'search': 'search_logs', 'download': 'download_log_files',
                    'journal': 'collect_journal_logs'}
        tasks = []
        for index, (task_type, handler) in enumerate(handlers.items()):
            setattr(agent, handler, MagicMock(return_value={'example': task_type}))
            tasks.append({'task_id': index, 'task_type': task_type, 'params': {'test': index}})
        tasks += [{'task_id': 5, 'task_type': 'unknown', 'params': {}},
                  {'task_id': 6, 'task_type': 'journal', 'params': {}}]
        agent.collect_journal_logs.side_effect = [{'example': 'journal'}, {'error': 'permission denied'}]
        agent.get_device_id = lambda: 'test-device'
        agent.requests.get.return_value.status_code = 200
        agent.requests.get.return_value.json.return_value = {'tasks': tasks}
        agent.requests.post.return_value.status_code = 200
        agent.poll_and_execute_log_tasks()
        agent.requests.get.assert_called_once_with(
            f'{agent.CLOUD_SERVER}/devices/test-device/pending_log_tasks/',
            params={'limit': 1}, timeout=10,
        )
        reports = [call.kwargs['json'] for call in agent.requests.post.call_args_list]
        self.assertEqual(len(reports), 7)
        for index, task_type in enumerate(handlers):
            self.assertEqual(reports[index], {'task_id': index, 'status': 'completed',
                                              'result': {'example': task_type}, 'error_message': ''})
        self.assertEqual(reports[-1], {'task_id': 6, 'status': 'failed', 'result': {},
                                       'error_message': 'permission denied'})
        self.assertEqual(reports[-2]['status'], 'failed')
        self.assertEqual(agent.AGENT_VERSION, '1.7.3')


if __name__ == '__main__':
    unittest.main()
