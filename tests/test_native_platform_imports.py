# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/backend'))
import native_server_archive as archive
import native_platform_config as config
import native_platform_install as providers


def jar(main, java=17, extra=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('META-INF/MANIFEST.MF', 'Main-Class: ' + main + '\r\n')
        z.writestr(main.replace('.', '/') + '.class', b'\xca\xfe\xba\xbe\0\0' + (44 + java).to_bytes(2, 'big'))
        for key, value in (extra or {}).items():
            z.writestr(key, value)
    return out.getvalue()


class PlatformImports(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.gettempdir()) / 'QiZhangPanel-Free-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='qizhang-platform-unit-', dir=base)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_proxy_uses_own_class_floor_not_minecraft_or_optional_vendor(self):
        file = self.root / 'renamed.jar'
        file.write_bytes(jar('net.md_5.bungee.Bootstrap', 11, {
            'net/md_5/bungee/BungeeCord.class': b'\xca\xfe\xba\xbe\0\0\0\x3d',
            'io/netty/optional/Future.class': b'\xca\xfe\xba\xbe\0\0\0\x45'}))
        core = archive.detect_core(self.root)
        self.assertEqual(core[0], 'bungeecord')
        self.assertEqual(archive.core_java_requirement(self.root, core, '')['major'], 17)

    def test_native_zip_never_executes_or_discovers_java(self):
        source = self.root / 'server.zip'
        with zipfile.ZipFile(source, 'w') as z:
            z.writestr('nested/bedrock_server.exe', b'MZ-unit-fixture-not-executable')
            z.writestr('nested/server.properties', 'server-port=19132\n')
            z.writestr('nested/start.cmd', 'bedrock_server.exe\r\n')
        with patch('subprocess.Popen', side_effect=AssertionError('no archive execution')), patch('native_server_install.discover_java', side_effect=AssertionError('native does not use Java')):
            result = archive.install_archive(source, self.root / 'out', '', lambda *_: None)
        self.assertEqual(result['platform'], 'bedrock')
        self.assertIsNone(result['java_major'])
        payload = json.loads((self.root / 'out/qizhang-platform-launch.json').read_text(encoding='utf-8'))
        self.assertEqual(payload['runtime_path'], 'bedrock_server.exe')
        self.assertTrue((self.root / 'out/start.cmd').is_file())

    def test_pocketmine_requires_matching_runtime_in_package(self):
        source = self.root / 'server.zip'
        with zipfile.ZipFile(source, 'w') as z:
            z.writestr('PocketMine-MP.phar', b'not-executed')
        with self.assertRaisesRegex(archive.ArchiveInstallError, 'PHP'):
            archive.install_archive(source, self.root / 'out', '', lambda *_: None)

    def test_proxy_config_preserves_unrelated_settings_and_ipv6(self):
        p = self.root / 'velocity.toml'
        p.write_bytes(b'bind = "0.0.0.0:25565"\r\nonline-mode = true\r\n[servers]\r\nlobby = "127.0.0.1:25566"\r\n')
        config.write_endpoint(self.root, 'velocity', '::1', 32000)
        result = config.read_endpoint(self.root, 'velocity')
        self.assertEqual(result['server-ip'], '::1')
        self.assertEqual(int(result['server-port']), 32000)
        self.assertIn(b'lobby = "127.0.0.1:25566"\r\n', p.read_bytes())

    def test_bungee_zero_indent_yaml_and_multiple_listener_refusal(self):
        p = self.root / 'config.yml'
        p.write_text('listeners:\n- host: 0.0.0.0:25577\n  motd: test\nservers:\n  lobby:\n    address: localhost:25565\n', encoding='utf-8')
        config.write_endpoint(self.root, 'bungeecord', '127.0.0.1', 32001)
        self.assertEqual(int(config.read_endpoint(self.root, 'bungeecord')['server-port']), 32001)
        p.write_text('listeners:\n- host: 0.0.0.0:25577\n- host: 0.0.0.0:25578\n', encoding='utf-8')
        original = p.read_bytes()
        with self.assertRaises(ValueError):
            config.write_endpoint(self.root, 'bungeecord', '', 32002)
        self.assertEqual(p.read_bytes(), original)

    def test_bedrock_transport_is_not_silently_changed(self):
        p = self.root / 'server.properties'
        p.write_text('transport=nethernet\nserver-ip=127.0.0.1\nserver-port=32003\n', encoding='utf-8')
        config.write_endpoint(self.root, 'bedrock', '127.0.0.1', 32004)
        self.assertEqual(config.read_endpoint(self.root, 'bedrock')['server-ip'], '127.0.0.1')
        self.assertIn('transport=nethernet', p.read_text())
        p.write_text('transport=raknet\nserver-port=32003\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            config.write_endpoint(self.root, 'bedrock', '127.0.0.1', 32004)

    def test_experimental_builds_are_not_default_downloads(self):
        data = [{'id': 6, 'channel': 'ALPHA', 'downloads': {'server:default': {'url': 'https://fill-data.papermc.io/file'}}}]
        with patch('native_server_install._metadata_json', side_effect=[{'versions': {'1.21': ['1.21.4']}}, data]):
            result = providers.catalog('folia', '1.21.4')
        self.assertEqual(result['loader_versions'], [])
        self.assertEqual(result['default_loader_version'], '')

    def test_manual_platform_has_official_source_not_fake_download(self):
        result = providers.catalog('spigot')
        self.assertEqual(result['install_method'], 'import')
        self.assertIn('buildtools', result['official_url'])

    def test_index_only_pack_explains_missing_install_steps_for_both_checkbox_states(self):
        source = self.root / 'client-export.zip'
        record = {'formatVersion': 1, 'game': 'minecraft', 'dependencies': {'minecraft': '1.20.1', 'forge': '47.3.33'},
                  'files': [{'path': 'mods/example.jar', 'downloads': ['https://example.invalid/example.jar']}]}
        with zipfile.ZipFile(source, 'w') as z:
            z.writestr('modrinth.index.json', json.dumps(record))
            z.writestr('overrides/config/settings.txt', 'preserve')
        before = source.read_bytes()
        for adapt in (True, False):
            with self.subTest(adapt=adapt), patch('subprocess.Popen', side_effect=AssertionError('no execution')):
                with self.assertRaisesRegex(archive.ArchiveInstallError, 'Modrinth.*1.20.1.*47.3.33'):
                    archive.install_archive(source, self.root / str(adapt), '', lambda *_: None, adapt_startup=adapt)
                self.assertFalse((self.root / str(adapt)).exists())
        self.assertEqual(source.read_bytes(), before)

    def test_installed_server_retaining_index_is_not_misclassified(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as z:
            z.writestr('modrinth.index.json', '{"formatVersion":1,"game":"minecraft"}')
            z.writestr('server.jar', jar('net.minecraft.server.Main'))
        with zipfile.ZipFile(stream) as z:
            archive.check_uninstalled_modpack(z)

    def test_property_continuation_is_not_a_second_endpoint_key(self):
        p = self.root / 'server.properties'
        original = b'\xef\xbb\xbfmotd=hello\\\r\nserver-port=inside-motd\r\n  server-port = 19132\nserver-ip=127.0.0.1\n'
        p.write_bytes(original)
        self.assertEqual(config.read_endpoint(self.root, 'nukkit')['server-port'], 19132)
        config.write_endpoint(self.root, 'nukkit', '127.0.0.1', 32007)
        self.assertEqual(p.read_bytes(), original.replace(b'  server-port = 19132', b'server-port=32007'))

    def test_property_update_cannot_append_into_unterminated_continuation(self):
        p = self.root / 'server.properties'
        original = b'motd=hello\\'
        p.write_bytes(original)
        with self.assertRaisesRegex(ValueError, '续行'):
            config.write_endpoint(self.root, 'nukkit', '127.0.0.1', 32007)
        self.assertEqual(p.read_bytes(), original)

    def test_replacing_a_continued_endpoint_consumes_its_entire_record(self):
        p = self.root / 'server.properties'
        p.write_bytes(b'server-port=19\\\r\n 132\r\nserver-ip=::1\r\nmotd=keep')
        self.assertEqual(config.read_endpoint(self.root, 'nukkit')['server-port'], 19132)
        config.write_endpoint(self.root, 'nukkit', '::1', 32007)
        self.assertEqual(p.read_bytes(), b'server-port=32007\r\nserver-ip=::1\r\nmotd=keep')

    def test_noop_keeps_bom_mixed_newline_mtime_and_spaced_keys(self):
        p = self.root / 'server.properties'
        original = b'\xef\xbb\xbf  server-port = 19132 \rserver-ip = ::1\n# comment\r\nmotd=no-final-newline'
        p.write_bytes(original)
        stamp = p.stat().st_mtime_ns
        config.write_endpoint(self.root, 'nukkit', '::1', 19132)
        self.assertEqual(p.read_bytes(), original)
        self.assertEqual(p.stat().st_mtime_ns, stamp)

    def test_transport_value_cannot_be_forged_by_continued_motd(self):
        p = self.root / 'server.properties'
        original = b'motd=continued\\\ntransport=nethernet\nserver-port=19132\n'
        p.write_bytes(original)
        with self.assertRaises(ValueError):
            config.write_endpoint(self.root, 'bedrock', '127.0.0.1', 32007)
        self.assertEqual(p.read_bytes(), original)

    def test_explicit_spaced_nethernet_allows_ipv6_without_changing_transport(self):
        p = self.root / 'server.properties'
        p.write_bytes(b'  transport = nethernet \r\nserver-port=19132\r\nserver-ip=::1\nserver-portv6=19133\n')
        config.write_endpoint(self.root, 'bedrock', '::1', 32007)
        result = config.read_endpoint(self.root, 'bedrock')
        self.assertEqual(result['server-ip'], '::1')
        self.assertEqual(result['server-port'], 32007)
        self.assertEqual(result['network_protocol'], 'TCP')
        self.assertIn(b'  transport = nethernet \r\n', p.read_bytes())
        self.assertIn(b'server-portv6=19133\n', p.read_bytes())

    def test_ipv6_proxy_preserves_bom_other_sections_and_crlf(self):
        p = self.root / 'velocity.toml'
        original = b'\xef\xbb\xbfbind = "[::1]:25565" # keep comment\r\nonline-mode=true\r\n[servers]\r\nfirst="localhost:25566"\r\n'
        p.write_bytes(original)
        config.write_endpoint(self.root, 'velocity', '::1', 32007)
        self.assertEqual(p.read_bytes(), original.replace(b'[::1]:25565', b'[::1]:32007'))

    def test_bedrock_protocol_tracks_actual_transport_and_unknown_is_not_udp(self):
        from native_platforms import profile
        self.assertEqual(profile('bedrock')['network_protocol'], 'UDP')
        self.assertEqual(profile('bedrock', self.root)['network_protocol'], 'UDP')
        p = self.root / 'server.properties'
        p.write_text('transport=nethernet\n', encoding='utf-8')
        self.assertEqual(profile('bedrock', self.root)['network_protocol'], 'TCP')
        self.assertEqual(config.read_endpoint(self.root, 'bedrock')['network_protocol'], 'TCP')
        p.write_text('transport=raknet\n', encoding='utf-8')
        self.assertEqual(config.read_endpoint(self.root, 'bedrock')['network_protocol'], 'UDP')
        p.write_text('transport=future-unknown\n', encoding='utf-8')
        with self.assertRaises(ValueError): config.read_endpoint(self.root, 'bedrock')

    def test_noop_effective_duplicate_endpoint_preserves_all_physical_lines(self):
        p = self.root / 'server.properties'
        original = b'server-port=10000\n# later value wins\nserver-port=19132\n'
        p.write_bytes(original)
        config.write_endpoint(self.root, 'nukkit', '', 19132)
        self.assertEqual(p.read_bytes(), original)

    def test_port_only_does_not_invent_an_absent_default_bind_key(self):
        p = self.root / 'server.properties'
        p.write_bytes(b'# retain\r\nserver-port=19132\r\n')
        config.write_endpoint(self.root, 'nukkit', '', 32007)
        self.assertEqual(p.read_bytes(), b'# retain\r\nserver-port=32007\r\n')


if __name__ == '__main__':
    unittest.main()
