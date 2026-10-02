# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
import io
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'src/backend'))
import native_console_pipe as pipe
from native_managed_launch import OwnedLaunch


class PipeTests(unittest.TestCase):
    def setUp(self):
        self.process = SimpleNamespace(args=['java.exe', '-jar', 'server.jar'], stdin=io.BytesIO(), _handle=11)
        self.manager = SimpleNamespace(server_id='server-qa', server_root=Path('.').resolve(), launch_script='qizhang-managed-start.bat', _startup_launcher=self.process,
            _console_pipe_lock=threading.Lock(), _console_pipe_pending=None)
        self.manager._owned_direct_launch = OwnedLaunch(self.process, 31, 123, self.manager.server_id, self.manager.server_root, self.manager.launch_script, tuple(self.process.args))
        self.patcher = patch.multiple(pipe, _kernel=Mock(return_value=None), _handle_identity=Mock(return_value=(31, 123, False)))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_utf8_command_is_written_once_to_exact_owned_java(self):
        self.assertTrue(pipe.send_command(self.manager, 31, 'say 七章命令测试'))
        self.assertEqual(self.process.stdin.getvalue(), 'say 七章命令测试\n'.encode())

    def test_original_script_has_no_input_route(self):
        self.manager._owned_direct_launch = None
        self.assertFalse(pipe.send_command(self.manager, 31, 'stop'))
        self.assertEqual(self.process.stdin.getvalue(), b'')

    def test_wrong_birth_server_or_pid_never_writes(self):
        for change in ('birth', 'server', 'pid'):
            with self.subTest(change=change):
                with patch.object(pipe, '_handle_identity', return_value=(31, 124 if change == 'birth' else 123, False)):
                    self.manager.server_id = 'other' if change == 'server' else 'server-qa'
                    with self.assertRaises(pipe.ConsolePipeError):
                        pipe.send_command(self.manager, 32 if change == 'pid' else 31, 'stop')
        self.assertEqual(self.process.stdin.getvalue(), b'')

    def test_closed_or_partial_pipe_raises_and_never_retries(self):
        self.process.stdin.close()
        with self.assertRaises(pipe.ConsolePipeError):
            pipe.send_command(self.manager, 31, 'stop')
        self.process.stdin = Mock(closed=False, write=Mock(return_value=2))
        with self.assertRaisesRegex(pipe.ConsolePipeError, '未切换通道或重试'):
            pipe.send_command(self.manager, 31, 'stop')
        self.process.stdin.write.assert_called_once_with(b'stop\n')

    def test_timeout_does_not_add_workers_or_resend_while_previous_write_is_pending(self):
        release = threading.Event()
        entered = threading.Event()
        def blocked(data):
            entered.set()
            release.wait(3)
            return len(data)
        self.process.stdin = Mock(closed=False, write=Mock(side_effect=blocked))
        try:
            with self.assertRaisesRegex(pipe.ConsolePipeError, '超时'):
                pipe.send_command(self.manager, 31, 'say once', timeout=.02)
            self.assertTrue(entered.is_set())
            with self.assertRaisesRegex(pipe.ConsolePipeError, '本次未发送'):
                pipe.send_command(self.manager, 31, 'say twice', timeout=.02)
            self.process.stdin.write.assert_called_once()
        finally:
            release.set()
            self.manager._console_pipe_pending['done'].wait(3)

    def test_invalid_command_never_writes(self):
        for command in ('', 'stop\nsay again', 'x' * 2001):
            with self.assertRaises(pipe.ConsolePipeError):
                pipe.send_command(self.manager, 31, command)
        self.assertEqual(self.process.stdin.getvalue(), b'')


if __name__ == '__main__':
    unittest.main()
