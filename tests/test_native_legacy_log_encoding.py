"""Legacy Windows log bytes, complete-line replay and process-lifetime boundaries."""
from datetime import datetime
import gzip
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/backend'))
from server_manager import ServerManager, decode_server_log

class LegacyLogEncodingTests(unittest.TestCase):

    def setUp(self):
        base = Path(tempfile.gettempdir()) / 'QiZhangPanel-Free-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.server = self.root / 'server'
        (self.server / 'logs').mkdir(parents=True)
        self.manager = ServerManager(self.server, self.root / 'panel', supports_watchdog=False)
        self.started = datetime(2026, 9, 29, 11, 10, 0)
        self.manager._log_process_started_at = self.started
        self.line = '[299月2026 11:10:10.752] [Server thread/INFO] [net.minecraft.server.dedicated.DedicatedServer/]: Done (3.263s)! For help, type "help"\n'

    def write(self, data):
        self.manager.latest_log_path.write_bytes(data)
        stamp = datetime(2026, 9, 29, 11, 10, 20).timestamp()
        os.utime(self.manager.latest_log_path, (stamp, stamp))

    def test_exact_observed_gbk_month_bytes_become_ready(self):
        data = self.line.encode('gbk')
        self.assertIn(b'299\xd4\xc22026', data)
        self.write(data)
        self.manager._consume_new_log_lines()
        self.assertTrue(self.manager._log_ready_seen)
        self.assertEqual(self.manager._log_position, len(data))
        self.assertNotIn('�', self.manager._recent_log_lines[-1])

    def test_utf8_chinese_and_non_bmp_chat_is_preserved(self):
        line = '[11:10:11] [Server thread/INFO]: 玩家 中文 😀\n'
        self.write(self.line.encode('utf-8') + line.encode('utf-8'))
        self.manager._consume_new_log_lines()
        self.assertTrue(self.manager._log_ready_seen)
        self.assertEqual(self.manager._recent_log_lines[-1], line.rstrip())

    def test_incomplete_multibyte_prefix_is_not_consumed(self):
        data = self.line.encode('gbk')
        cut = data.index(b'\xd4') + 1
        self.write(data[:cut])
        self.manager._consume_new_log_lines()
        self.assertFalse(self.manager._log_ready_seen)
        self.assertEqual(self.manager._log_position, 0)
        with self.manager.latest_log_path.open('ab') as stream:
            stream.write(data[cut:])
        self.manager._consume_new_log_lines()
        self.assertTrue(self.manager._log_ready_seen)
        self.assertEqual(len(self.manager._recent_log_lines), 1)

    def test_done_without_final_newline_waits_for_writer(self):
        prefix = b'[11:10:01] [Server thread/INFO]: Starting\n'
        data = self.line.encode('utf-8')
        self.write(prefix + data[:-1])
        self.manager._consume_new_log_lines()
        self.assertFalse(self.manager._log_ready_seen)
        self.assertEqual(self.manager._log_position, len(prefix))
        with self.manager.latest_log_path.open('ab') as stream:
            stream.write(b'\n')
        self.manager._consume_new_log_lines()
        self.assertTrue(self.manager._log_ready_seen)
        self.assertEqual(len(self.manager._recent_log_lines), 2)

    def test_old_gbk_done_is_not_proof_of_current_process(self):
        self.write(self.line.replace('11:10:10', '11:09:59').encode('gbk'))
        self.manager._consume_new_log_lines()
        self.assertFalse(self.manager._log_ready_seen)

    def test_old_day_is_not_replaced_by_new_file_mtime(self):
        self.write(self.line.replace('299月', '289月').encode('gbk'))
        self.manager._consume_new_log_lines()
        self.assertFalse(self.manager._log_ready_seen)

    def test_invalid_timestamp_and_missing_timestamp_do_not_set_ready(self):
        for line in (self.line.replace('299月', '329月'), self.line[self.line.index(']') + 2:]):
            with self.subTest(line=line):
                self.manager._initialize_log_state()
                self.manager._log_process_started_at = self.started
                self.write(line.encode('gbk'))
                self.manager._consume_new_log_lines()
                self.assertFalse(self.manager._log_ready_seen)

    def test_unbound_process_does_not_accept_even_valid_done(self):
        self.manager._log_process_started_at = None
        self.write(self.line.encode('gbk'))
        self.manager._consume_new_log_lines()
        self.assertFalse(self.manager._log_ready_seen)

    def test_english_month_and_java8_clock_remain_supported(self):
        for line in (self.line.replace('299月2026', '29Sep2026'), self.line.replace('299月2026 11:10:10.752', '11:10:10')):
            with self.subTest(line=line):
                self.manager._initialize_log_state()
                self.manager._log_process_started_at = self.started
                self.write(line.encode('ascii'))
                self.manager._consume_new_log_lines()
                self.assertTrue(self.manager._log_ready_seen)

    def test_rotation_keeps_current_process_ready_and_reads_new_bytes(self):
        self.write(self.line.encode('gbk'))
        self.manager._consume_new_log_lines()
        self.manager.latest_log_path.rename(self.server / 'logs/old.log')
        self.write(b'[11:10:12] [Server thread/INFO]: Player joined the game\n')
        self.manager._consume_new_log_lines()
        self.assertTrue(self.manager._log_ready_seen)
        self.assertEqual(self.manager._online_players, {'Player'})

    def archive(self, name, content):
        path = self.server / 'logs' / name
        with gzip.open(path, 'wb') as stream:
            stream.write(content.encode('gbk'))
        stamp = datetime(2026, 9, 29, 11, 10, 20).timestamp()
        os.utime(path, (stamp, stamp))

    def test_gzip_replay_checks_row_timestamp_not_only_archive_mtime(self):
        self.archive('2026-09-29-1.log.gz', self.line.replace('11:10:10', '11:09:59'))
        self.manager._restore_current_process_logs(self.started.timestamp())
        self.assertFalse(self.manager._log_ready_seen)
        self.archive('2026-09-29-2.log.gz', self.line)
        self.manager._restore_current_process_logs(self.started.timestamp())
        self.assertTrue(self.manager._log_ready_seen)

    def test_gbk_launcher_diagnostics_and_failure_excerpt_are_readable(self):
        path = self.server / 'logs/panel-launcher.stderr.log'
        self.manager._capture_startup_logs()
        path.write_bytes('启动失败：内存不足\n'.encode('gbk'))
        self.assertIn('启动失败：内存不足', self.manager._launcher_log_lines('stderr', 'ERROR', 20)[0])
        self.assertIn('启动失败：内存不足', self.manager._startup_failure_message('失败'))

    def test_utf8_bom_does_not_obscure_first_timestamp(self):
        self.write(self.line.encode('utf-8-sig'))
        self.manager._consume_new_log_lines()
        self.assertTrue(self.manager._log_ready_seen)

    def test_java8_chinese_month_names_all_twelve_map_exactly(self):
        for number, month in enumerate(('一', '二', '三', '四', '五', '六', '七', '八', '九', '十', '十一', '十二'), 1):
            with self.subTest(month=month):
                line = f'[09{month}月2026 11:10:10.752] [Server thread/INFO]: Done (3.0s)! For help, type "help"'
                self.assertEqual(self.manager._logout_timestamp_from_line(line, '2000-01-01'), f'2026-{number:02}-09T11:10:10')

    def test_observed_forge1165_chinese_month_becomes_ready_in_utf8_and_gbk(self):
        line = self.line.replace('299月2026', '29九月2026')
        for encoding in ('utf-8', 'gbk'):
            with self.subTest(encoding=encoding):
                self.manager._initialize_log_state()
                self.manager._log_process_started_at = self.started
                self.write(line.encode(encoding))
                self.manager._consume_new_log_lines()
                self.assertTrue(self.manager._log_ready_seen)

    def test_old_java8_chinese_done_cannot_satisfy_new_process(self):
        line = self.line.replace('299月2026', '29九月2026').replace('11:10:10', '11:09:59')
        self.write(line.encode('utf-8'))
        self.manager._consume_new_log_lines()
        self.assertFalse(self.manager._log_ready_seen)

    def test_invalid_chinese_month_and_impossible_date_are_not_guessed(self):
        for token in ('29十三月2026', '29壹月2026', '29一十月2026', '31二月2026'):
            with self.subTest(token=token):
                self.assertIsNone(self.manager._logout_timestamp_from_line(self.line.replace('299月2026', token), '2026-09-29'))
if __name__ == '__main__':
    unittest.main(verbosity=2)
