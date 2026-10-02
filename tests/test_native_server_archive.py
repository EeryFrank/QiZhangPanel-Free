import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).parents[1] / "src/backend"))
import native_server_archive as archive
from native_server_install import inspect_java as real_inspect_java, ServerInstallError


def jar_entries(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as file:
        for name, content in entries.items():
            file.writestr(name, content)
    return buffer.getvalue()


def server_jar(main="net.minecraft.bundler.Main"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as file:
        file.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nMain-Class: " + main + "\n")
    return buffer.getvalue()


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.gettempdir()) / 'QiZhangPanel-Free-tests'
        base.mkdir(exist_ok=True, parents=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = patch("native_server_install.inspect_java", return_value={"path": r"D:\Java\jdk-21\bin\java.exe", "major": 21, "bits": 64, "version": "21.0.8"})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def package(self, entries):
        path = self.root / "server.zip"
        with zipfile.ZipFile(path, "w") as file:
            for name, content in entries:
                file.writestr(name, content)
        return path

    def catserver_entries(self, **updates):
        spec = {"schema_version": 1, "platform": "forge", "minecraft_version": "1.12.2", "java_major": 8,
                "java_path": "runtime/java8/bin/java.exe", "core_jar": "CatServer.jar", "main_class": archive.CATSERVER_MAIN,
                "classpath": ["libraries/log4j-api-2.25.3.jar", "libraries/log4j-core-2.25.3.jar", "CatServer.jar"],
                "jvm_args": ["-Xms1G", "-Xmx6G", "-XX:+UseG1GC", "-Dfile.encoding=UTF-8", "-Dcatserver.skipCheckLibraries=true"],
                "game_args": ["nogui"], "command_channel": "serverfoundation-file-v1"}
        spec.update(updates)
        return [("CatServer.jar", server_jar(archive.CATSERVER_MAIN)),
                (archive.LAUNCH_MANIFEST, json.dumps(spec)),
                ("runtime/java8/bin/java.exe", b"never execute during import"),
                ("runtime/java8/release", 'JAVA_VERSION="1.8.0_504"\nOS_ARCH="amd64"\nOS_NAME="Windows"\n'),
                ("libraries/log4j-api-2.25.3.jar", b"api"), ("libraries/log4j-core-2.25.3.jar", b"core"),
                ("plugins/ServerFoundation-fixture.jar", jar_entries({"local/mc/foundation/PanelCommandBridge.class": b"fixture"}))]

    def install(self, path):
        return archive.install_archive(path, self.root / "installed", "java", lambda percent, text: None)

    def versioned_server(self, version):
        return jar_entries({"META-INF/MANIFEST.MF": "Main-Class: net.minecraft.bundler.Main\n",
                            "version.json": json.dumps({"id": version})})

    def runtime_entries(self, home, version, arch="amd64", system="Windows", executable=b"never execute archive Java during import"):
        return [(home + "/bin/java.exe", executable),
                (home + "/release", f'JAVA_VERSION="{version}"\nOS_ARCH="{arch}"\nOS_NAME="{system}"\n')]

    def paperclip_entries(self):
        return {
            "META-INF/MANIFEST.MF": "Manifest-Version: 1.0\nMain-Class: io.papermc.paperclip.Main\n\n",
            "io/papermc/paperclip/Main.class": b"static fixture only",
            "version.json": json.dumps({"id": "1.21.1", "java_version": 21}),
            "META-INF/main-class": "org.bukkit.craftbukkit.Main",
            "META-INF/versions.list": "a" * 64 + "\t1.21.1\t1.21.1/paper-1.21.1.jar\n",
            "META-INF/patches.list": "versions\t" + "b" * 64 + "\t" + "c" * 64 + "\t" + "a" * 64 + "\t1.21.1/server.jar\t1.21.1/server.jar.patch\t1.21.1/paper-1.21.1.jar\n",
            "META-INF/download-context": "b" * 64 + "\thttps://piston-data.mojang.com/fixture/server.jar\tmojang_1.21.1.jar",
            "META-INF/versions/1.21.1/server.jar.patch": b"static patch fixture only",
        }

    def test_modern_paperclip_official_descriptor_shape_imports_with_java21_without_execution(self):
        package = self.package([("Server/paper-1.21.1-133.jar", jar_entries(self.paperclip_entries())),
                                ("Server/server.properties", "server-port=25565\n")])
        with patch("subprocess.Popen", side_effect=AssertionError("import cannot launch bundled code")):
            result = self.install(package)
        self.assertEqual(result["minecraft_version"], "1.21.1")
        self.assertEqual(result["java_major"], 21)
        root = Path(result["path"])
        self.assertEqual(json.loads((root / "qizhang-startup.json").read_text())["entry"], "paper-1.21.1-133.jar")

    def test_paperclip_descriptor_conflicts_and_partial_bundles_are_rejected(self):
        variants = {
            "other_target_main": ("META-INF/main-class", "example.SomeOtherBootstrap"),
            "other_minecraft": ("version.json", json.dumps({"id": "1.20.1", "java_version": 17})),
            "wrong_java": ("version.json", json.dumps({"id": "1.21.1", "java_version": 8})),
            "multiple_versions": ("META-INF/versions.list", ("a" * 64 + "\t1.21.1\t1.21.1/paper-1.21.1.jar\n") * 2),
            "target_escape": ("META-INF/versions.list", "a" * 64 + "\t1.21.1\t../paper.jar\n"),
            "wrong_patch_hash": ("META-INF/patches.list", "versions\t" + "b"*64 + "\t" + "c"*64 + "\t" + "d"*64 + "\t1.21.1/server.jar\t1.21.1/server.jar.patch\t1.21.1/paper-1.21.1.jar"),
            "empty_patch": ("META-INF/versions/1.21.1/server.jar.patch", b""),
            "empty_wrapper": ("io/papermc/paperclip/Main.class", b""),
            "oversized_version": ("version.json", " " * 65537),
        }
        jar = self.root / "server.jar"
        for name, (key, value) in variants.items():
            with self.subTest(name=name):
                entries = self.paperclip_entries()
                entries[key] = value
                jar.write_bytes(jar_entries(entries))
                with self.assertRaisesRegex(archive.ArchiveInstallError, "Paperclip"):
                    archive.detect_core(self.root)
        entries = self.paperclip_entries()
        del entries["META-INF/versions/1.21.1/server.jar.patch"]
        jar.write_bytes(jar_entries(entries))
        with self.assertRaisesRegex(archive.ArchiveInstallError, "Paperclip"):
            archive.detect_core(self.root)

    def test_paperclip_filename_cannot_override_internal_minecraft_version(self):
        jar = self.root / "paper-1.20.1.jar"
        jar.write_bytes(jar_entries(self.paperclip_entries()))
        core = archive.detect_core(self.root)
        with self.assertRaisesRegex(archive.ArchiveInstallError, "版本信息冲突"):
            archive.detect_minecraft_version(self.root, core)

    def test_arbitrary_bootstrap_with_paper_metadata_is_not_recognized(self):
        entries = self.paperclip_entries()
        entries["META-INF/MANIFEST.MF"] = "Main-Class: example.Bootstrap\n\n"
        (self.root / "paper-1.21.1.jar").write_bytes(jar_entries(entries))
        self.assertIsNone(archive.detect_core(self.root))

    def test_signed_legacy_forge_main_section_is_bounded_and_signature_entries_cannot_override_it(self):
        jar = self.root / "forge-1.16.5-36.2.34.jar"
        manifest = ("Manifest-Version: 1.0\r\r\nMain-Class: net.minecraftforge.server.ServerMain\r\r\n\r\r\n"
                    "Name: hostile.class\r\r\nMain-Class: unrelated.Main\r\r\n\r\r\n" + "Name: fixture.class\nSHA-256-Digest: x\n\n" * 6000)
        jar.write_bytes(jar_entries({"META-INF/MANIFEST.MF": manifest}))
        self.assertEqual(archive.jar_manifest(jar)["Main-Class"], "net.minecraftforge.server.ServerMain")
        core = archive.detect_core(self.root)
        self.assertEqual(core[:3], ("forge", "jar", jar.name))
        self.assertEqual(archive.detect_minecraft_version(self.root, core)[0], "1.16.5")
        jar.write_bytes(jar_entries({"META-INF/MANIFEST.MF": "X: " + "x" * 70000}))
        with self.assertRaisesRegex(archive.ArchiveInstallError, "主属性"):
            archive.jar_manifest(jar)

    def test_generic_bundled_java8_16_17_21_win64_precedes_wrong_external_selection(self):
        for version, major, home, java_version in (
            ("1.12.2", 8, "runtime/java8", "1.8.0_504"),
            ("1.17.1", 16, "java/jdk-16.0.2", "16.0.2+7"),
            ("1.20.4", 17, "jre", "17.0.16+8"),
            ("1.21.1", 21, "tools/runtimes/java-runtime-delta/windows-x64/jdk", "21.0.8+9-LTS"),
        ):
            with self.subTest(major=major):
                original = [("server.jar", self.versioned_server(version)), *self.runtime_entries(home, java_version)]
                wrapped = [("Wrapper/Server/" + name, data) for name, data in original]
                with patch("native_server_install.inspect_java", side_effect=AssertionError("bundled selection cannot execute Java")), \
                     patch("native_server_install.discover_java", side_effect=AssertionError("bundled runtime has priority")), \
                     patch("subprocess.run", side_effect=AssertionError("must not run archive programs")):
                    definition = archive.install_archive(self.package(wrapped), self.root / str(major), r"D:\wrong-java\bin\java.exe", lambda *args: None)
                target = Path(definition["path"])
                self.assertEqual(definition["java_major"], major)
                self.assertEqual(definition["java_source"], "bundled")
                self.assertEqual((target / "qizhang-java-path.txt").read_text().strip(), home + "/bin/java.exe")
                for name, data in original:
                    self.assertEqual((target / name).read_bytes(), data.encode() if isinstance(data, str) else data)
                metadata = json.loads((target / "qizhang-import.json").read_text(encoding="utf-8"))
                self.assertEqual(metadata["java_validation"], "bundled-release-static-only")
                self.assertEqual(metadata["java_relative_path"], home + "/bin/java.exe")

    def test_multiple_bundled_majors_select_matching_latest_patch_deterministically(self):
        entries = [("server.jar", self.versioned_server("1.12.2")),
                   *self.runtime_entries("runtime/jdk21", "21.0.8"),
                   *self.runtime_entries("runtime/jdk8-old", "1.8.0_202"),
                   *self.runtime_entries("runtime/jdk8-new", "1.8.0_504")]
        with patch("native_server_install.inspect_java", side_effect=AssertionError("must not inspect external Java")):
            result = self.install(self.package(entries))
        self.assertEqual(result["java_relative_path"], "runtime/jdk8-new/bin/java.exe")
        self.assertEqual(len(result["java_selection"]["candidates"]), 2)
        self.assertTrue(any("需要 Java 8" in item["reason"] for item in result["java_selection"]["rejected"]))

    def test_no_bundled_runtime_discovers_the_required_local_major_automatically(self):
        for version, major in (("1.12.2", 8), ("1.17.1", 16), ("1.20.4", 17), ("1.21.1", 21)):
            java = rf"D:\local-jdk{major}\bin\java.exe"
            with self.subTest(major=major), patch("native_server_install.discover_java", return_value=[java]) as discovery, \
                 patch("native_server_install.inspect_java", return_value={"path": java, "major": major, "bits": 64}) as probe:
                result = archive.install_archive(self.package([("server.jar", self.versioned_server(version))]), self.root / version, "", lambda *args: None)
            discovery.assert_called_once_with(major)
            probe.assert_called_once_with(java, major)
            self.assertEqual(result["java_source"], "local-auto")

    def test_incompatible_bundled_runtime_is_preserved_and_matching_local_java_is_used(self):
        for index, release in enumerate((
            'JAVA_VERSION="17.0.8"\nOS_ARCH="x86"\nOS_NAME="Windows"\n',
            'JAVA_VERSION="17.0.8"\nOS_ARCH="amd64"\nOS_NAME="Linux"\n',
            'JAVA_VERSION="21.0.8"\nOS_ARCH="amd64"\nOS_NAME="Windows"\n',
            'JAVA_VERSION="17.0.8"\nJAVA_VERSION="17.0.9"\nOS_ARCH="amd64"\nOS_NAME="Windows"\n',
        )):
            entries = [("server.jar", self.versioned_server("1.20.4")), ("jre/bin/java.exe", b"keep original"), ("jre/release", release)]
            java = r"D:\compatible-java17\bin\java.exe"
            with patch("native_server_install.discover_java", return_value=[java]), \
                 patch("native_server_install.inspect_java", return_value={"path": java, "major": 17, "bits": 64}):
                result = archive.install_archive(self.package(entries), self.root / str(index), "", lambda *args: None)
            self.assertEqual(result["java_source"], "local-auto")
            self.assertTrue(result["java_selection"]["rejected"])
            self.assertEqual((Path(result["path"]) / "jre/release").read_text(), release)

    def test_java8_inner_jre_uses_outer_jdk_release(self):
        entries = [("server.jar", self.versioned_server("1.12.2")),
                   ("jdk8/jre/bin/java.exe", b"never execute"),
                   ("jdk8/release", 'JAVA_VERSION="1.8.0_504"\nOS_ARCH="x86_64"\nOS_NAME="Windows"\n')]
        result = self.install(self.package(entries))
        self.assertEqual(result["java_relative_path"], "jdk8/jre/bin/java.exe")
        self.assertEqual(result["java_selection"]["candidates"][0]["release_path"], "jdk8/release")

    def test_unknown_minecraft_does_not_infer_version_from_bundled_java(self):
        entries = [("server.jar", server_jar()), *self.runtime_entries("runtime/jdk21", "21.0.8")]
        with patch("native_server_install.discover_java", side_effect=AssertionError("unknown MC must not auto choose")), \
             self.assertRaisesRegex(archive.ArchiveInstallError, "无法确定 Minecraft 版本"):
            archive.install_archive(self.package(entries), self.root / "unknown", "", lambda *args: None)

    def test_missing_manifest_runtime_uses_local_java_and_preserves_classpath(self):
        entries = [(name, data) for name, data in self.catserver_entries() if not name.startswith("runtime/")]
        java = r"D:\Java8\bin\java.exe"
        with patch("native_server_install.discover_java", return_value=[java]), \
             patch("native_server_install.inspect_java", return_value={"path": java, "major": 8, "bits": 64}):
            result = archive.install_archive(self.package(entries), self.root / "without-runtime", "", lambda *args: None)
        root = Path(result["path"])
        runtime = json.loads((root / "qizhang-startup.json").read_text())
        original = json.loads(dict(entries)[archive.LAUNCH_MANIFEST])
        self.assertEqual(runtime["classpath"], original["classpath"])
        from native_launch_settings import _jvm_file, IMPORT_JVM_FILE
        self.assertEqual(_jvm_file(root, IMPORT_JVM_FILE), original["jvm_args"])
        self.assertEqual(runtime["java_path"], java)
        self.assertEqual(result["java_source"], "local-auto")

    def test_manifest_preferred_compatible_runtime_keeps_original_choice(self):
        result = self.install(self.package(self.catserver_entries() + self.runtime_entries("newer-jdk8", "1.8.0_600")))
        self.assertEqual(result["java_relative_path"], "runtime/java8/bin/java.exe")

    def test_modern_argument_file_launcher_preserves_loader_args_and_relative_java(self):
        original = "-cp \"library original\"\noriginal.Main\n"
        entries = [("libraries/net/neoforged/neoforge/21.1.252/win_args.txt", original), *self.runtime_entries("java21", "21.0.8")]
        result = self.install(self.package(entries))
        root = Path(result["path"])
        launcher = (root / result["launch_script"]).read_text()
        config = json.loads((root / "qizhang-startup.json").read_text())
        self.assertEqual(config["entry"], entries[0][0])
        self.assertEqual(config["java_path"], "java21/bin/java.exe")
        self.assertEqual((root / entries[0][0]).read_text(), original)
        self.assertNotIn('set "QZ_JAVA=java.exe"', launcher)

    def test_runtime_scan_is_depth_bounded_and_does_not_select_backup_java(self):
        deepest_home = "/".join("d" + str(i) for i in range(archive.MAX_JAVA_DEPTH - 2))
        too_deep = deepest_home + "/deep"
        entries = [("server.jar", self.versioned_server("1.21.1")),
                   *self.runtime_entries(deepest_home, "21.0.8"),
                   *self.runtime_entries(too_deep, "21.0.99"),
                   *self.runtime_entries("backups/java21", "21.0.100")]
        result = self.install(self.package(entries))
        self.assertEqual(result["java_relative_path"], deepest_home + "/bin/java.exe")
        self.assertGreater(result["java_selection"]["skipped_deep_directories"], 0)

    def test_runtime_paths_release_size_and_links_are_checked_without_execution(self):
        home = self.root / "runtime"
        (home / "bin").mkdir(parents=True)
        (home / "bin/java.exe").write_bytes(b"fixture")
        release = home / "release"
        release.write_text('JAVA_VERSION="21.0.8"\nOS_ARCH="amd64"\nOS_NAME="Windows"\n')
        for relative in ("../outside/bin/java.exe", "C:/outside/bin/java.exe", "runtime/bin/not-java.exe"):
            with self.subTest(relative=relative), self.assertRaises(archive.ArchiveInstallError):
                archive.inspect_bundled_java(self.root, relative)
        original = Path.is_symlink
        with patch.object(Path, "is_symlink", lambda item: item == home or original(item)), self.assertRaisesRegex(archive.ArchiveInstallError, "链接"):
            archive.inspect_bundled_java(self.root, "runtime/bin/java.exe")
        release.write_bytes(b"x" * 65537)
        with self.assertRaisesRegex(archive.ArchiveInstallError, "超过允许大小"):
            archive.inspect_bundled_java(self.root, "runtime/bin/java.exe")

    def test_outer_sibling_runtime_is_copied_completely_inside_selected_server(self):
        for version, major, java_version in (("1.12.2", 8, "1.8.0_504"), ("1.21.1", 21, "21.0.8")):
            home = "Wrapper/jdk" + str(major)
            runtime = self.runtime_entries(home, java_version) + [
                (home + "/bin/server/jvm.dll", b"owned fixture vm"),
                (home + "/lib/" + ("rt.jar" if major == 8 else "modules"), b"owned fixture library"),
                (home + "/legal/NOTICE.txt", b"preserve complete runtime"),
            ]
            entries = [("Wrapper/Server/server.jar", self.versioned_server(version)),
                       ("Wrapper/Server/server.properties", "server-port=28888\n"), *runtime]
            archive_file = self.package(entries)
            original_bytes = archive_file.read_bytes()
            with patch("native_server_install.inspect_java", side_effect=AssertionError("outer bundled Java must remain static-only")), \
                 patch("subprocess.run", side_effect=AssertionError("no archive execution")):
                result = archive.install_archive(archive_file, self.root / str(major), "", lambda *args: None)
            self.assertEqual(archive_file.read_bytes(), original_bytes)
            target = Path(result["path"])
            selected = result["java_selection"]["candidates"][0]
            self.assertEqual(selected["copied_from_archive"], home + "/bin/java.exe")
            self.assertTrue(result["java_relative_path"].startswith("qizhang-bundled-java/java-" + str(major)))
            copied_home = (target / result["java_relative_path"]).parent.parent
            for name, data in runtime:
                self.assertEqual((copied_home / name[len(home) + 1:]).read_bytes(), data.encode() if isinstance(data, str) else data)
            self.assertEqual((target / "server.properties").read_text(), "server-port=28888\n")

    def test_incomplete_outer_runtime_is_not_copied_as_only_java_exe(self):
        entries = [("Server/server.jar", self.versioned_server("1.21.1")), *self.runtime_entries("jdk21", "21.0.8")]
        with patch("native_server_install.discover_java", return_value=[r"D:\local\java.exe"]):
            result = archive.install_archive(self.package(entries), self.root / "target", "", lambda *args: None)
        self.assertEqual(result["java_source"], "local-auto")
        self.assertFalse((Path(result["path"]) / "qizhang-bundled-java").exists())
        self.assertTrue(any("缺少运行库" in entry["reason"] for entry in result["java_selection"]["outer_archive_scan"]["rejected"]))

    def test_outer_runtime_copy_rejects_escape_and_links_before_copying(self):
        staging = self.root / "stage"
        server = staging / "Server"
        server.mkdir(parents=True)
        for name, data in self.runtime_entries("jdk21", "21.0.8") + [("jdk21/bin/server/jvm.dll", b"fixture"), ("jdk21/lib/modules", b"fixture")]:
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data.encode() if isinstance(data, str) else data)
        with self.assertRaises(archive.ArchiveInstallError):
            archive.copy_outer_bundled_java(staging, server, {"path": "../external/bin/java.exe"})
        original = Path.is_symlink
        library = staging / "jdk21/lib/modules"
        with patch.object(Path, "is_symlink", lambda path: path == library or original(path)), self.assertRaisesRegex(archive.ArchiveInstallError, "链接"):
            archive.copy_outer_bundled_java(staging, server, {"path": "jdk21/bin/java.exe"})
        self.assertFalse((server / "qizhang-bundled-java").exists())

    @unittest.skipUnless(os.name == "nt", "Windows generated launchers")
    def test_generated_java8_and21_launchers_resolve_runtime_after_folder_move(self):
        compiler = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        if not compiler.is_file():
            self.skipTest(".NET compiler unavailable for owned argv fixture")
        source = self.root / "JavaFixture.cs"
        source.write_text('using System; using System.IO; class JavaFixture { static int Main(string[] args) { File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"fixture-args.txt"),string.Join("\\n",args)); return 0; } }', encoding="utf-8")
        executable = self.root / "JavaFixture.exe"
        compile_result = subprocess.run([str(compiler), "/nologo", "/target:exe", "/out:" + str(executable), str(source)], capture_output=True, creationflags=0x08000000, timeout=30)
        self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
        for minecraft, major, java_version in (("1.12.2", 8, "1.8.0_504"), ("1.21.1", 21, "21.0.8")):
            entries = [("server.jar", self.versioned_server(minecraft)), *self.runtime_entries("运行时 Java/jre", java_version, executable=executable.read_bytes())]
            with patch("native_server_install.inspect_java", side_effect=AssertionError("must not run an imported fixture during import")), \
                 patch("subprocess.run", side_effect=AssertionError("import cannot execute")):
                definition = archive.install_archive(self.package(entries), self.root / ("original-" + str(major)), "", lambda *args: None)
            initial = Path(definition["path"])
            relocated = self.root / ("移动后 空格 " + str(major))
            initial.rename(relocated)
            result = subprocess.run([os.environ.get("ComSpec", "cmd.exe"), "/d", "/c", str(relocated / definition["launch_script"])],
                                    cwd=self.root, stdin=subprocess.DEVNULL, capture_output=True, creationflags=0x08000000, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            args = (relocated / "运行时 Java/jre/bin/fixture-args.txt").read_text(encoding="utf-8-sig")
            self.assertIn("-Dqizhang.panel.server_id=" + definition["id"], args)
            self.assertIn("-jar\nserver.jar\nnogui", args)

    def test_wrapped_vanilla_detected_bound_and_original_settings_preserved(self):
        path = self.package([("MyServer/server.jar", server_jar()), ("MyServer/server.properties", "server-port=28888\n"),
                             ("MyServer/user_jvm_args.txt", "-Xms1G\n-Xmx3G\n"), ("MyServer/eula.txt", "eula=true\n"),
                             ("MyServer/start.bat", "@echo off\njava @user_jvm_args.txt -jar server.jar nogui\n")])
        definition = self.install(path)
        root = Path(definition["path"])
        self.assertEqual(definition["platform"], "vanilla")
        self.assertIn("server-port=28888", (root / "server.properties").read_text())
        self.assertEqual((root / "user_jvm_args.txt").read_text(), "-Xms1G\n-Xmx3G\n")
        self.assertEqual((root / "eula.txt").read_text(), "eula=true\n")
        self.assertTrue((root / "qizhang-java-path.txt").is_file())
        self.assertFalse((root / "should-not-exist.txt").exists())
        self.assertEqual(json.loads((root / "qizhang-startup.json").read_text())["entry"], "server.jar")

    def test_neoforge_and_fabric_launchers_are_detected(self):
        for platform, entries in (("neoforge", [("run.bat", "@echo off\njava @libraries/net/neoforged/neoforge/21.1.252/win_args.txt %*"), ("libraries/net/neoforged/neoforge/21.1.252/win_args.txt", "args")]),
                                  ("fabric", [("fabric-server-launch.jar", server_jar("net.fabricmc.installer.ServerLauncher"))])):
            with self.subTest(platform=platform):
                path = self.package(entries)
                definition = archive.install_archive(path, self.root / platform, "java", lambda percent, text: None)
                self.assertEqual(definition["platform"], platform)
                self.assertEqual((Path(definition["path"]) / "eula.txt").read_text(), "eula=false\n")

    def test_catserver_manifest_preserves_classpath_and_uses_bundled_java_without_executing(self):
        entries = self.catserver_entries() + [("start.bat", "bad command"), ("plugins/server.jar", server_jar()),
                    ("mods/client.jar", server_jar("net.minecraft.client.main.Main")),
                    ("libraries/minecraft_server.1.12.2.jar", server_jar("net.minecraft.server.MinecraftServer"))]
        with patch("native_server_install.validate_java21", side_effect=AssertionError("must not validate Java21")), \
             patch("subprocess.run", side_effect=AssertionError("must not execute archive code")):
            definition = self.install(self.package(entries))
        root = Path(definition["path"])
        meta = json.loads((root / "qizhang-import.json").read_text(encoding="utf-8"))
        runtime = json.loads((root / "qizhang-startup.json").read_text())
        self.assertEqual(definition["platform"], "catserver")
        self.assertEqual(definition["minecraft_version"], "1.12.2")
        self.assertEqual(meta["java_path"], str(root / "runtime/java8/bin/java.exe"))
        self.assertEqual(meta["java_validation"], "bundled-release-static-only")
        self.assertEqual(meta["command_channel"], "serverfoundation-file-v1")
        self.assertEqual(runtime["classpath"][-1], "CatServer.jar")
        self.assertEqual(runtime["classpath"][0], "libraries/log4j-api-2.25.3.jar")
        from native_launch_settings import _jvm_file, IMPORT_JVM_FILE
        self.assertIn("-Dcatserver.skipCheckLibraries=true", _jvm_file(root, IMPORT_JVM_FILE))
        self.assertEqual(runtime["server_id"], definition["id"])
        self.assertFalse((root / "user_jvm_args.txt").exists())
        launcher = (root / "qizhang-managed-start.ps1").read_text(encoding="utf-8-sig")
        self.assertNotIn("@user_jvm_args", launcher)
        self.assertIn("Get-Content", launcher)
        self.assertIn("-Dqizhang.panel.server_id=", launcher)

    def test_catserver_without_manifest_reports_specific_preservation_requirement(self):
        with self.assertRaisesRegex(archive.ArchiveInstallError, "CatServer.*classpath"):
            self.install(self.package([("CatServer.jar", server_jar(archive.CATSERVER_MAIN))]))

    def test_legacy_forge_and_companion_vanilla_select_java8_with_compatible_launcher(self):
        for number, main in enumerate(sorted(archive.LEGACY_FORGE_MAINS)):
            entries = [("forge-1.12.2-14.23.5.2860.jar", server_jar(main)),
                       ("minecraft_server.1.12.2.jar", server_jar("net.minecraft.server.MinecraftServer")),
                       ("start.bat", "java -Xmx2G -jar forge-1.12.2-14.23.5.2860.jar nogui")]
            with patch("native_server_install.inspect_java", return_value={"path": r"D:\Java\jdk8\bin\java.exe", "major": 8}) as probe:
                definition = archive.install_archive(self.package(entries), self.root / ("legacy-" + str(number)), "java", lambda *args: None)
            probe.assert_called_once_with("java", 8)
            self.assertEqual(definition["minecraft_version"], "1.12.2")
            self.assertEqual(definition["java_requirement"]["major"], 8)
            root = Path(definition["path"])
            self.assertIn("qizhang-managed-start.ps1", (root / definition["launch_script"]).read_text())
            launcher = (root / "qizhang-managed-start.ps1").read_text(encoding="utf-8-sig")
            self.assertNotIn("@user_jvm_args.txt", launcher)
            self.assertIn("qizhang-java-path.txt", launcher)
            self.assertIn("'-jar', $cfg.entry", launcher)
            self.assertEqual((root / "start.bat").read_text(), entries[-1][1])

    def test_version_json_selects_java16_17_or21_without_running_a_jar(self):
        for version, major in (("1.17.1", 16), ("1.18.2", 17), ("1.20.4", 17), ("1.20.5", 21), ("1.21.1", 21)):
            jar = jar_entries({"META-INF/MANIFEST.MF": "Main-Class: net.minecraft.bundler.Main\n", "version.json": json.dumps({"id": version})})
            with patch("native_server_install.inspect_java", return_value={"path": r"D:\Java\java.exe", "major": major}) as probe:
                definition = archive.install_archive(self.package([("server.jar", jar)]), self.root / version, "java", lambda *args: None)
            probe.assert_called_once_with("java", major)
            self.assertEqual(definition["minecraft_version"], version)
            self.assertEqual(definition["java_major"], major)

    def test_known_version_wrong_java_major_rejected_and_stage_removed(self):
        java = self.root / "java.exe"
        java.write_bytes(b"external test executable")
        path = self.package([("forge-1.12.2-14.23.5.2860.jar", server_jar("net.minecraftforge.fml.relauncher.ServerLaunchWrapper"))])
        with patch("native_server_install.inspect_java", side_effect=real_inspect_java), \
                patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, b'openjdk version "21.0.8"\n64-Bit')):
            with self.assertRaisesRegex(ServerInstallError, "需要 64 位 Java 8.*Java 21"):
                archive.install_archive(path, self.root / "installed", str(java), lambda *args: None)
        self.assertFalse((self.root / "installed").exists())
        self.assertFalse(list(self.root.glob(".qizhang-server-import-*")))

    def test_unknown_version_asks_for_java_and_does_not_assume21(self):
        path = self.package([("server.jar", server_jar())])
        with patch("native_server_install.discover_java", side_effect=AssertionError("must not select a Java for unknown MC")):
            with self.assertRaisesRegex(archive.ArchiveInstallError, "无法确定 Minecraft 版本"):
                archive.install_archive(path, self.root / "unknown", "", lambda *args: None)
        with patch("native_server_install.inspect_java", return_value={"path": r"D:\Java\jdk8\bin\java.exe", "major": 8}) as probe:
            definition = self.install(path)
        probe.assert_called_once_with("java", None)
        self.assertEqual(definition["minecraft_version"], "")
        self.assertFalse(definition["java_requirement"]["known"])
        self.assertEqual(definition["java_major"], 8)

    def test_different_vanilla_release_requires_selection_instead_of_poisoning_loader_version(self):
        entries = [("forge-1.12.2-14.23.5.2860.jar", server_jar("net.minecraftforge.fml.relauncher.ServerLaunchWrapper")),
                   ("minecraft_server.1.16.5.jar", server_jar("net.minecraft.server.Main"))]
        with self.assertRaises(archive.ArchiveSelectionRequired) as prompt:
            self.install(self.package(entries))
        self.assertEqual({row["minecraft_version"] for row in prompt.exception.choices}, {"1.12.2", "1.16.5"})

    def test_forge_version_library_directory_and_fabric_dependency_metadata(self):
        cases = [("forge", [("forge.jar", server_jar("net.minecraftforge.fml.relauncher.ServerLaunchWrapper")),
                             ("libraries/net/minecraftforge/forge/1.12.2-14.23.5.2860/forge.jar", b"fixture")], "1.12.2", 8),
                 ("fabric", [("fabric-server-launch.jar", server_jar("net.fabricmc.installer.ServerLauncher")),
                              ("minecraft_server.1.20.4.jar", server_jar())], "1.20.4", 17)]
        for platform, entries, version, major in cases:
            with patch("native_server_install.inspect_java", return_value={"path": r"D:\Java\java.exe", "major": major}) as probe:
                definition = archive.install_archive(self.package(entries), self.root / platform, "java", lambda *args: None)
            probe.assert_called_once_with("java", major)
            self.assertEqual(definition["minecraft_version"], version)

    def test_file_bridge_is_never_assumed_from_plugin_name(self):
        entries = [(name, content) for name, content in self.catserver_entries() if not name.startswith("plugins/")]
        entries.append(("plugins/ServerFoundation-0.2.0.jar", jar_entries({"plugin.yml": "version: 0.2.0\n"})))
        with self.assertRaisesRegex(archive.ArchiveInstallError, "未包含 PanelCommandBridge"):
            self.install(self.package(entries))

    def legacy_catserver_entries(self):
        core = "CatServer-4168d848-universal.jar"
        classpath = ["libraries/log4j-api-2.25.3.jar", "libraries/log4j-core-2.25.3.jar",
                     "libraries/lwjgl_util-2.9.4-nightly-20150209.jar", core]
        source = 'public const string ClassPath = "' + ";".join(classpath) + '";\n' + r'new ProcessStartInfo(java, "-Xms1G -Xmx" + memory + " -XX:+UseG1GC -Dfile.encoding=UTF-8 -Dfml.readTimeout=180 -Dcatserver.skipCheckLibraries=true -Dcatserver.spark.enable=false -cp \"" + ClassPath + "\" catserver.server.CatServerLaunch nogui")'
        return [(core, jar_entries({"META-INF/MANIFEST.MF": "Main-Class: catserver.server.CatServerLaunch\r\r\nImplementation-Version: git-CatServer-1.12.2-4168d848\r\r\nClass-Path: libraries/log4j-\r\r\n core.jar\r\r\n", "catserver/server/CatServerLaunch.class": b"fixture"})),
                ("maintenance-sources/server-launcher/LauncherCore.cs", source),
                ("runtime/java8/bin/java.exe", b"must not execute"),
                ("runtime/java8/release", 'JAVA_VERSION="1.8.0_504"\nOS_ARCH="amd64"\nOS_NAME="Windows"\n'),
                ("libraries/minecraft_server.1.12.2.jar", server_jar("net.minecraft.server.MinecraftServer")),
                ("plugins/ServerFoundation-0.2.0.jar", jar_entries({"plugin.yml": "version: 0.2.0\n"})),
                *[(name, b"keep-original-library") for name in classpath[:-1]]]

    def test_original_catserver_profile_imports_without_new_manifest_or_executing_java(self):
        entries = self.legacy_catserver_entries()
        with patch("subprocess.run", side_effect=AssertionError("must not execute archive code")), \
                patch("native_server_install.inspect_java", side_effect=AssertionError("bundled java is static-only")):
            definition = self.install(self.package(entries))
        root = Path(definition["path"])
        for name, content in entries:
            self.assertEqual((root / name).read_bytes(), content.encode() if isinstance(content, str) else content)
        runtime = json.loads((root / "qizhang-startup.json").read_text(encoding="utf-8"))
        self.assertEqual(json.loads((root / "qizhang-import.json").read_text(encoding="utf-8"))["command_channel"], "default")
        self.assertEqual(runtime["minecraft_version"], "1.12.2")
        self.assertEqual(runtime["java_major"], 8)
        from native_launch_settings import _jvm_file, IMPORT_JVM_FILE
        self.assertEqual(len(_jvm_file(root, IMPORT_JVM_FILE)), 7)
        self.assertEqual(len(runtime["classpath"]), 4)
        self.assertEqual(archive.jar_manifest(root / runtime["entry"])["Class-Path"], "libraries/log4j-core.jar")

    def test_unrecognized_catserver_profile_keeps_specific_error_and_original_files(self):
        entries = [(name, data.replace("-Dfml.readTimeout=180", "-Dfml.readTimeout=200") if name.endswith("LauncherCore.cs") else data)
                   for name, data in self.legacy_catserver_entries()]
        with self.assertRaisesRegex(archive.ArchiveInstallError, "已识别 CatServer.*启动格式"):
            self.install(self.package(entries))

    def test_launch_manifest_does_not_make_unknown_mod_into_server(self):
        entries = self.catserver_entries()
        entries[0] = ("CatServer.jar", server_jar("com.example.client.ModLauncher"))
        with self.assertRaisesRegex(archive.ArchiveInstallError, "唯一"):
            self.install(self.package(entries))

    def test_verified_manifest_disambiguates_but_unresolved_multiple_cores_require_selection(self):
        result = self.install(self.package(self.catserver_entries() + [("spigot.jar", server_jar("org.bukkit.craftbukkit.Main"))]))
        self.assertEqual(result["platform"], "catserver")
        self.assertTrue((Path(result["path"]) / "spigot.jar").is_file())
        cases = [[("libraries/net/neoforged/neoforge/21.1.252/win_args.txt", "args"), ("spigot.jar", server_jar("org.bukkit.craftbukkit.Main"))],
                 [("forge-one.jar", server_jar("net.minecraftforge.fml.relauncher.ServerLaunchWrapper")),
                  ("forge-two.jar", server_jar("net.minecraftforge.fml.relauncher.ServerLaunchWrapper"))]]
        for index, entries in enumerate(cases):
            with self.subTest(entries=[entry[0] for entry in entries]), self.assertRaisesRegex(archive.ArchiveInstallError, "多个"):
                archive.install_archive(self.package(entries), self.root / ("choice-" + str(index)), "java", lambda *args: None)

    def test_invalid_startup_contract_is_rejected_and_staging_cleaned(self):
        changes = [{"core_jar": "other.jar"}, {"main_class": "example.Other"}, {"java_path": "../java.exe"},
                   {"classpath": ["CatServer.jar", "libraries/missing.jar"]}, {"java_major": 21},
                   {"jvm_args": ["-jar", "evil.jar"]}, {"command_channel": "unknown"}]
        for update in changes:
            with self.subTest(update=update), self.assertRaises(archive.ArchiveInstallError):
                self.install(self.package(self.catserver_entries(**update)))
            self.assertFalse((self.root / "installed").exists())
            self.assertFalse(list(self.root.glob(".qizhang-server-import-*")))

    def test_bundled_runtime_must_declare_windows_64_bit_java8(self):
        for release in ('JAVA_VERSION="1.8.0_504"\nOS_ARCH="x86"\nOS_NAME="Windows"\n',
                        'JAVA_VERSION="21.0.1"\nOS_ARCH="amd64"\nOS_NAME="Windows"\n',
                        'JAVA_VERSION="1.8.0_504"\nOS_ARCH="amd64"\nOS_NAME="Linux"\n'):
            entries = [(name, release if name.endswith("/release") else data) for name, data in self.catserver_entries()]
            with self.subTest(release=release), self.assertRaises(archive.ArchiveInstallError):
                self.install(self.package(entries))

    def test_traversal_absolute_case_collisions_and_symlink_rejected(self):
        cases = [[("../outside.txt", "bad")], [("C:/outside.txt", "bad")], [("mods/A.jar", "a"), ("mods/a.jar", "b")]]
        symbolic = zipfile.ZipInfo("link")
        symbolic.create_system = 3
        symbolic.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases.append([(symbolic, "../outside.txt")])
        for entries in cases:
            with self.subTest(entries=str(entries)):
                with self.assertRaises(archive.ArchiveInstallError):
                    self.install(self.package(entries))
                self.assertFalse((self.root / "installed").exists())
                self.assertFalse((self.root / "outside.txt").exists())
                self.assertFalse(list(self.root.glob(".qizhang-server-import-*")))

    def test_client_pack_and_ambiguous_multiple_servers_rejected(self):
        cases = [[("mods/a.jar", "clientmod"), ("manifest.json", "{}")],
                 [("one/server.jar", server_jar()), ("two/server.jar", server_jar())]]
        for entries in cases:
            with self.subTest(entries=str([x[0] for x in entries])), self.assertRaises(archive.ArchiveInstallError):
                self.install(self.package(entries))

    def test_existing_server_directory_is_never_overwritten(self):
        target = self.root / "installed"
        target.mkdir()
        original = target / "world.txt"
        original.write_text("original world", encoding="utf-8")
        with self.assertRaises(archive.ArchiveInstallError):
            self.install(self.package([("server.jar", server_jar())]))
        self.assertEqual(original.read_text(), "original world")


if __name__ == "__main__":
    unittest.main(verbosity=2)
