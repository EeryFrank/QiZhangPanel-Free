# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/backend'))
from native_java_bridge import rewrite_argument


class BridgeArguments(unittest.TestCase):
    def test_native_and_forward_paths_and_classpath(self):
        root, alias = r'E:\中文 root', r'E:\alias'
        cases = {
            root: alias,
            '-Dpath='+root+r'\file': '-Dpath='+alias+r'\file',
            '-Dpath=E:/中文 root/file': '-Dpath='+alias+'/file',
            root+r'\a.jar;E:/中文 root/b.jar': alias+r'\a.jar;'+alias+'/b.jar',
            '"E:/中文 root/file"': '"'+alias+'/file"',
        }
        for before, after in cases.items():
            self.assertEqual(rewrite_argument(before, root, alias), after)

    def test_url_unrelated_suffix_and_other_separators_are_untouched(self):
        root, alias = r'E:\中文 root', r'E:\alias'
        for value in ('-Dendpoint=https://example.invalid/E:/中文 root-backup/',
                      '-Dpath=E:/中文 root-backup/file',
                      '-Dtext=xE:/中文 root/file',
                      '-Dendpoint=https://example.invalid/E:/中文 root/file'):
            self.assertEqual(rewrite_argument(value, root, alias), value)


if __name__ == '__main__':
    unittest.main()
