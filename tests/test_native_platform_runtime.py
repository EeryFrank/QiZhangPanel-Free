# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Platform guards plus actual inert native UDP/stdin process, not game proof."""
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'src/backend'))
import native_platforms as platforms
import native_platform_launch as launch
import native_launch_settings as settings
from native_managed_launch import build_launch, owned_process_pid, owned_exit_snapshot
from server_registry import ServerRegistry
from server_manager import ServerManager, PanelError


class PlatformRuntimeTests(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.gettempdir()) / 'QiZhangPanel-Free-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'server'
        self.root.mkdir()

    def manager(self, platform='bedrock'):
        return ServerManager(self.root, Path(self.temp.name) / 'panel', server_id='qa-platform',
                             platform=platform, launch_script=launch.LAUNCHER, supports_watchdog=False)

    def native(self):
        (self.root / 'bedrock_server.exe').write_bytes(b'inert file, not executable')
        return launch.write(self.root, 'bedrock', 'bedrock_server.exe', server_id='qa-platform')

    def test_platform_set_and_capability_copy(self):
        expected = 'vanilla fabric quilt forge neoforge bukkit spigot paper purpur folia sponge arclight catserver mohist magma bedrock nukkit pocketmine velocity bungeecord waterfall custom'.split()
        self.assertEqual(set(platforms.PLATFORMS), set(expected))
        p = platforms.profile('velocity'); p['capabilities']['save_world'] = True
        self.assertFalse(platforms.profile('velocity')['capabilities']['save_world'])
        self.assertEqual(platforms.profile('bungeecord')['default_port'], 25577)
        self.assertEqual(platforms.profile('bedrock')['network_protocol'], 'UDP')
        self.assertEqual(platforms.profile('pocketmine')['runtime'], 'php')

    def test_native_writer_argv_and_no_java_probe(self):
        self.native(); manager = self.manager()
        with patch('native_server_install.inspect_java', side_effect=AssertionError('must not inspect Java')):
            args, env = build_launch(manager)
            value = settings.inspect(manager)
        self.assertEqual(args, [str(self.root / 'bedrock_server.exe')])
        self.assertFalse(value['java_applicable'])
        self.assertEqual(value['platform_profile']['id'], 'bedrock')
        self.assertEqual(env['QIZHANG_SERVER_ROOT'], str(self.root))

    def test_php_preserves_runtime_arguments_and_explicit_phar(self):
        (self.root / 'PocketMine-MP.phar').write_bytes(b'inert')
        (self.root / 'runtime').mkdir(); (self.root / 'runtime/php.exe').write_bytes(b'inert')
        launch.write(self.root, 'pocketmine', 'PocketMine-MP.phar', 'runtime/php.exe',
                     ['-d', 'memory_limit=512M'], ['--no-wizard', '中文 空格'], 'qa-platform')
        args, _ = build_launch(self.manager('pocketmine'))
        self.assertEqual(args, [str(self.root / 'runtime/php.exe'), '-d', 'memory_limit=512M',
                               str(self.root / 'PocketMine-MP.phar'), '--no-wizard', '中文 空格'])

    def test_missing_php_never_silently_uses_java(self):
        (self.root / 'PocketMine-MP.phar').write_bytes(b'inert')
        with self.assertRaisesRegex(PanelError, 'PHP'):
            launch.write(self.root, 'pocketmine', 'PocketMine-MP.phar')
        self.assertFalse((self.root / launch.CONFIG).exists())

    def test_outside_entry_and_wrong_image_rejected(self):
        for entry in ('../bedrock_server.exe', str(self.root / 'bedrock_server.exe'), 'cmd.exe'):
            with self.subTest(entry=entry), self.assertRaises(PanelError):
                launch.write(self.root, 'bedrock', entry)
        self.native()
        outside = Path(self.temp.name) / 'bedrock_server.exe'; outside.write_bytes(b'inert')
        with self.assertRaises(PanelError):
            launch.write(self.root, 'bedrock', 'bedrock_server.exe', str(outside))

    def test_tampered_launcher_or_server_identity_fails_closed(self):
        self.native(); manager = self.manager()
        (self.root / launch.LAUNCHER).write_text('echo changed', encoding='utf-8')
        with self.assertRaisesRegex(PanelError, '修改'):
            build_launch(manager)
        self.native(); manager.server_id = 'other'
        with self.assertRaisesRegex(PanelError, '实例'):
            build_launch(manager)

    def test_arguments_reject_multiline_control_and_nonlist(self):
        self.native()
        for values in (["hello\nstop"], ['x\0y'], [None], {'x': 'y'}):
            with self.subTest(values=values), self.assertRaises(PanelError):
                launch.write(self.root, 'bedrock', 'bedrock_server.exe', server_args=values)

    def test_registry_native_without_server_properties_validates_entry(self):
        self.native()
        value = ServerRegistry._validated_definition(dict(id='qa-platform', name='Native QA', platform='bedrock',
                     path=str(self.root), launch_script=launch.LAUNCHER, supports_watchdog=False))
        self.assertEqual(value['platform'], 'bedrock')
        (self.root / 'bedrock_server.exe').unlink()
        with self.assertRaises(PanelError):
            ServerRegistry._validated_definition(value)

    def test_proxy_endpoint_real_toml_ipv6_and_no_game_properties(self):
        (self.root / 'velocity.toml').write_text('bind = "[::1]:47640"\n[servers]\nlobby="127.0.0.1:25565"\n', encoding='utf-8')
        self.assertEqual(self.manager('velocity')._runtime_endpoint(), (47640, 'TCP'))
        self.assertEqual(platforms.proxy_endpoint(self.root, 'velocity')['server-ip'], '::1')

    def test_bungee_unique_listener_zero_indent_and_ambiguity(self):
        config = self.root / 'config.yml'
        config.write_text('listeners:\n- host: 127.0.0.1:47641\nservers:\n  hub:\n    address: 127.0.0.1:25565\n', encoding='utf-8')
        self.assertEqual(platforms.proxy_endpoint(self.root, 'bungeecord')['server-port'], '47641')
        config.write_text('listeners:\n- host: 127.0.0.1:47641\n- host: 127.0.0.1:47642\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            platforms.proxy_endpoint(self.root, 'bungeecord')

    def test_ready_markers_are_platform_specific(self):
        for platform, marker in [('bedrock', 'Server started.'), ('velocity', 'Done (0.50s)!'),
                                 ('bungeecord', 'Listening on /127.0.0.1:25577'),
                                 ('pocketmine', 'Done (1.23s)! For help, type "help"')]:
            with self.subTest(platform=platform):
                self.assertTrue(platforms.ready_line(platform, marker))
                self.assertFalse(platforms.ready_line('vanilla', marker))

    def test_udp_endpoint_detects_udp_listener_even_if_tcp_is_free(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as occupied:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            occupied.bind(('127.0.0.1', 0)); port = occupied.getsockname()[1]
            ServerManager._check_server_endpoint_available({'server-ip': '127.0.0.1', 'server-port': port, 'network_protocol': 'TCP'})
            with self.assertRaises(PanelError):
                ServerManager._check_server_endpoint_available({'server-ip': '127.0.0.1', 'server-port': port, 'network_protocol': 'UDP'})

    def test_proxy_stop_only_sends_end(self):
        manager = self.manager('velocity'); manager.validated_server_pid = Mock(return_value=120)
        manager.send_command = Mock(); manager.stop_server()
        manager.send_command.assert_called_once_with('end')

    def test_native_stop_only_sends_stop(self):
        manager = self.manager(); manager.validated_server_pid = Mock(return_value=120)
        manager.send_command = Mock(); manager.stop_server()
        manager.send_command.assert_called_once_with('stop')

    def test_proxy_rejects_world_players_and_gamerules_before_any_write(self):
        manager = self.manager('velocity')
        manager.send_command = Mock(); manager._update_properties = Mock(); manager.start_operation = Mock()
        for action in [lambda: manager.request_server_action('save'), lambda: manager.create_light_backup(),
                         lambda: manager.update_settings({'server_properties': {'server-port': 12345}, 'gamerules': {'keepInventory': True}})]:
            with self.assertRaises(PanelError): action()
        manager.send_command.assert_not_called(); manager._update_properties.assert_not_called(); manager.start_operation.assert_not_called()

    def test_native_rejects_java_memory_and_invalid_game_properties(self):
        manager = self.manager(); manager._update_jvm_memory = Mock()
        with self.assertRaises(PanelError): manager.update_settings({'jvm': {'xmx': '2G'}})
        with self.assertRaises(PanelError): manager._update_properties({'server-ip': '127.0.0.1'})
        manager._update_jvm_memory.assert_not_called()

    def test_nonjava_missing_owned_console_never_tries_attach_or_rcon(self):
        manager = self.manager('velocity'); manager.validated_server_pid = Mock(return_value=31)
        with (patch('native_console_pipe.send_command', return_value=False), patch('native_command_bridge.send_command') as attach,
                patch('native_rcon.send_command') as rcon):
            with self.assertRaisesRegex(PanelError, '标准输入'): manager.send_command('end')
            attach.assert_not_called(); rcon.assert_not_called()

    def test_native_default_backup_is_offline_and_includes_worlds(self):
        manager = self.manager()
        self.assertEqual(manager._normalise_backup_mode(), 'full')
        self.assertIn('worlds', manager._platform_backup_items())
        self.assertNotIn('world', manager._platform_backup_items())

    def test_native_unknown_snapshot_never_claims_stopped(self):
        self.native(); manager = self.manager()
        with patch('native_managed_launch._native_process_rows', side_effect=OSError('denied')):
            self.assertIsNone(manager._startup_process_snapshot(force=True))

    def test_settings_save_rolls_back_when_binding_write_fails(self):
        self.native(); manager = self.manager()
        manager._server_endpoint_lock_reason = Mock(return_value='')
        before = {name: (self.root / name).read_bytes() for name in (launch.CONFIG, launch.SCRIPT, launch.LAUNCHER)}
        with self.assertRaisesRegex(RuntimeError, 'persist failed'):
            settings.save(manager, {'server_args': ['changed']}, persist_launcher=Mock(side_effect=RuntimeError('persist failed')))
        self.assertEqual(before, {name: (self.root / name).read_bytes() for name in before})

    def test_bedrock_bind_editable_only_for_explicit_nethernet(self):
        manager = self.manager()
        self.assertNotIn('server-ip', manager._platform_editable_properties())
        manager.server_properties_path.write_text('transport=nethernet\n', encoding='utf-8')
        self.assertIn('server-ip', manager._platform_editable_properties())

    def test_nukkit_does_not_invent_nogui_or_require_game_java21(self):
        manager = self.manager('nukkit')
        (self.root / 'server.jar').write_bytes(b'inert')
        with (patch.object(settings, 'detect_core', return_value=('nukkit', 'jar', 'server.jar')),
              patch.object(settings, 'detect_minecraft_version', return_value=('', [])),
              patch.object(settings, 'jar_manifest', return_value={}),
              patch('native_server_archive.core_java_requirement', return_value={'major': 17, 'known': True, 'bits': 64})):
            value = settings.inspect(manager)
        self.assertTrue(value['supported'], value)
        self.assertEqual(value['server_args'], [])
        self.assertIsNone(value['java_requirement']['major'])
        self.assertEqual(value['java_requirement']['minimum_major'], 17)

    def test_actual_offline_bedrock_backup_and_restore_includes_worlds_and_plugins(self):
        manager = self.manager()
        manager.server_properties_path.write_bytes(b'server-port=19132\n')
        marker = self.root / 'worlds/MyWorld/db/CURRENT'; marker.parent.mkdir(parents=True)
        marker.write_bytes(b'original native data')
        plugin = self.root / 'plugins/settings.yml'; plugin.parent.mkdir(); plugin.write_bytes(b'preserve=yes')
        manager.validated_server_pid = Mock(return_value=0)
        manager._startup_process_snapshot = Mock(return_value={'java_pid': 0, 'launcher_pids': [], 'watchdog_pids': []})
        backup = manager.create_backup()
        with zipfile.ZipFile(backup) as archive:
            self.assertEqual(archive.read('worlds/MyWorld/db/CURRENT'), b'original native data')
            self.assertEqual(archive.read('plugins/settings.yml'), b'preserve=yes')
        marker.write_bytes(b'modified')
        manager.restore_backup(backup.name, backup.name, restart_after=False)
        self.assertEqual(marker.read_bytes(), b'original native data')
        self.assertEqual(plugin.read_bytes(), b'preserve=yes')

    @unittest.skipUnless(os.name == 'nt', 'Actual inert Windows native UDP process')
    def test_actual_native_udp_ready_unicode_console_and_normal_exit(self):
        compiler = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        if not compiler.is_file(): self.skipTest('C# fixture compiler unavailable')
        source = self.root / 'InertNativeFixture.cs'
        source.write_text('''using System; using System.Net; using System.Net.Sockets; using System.Text;
class InertNativeFixture {
 static void Main(string[] args) {
  Console.OutputEncoding = new UTF8Encoding(false); Console.InputEncoding = new UTF8Encoding(false);
  using (var udp = new UdpClient(new IPEndPoint(IPAddress.Loopback, Int32.Parse(args[0])))) {
   Console.WriteLine("Server started.");
   string line; while ((line = Console.ReadLine()) != null) {
    Console.WriteLine("RECEIVED:" + line);
    if (line == "stop") { Console.WriteLine("Stopping server"); return; }
   }
  }
 }
}''', encoding='utf-8')
        result = subprocess.run([str(compiler), '/nologo', '/target:exe', '/platform:x64',
                                '/out:' + str(self.root / 'bedrock_server.exe'), str(source)],
                                capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stdout.decode(errors='replace'))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        launch.write(self.root, 'bedrock', 'bedrock_server.exe', server_args=[str(port)], server_id='qa-platform')
        (self.root / 'server.properties').write_text('server-port=' + str(port) + '\n', encoding='utf-8')
        manager = self.manager(); manager.config['poll_seconds'] = 1
        manager.start_monitor()
        try:
            manager.start_server()
            process = manager._startup_launcher
            self.assertIsNone(process.poll())
            self.assertTrue(manager.get_status()['server']['ready'])
            self.assertEqual(manager.validated_server_pid(), process.pid)
            self.assertEqual(manager._find_port_pid(port, 'UDP'), process.pid)
            self.assertEqual(manager._find_port_pid(port, 'TCP'), 0)
            manager.send_command('say 中文 任意命令')
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and 'RECEIVED:say 中文 任意命令' not in manager.latest_log_path.read_text(encoding='utf-8'):
                time.sleep(.05)
            self.assertIn('RECEIVED:say 中文 任意命令', manager.latest_log_path.read_text(encoding='utf-8'))
            manager.safe_stop_server()
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertEqual(owned_process_pid(manager), 0)
            self.assertEqual(manager._find_port_pid(port, 'UDP'), 0)
            self.assertEqual(manager.latest_log_path.read_text(encoding='utf-8').count('RECEIVED:stop'), 1)
        finally:
            manager._stop_event.set()
            if getattr(manager, '_monitor_thread', None): manager._monitor_thread.join(10)
            process = getattr(manager, '_startup_launcher', None)
            if process is not None:
                if process.poll() is None:
                    # Cleanup only this inert, self-compiled fixture. A failed
                    # assertion remains failed; this is not a product stop pass.
                    process.kill(); process.wait(timeout=5)
                if process.stdin: process.stdin.close()


if __name__ == '__main__':
    unittest.main()
