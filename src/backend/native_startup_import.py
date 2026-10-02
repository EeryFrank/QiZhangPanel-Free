# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Bounded, static startup analysis. No script, Java or command is executed.

This is a deliberately small language, not a CMD/PowerShell/shell interpreter.
Unresolved control flow and side effects are explicit failures, not defaults.
"""
from pathlib import Path
import hashlib
import re
import shlex

MAX_BYTES = 128 * 1024
MAX_SCRIPTS = 32
MAX_ARGUMENTS = 256
GENERATED = {"qizhang-managed-start.bat", "qizhang-managed-start.ps1",
             "qizhang-imported-start.bat", "qizhang-imported-start.ps1"}


class StartupParseError(ValueError):
    pass


def _inside(root, value, *, file=True):
    root = root.resolve()
    value = str(value).replace("\\", "/")
    if any(c in value for c in "\0\r\n") or not value:
        raise StartupParseError("启动文件路径无效。")
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise StartupParseError("启动配置引用了服务器目录以外的文件。")
    original = root / value
    for part in (original, *original.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise StartupParseError("启动配置不能引用链接或目录联接。")
        if part == root:
            break
    if file and not path.is_file():
        raise StartupParseError("启动配置引用的包内文件不存在：" + value)
    return path


def _read(root, source):
    path = _inside(root, source)
    if path.stat().st_size > MAX_BYTES:
        raise StartupParseError("启动文件超过 128 KB，无法安全自动适配。")
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
        encoding = "utf-8"
    except UnicodeDecodeError:
        try:
            text, encoding = data.decode("gb18030"), "gb18030"
        except UnicodeDecodeError:
            raise StartupParseError("启动文件不是可读取的 UTF-8 或 GBK 文本。") from None
    if "\0" in text:
        raise StartupParseError("启动文件包含二进制或不支持的文本编码。")
    suffix = path.suffix.lower().lstrip(".")
    return text, {"path": path.relative_to(root.resolve()).as_posix(),
                  "sha256": hashlib.sha256(data).hexdigest(), "format": suffix,
                  "encoding": encoding, "can_run_original": suffix in {"bat", "cmd"}}


def _logical_lines(text, continuation):
    pending = ""
    for number, line in enumerate(text.splitlines(), 1):
        if number > 4096:
            raise StartupParseError("启动脚本超过允许的行数。")
        joined = pending + line
        if joined.endswith(continuation):
            if joined.endswith(continuation * 2):
                raise StartupParseError("启动脚本包含无法确认的转义续行。")
            pending = joined[:-1]
            continue
        pending = ""
        yield number, joined.strip()
    if pending:
        raise StartupParseError("启动脚本的续行没有结束。")


def _cmd_tokens(text):
    """Common quoted CMD words only; ambiguous native quote escaping is refused."""
    values, word, quoted, active = [], [], False, False
    for index, char in enumerate(text):
        if char == '"':
            if index and text[index - 1] == '"':
                raise StartupParseError("启动参数含有连续双引号，无法确认原生参数边界。")
            if index and text[index - 1] == "\\":
                raise StartupParseError("启动参数含有复杂的反斜线/引号转义，请手动核对。")
            quoted, active = not quoted, True
        elif char in "&|<>()" and not quoted:
            raise StartupParseError("启动脚本含有命令链、重定向或控制块，不能自动适配。")
        elif char in "^!":
            raise StartupParseError("启动脚本含有动态展开或不支持的转义。")
        elif char.isspace() and not quoted:
            if active:
                values.append("".join(word))
                word, active = [], False
        else:
            word.append(char)
            active = True
    if quoted:
        raise StartupParseError("启动参数引号未闭合。")
    if active:
        values.append("".join(word))
    return values


def _expand_cmd(text, variables, root):
    text = re.sub(r"%~dp0", lambda _: str(root.resolve()) + "/", text, flags=re.I)
    def replace(match):
        name = match[1].upper()
        value = variables.get(name)
        if value is None:
            raise StartupParseError("Java 启动行引用了无法静态确定的变量：%" + match[1] + "%")
        return value
    # CMD expands variables once per standalone line. Do not recursively
    # reinterpret percent signs introduced by a stored value.
    text = re.sub(r"%([A-Za-z_][A-Za-z0-9_]*)%", replace, text)
    if "%" in text:
        raise StartupParseError("Java 启动行含有未解析的参数、环境变量或动态替换。")
    return text


def _batch_calls(root, text):
    variables, display_variables, calls, notes = {}, {}, [], []
    def display_time(text):
        return re.sub(r"(?i)%(time|date)(?::~-?\d+(?:,-?\d+)?)?%",
                      lambda match: match[0] if match[1].upper() in variables else "0", text)
    for number, line in _logical_lines(text, "^"):
        line = line.lstrip("@").strip()
        if not line or re.match(r"(?i)^(?:rem(?:\s|$)|::)", line):
            continue
        if line.startswith(":") and re.fullmatch(r":[A-Za-z0-9_.-]+", line):
            continue  # Labels alone have no effect; every goto/call is refused below.
        if re.fullmatch(r"(?i)(?:chcp\s+\d+|pause)\s*>\s*nul", line):
            continue  # Exact console-only suppression; no file redirection.
        # Parse before ignoring presentation commands, so echo x & other-command
        # cannot conceal an additional executable step.
        words = _cmd_tokens(line)
        if not words:
            continue
        command = words[0].lower()
        if command == "set":
            assignment = line[3:].strip()
            if assignment.startswith('"') and assignment.endswith('"'):
                assignment = assignment[1:-1]
            match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", assignment)
            if not match:
                raise StartupParseError("仅支持常量 set 赋值，不支持交互输入或计算。")
            name, value = match[1].upper(), match[2]
            if name in {"JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "PATH"}:
                raise StartupParseError("脚本修改了 Java 注入环境或 PATH，不能只靠启动参数完整适配。")
            try:
                variables[name] = _expand_cmd(value, variables, root)
                display_variables[name] = variables[name]
            except StartupParseError:
                variables[name] = None
                # The bundled menu uses TIME substrings purely for its banner.
                # They remain unknown for Java argv. Only this bounded display
                # idiom gets a harmless placeholder; arbitrary environment
                # substitutions cannot conceal expanded CMD operators.
                preview = display_time(value)
                try:
                    display_variables[name] = _expand_cmd(preview, display_variables, root)
                except StartupParseError:
                    display_variables[name] = None
                notes.append("展示变量 " + name + " 无法静态展开；若用于 Java 启动将拒绝适配。")
            continue
        if command in {"setlocal", "endlocal"}:
            if command == "setlocal" and any(word.lower() == "enabledelayedexpansion" for word in words[1:]):
                raise StartupParseError("脚本启用了延迟变量展开，不能自动适配。")
            if command == "endlocal":
                variables.clear()  # Original outer environment is intentionally unknown.
                display_variables.clear()
            continue
        if (command in {"echo", "title", "color", "cls", "pause"} or command.startswith("echo.")
                or re.fullmatch(r"(?i)chcp\s+\d+", line)):
            _cmd_tokens(_expand_cmd(display_time(line), display_variables, root))
            continue
        if re.fullmatch(r"(?i)exit(?:\s+/b)?(?:\s+(?:\d+|%errorlevel%))?", line):
            # An unconditional exit before Java means the later line is unreachable.
            if not calls:
                raise StartupParseError("脚本在 Java 启动之前退出，无法确认启动目标。")
            break
        if command == "cd":
            expanded = _cmd_tokens(_expand_cmd(line, variables, root))
            path = expanded[2:] if len(expanded) > 1 and expanded[1].lower() == "/d" else expanded[1:]
            if len(path) != 1 or _inside(root, path[0], file=False) != root.resolve():
                raise StartupParseError("脚本更改到其他工作目录，不能自动改变其相对路径语义。")
            continue
        if re.match(r"(?i)^(?:if|for|goto|call|start|choice|powershell|pwsh|cmd|curl|wget|bitsadmin)(?:\s|$)", line):
            raise StartupParseError("脚本含有分支、子脚本或额外命令，请选择实际启动脚本或保留原启动方式。")
        forwarding = bool(re.search(r"(?:^|\s)%\*\s*$", line))
        if forwarding:
            line = re.sub(r"(?:^|\s)%\*\s*$", "", line)
            notes.append("原脚本末尾 %* 接收外部参数；面板没有额外传入参数。")
        expanded = _cmd_tokens(_expand_cmd(line, variables, root))
        if not expanded or expanded[0].replace("\\", "/").rsplit("/", 1)[-1].lower() not in {"java", "java.exe"}:
            raise StartupParseError("第 " + str(number) + " 行包含无法确认的执行步骤，未丢弃该步骤。")
        if expanded[1:] in (["-version"], ["--version"]):
            continue  # A standalone informational probe does not alter Java argv.
        calls.append(expanded)
    return calls, notes


def _literal_shell_calls(root, text, dialect):
    """PS1/SH intentionally support literal commands only, not their evaluators."""
    calls, notes = [], []
    for number, line in _logical_lines(text, "`" if dialect == "ps1" else "\\"):
        if not line or line.startswith("#"):
            continue
        quote, escaped = "", False
        for index, char in enumerate(line):
            if escaped:
                escaped = False
                continue
            if dialect == "sh" and char == "\\" and quote != "'":
                escaped = True
            elif char in "\"'":
                if not quote:
                    quote = char
                elif quote == char:
                    quote = ""
            elif char == "#" and not quote and (index == 0 or line[index - 1].isspace()):
                line = line[:index].rstrip()
                break
        if dialect == "ps1" and re.fullmatch(r"(?i)Set-Location\s+(?:-LiteralPath\s+)?\$PSScriptRoot", line):
            continue
        if dialect == "ps1" and line.lower() in {"exit $lastexitcode", "$erroractionpreference = 'stop'", '$erroractionpreference = "stop"'}:
            if line.lower().startswith("exit"):
                if not calls:
                    raise StartupParseError("脚本在 Java 启动之前退出。")
                break
            continue
        if dialect == "sh" and line in {"set -e", "set -eu", "set -euo pipefail"}:
            continue
        if dialect == "sh" and line in {'cd "$(dirname "$0")"', 'cd -- "$(dirname -- "$0")"'}:
            continue  # Exact root-location idiom only; no shell expansion occurs.
        if dialect == "ps1" and line.startswith("& "):
            line = line[2:].lstrip()
        if dialect == "sh" and line.startswith("exec "):
            line = line[5:].lstrip()
        if dialect == "sh":
            # The official Forge/NeoForge script forwards its caller's argv in
            # one final, double-quoted token. The panel supplies no script argv.
            # Require a complete preceding word boundary; shlex rejects an
            # unmatched quote or an escaped boundary before the placeholder.
            forwarding = re.search(r'(?:^|\s)"\$@"\s*$', line)
            if forwarding:
                prefix = line[:forwarding.start()].rstrip()
                try:
                    shlex.split(prefix, posix=True)
                except ValueError:
                    raise StartupParseError("Shell 外部参数占位不是独立的末尾参数。") from None
                if not prefix:
                    raise StartupParseError("Shell 外部参数占位前缺少 Java 启动命令。")
                line = prefix
                notes.append('原脚本末尾 "$@" 接收外部参数；面板没有额外传入参数。')
        if dialect == "sh" and any(char in line for char in "*?[]"):
            raise StartupParseError("Shell 通配符展开无法安全继承，请改为明确参数或保留原启动方式。")
        if any(char in line for char in "$`;&|<>()"):
            raise StartupParseError("第 " + str(number) + " 行含动态表达式、命令链或变量；此格式仅支持字面 Java 启动行。")
        if dialect == "ps1":
            # PS single quotes are literal; reject escapes rather than applying
            # the different POSIX backslash semantics to Windows paths.
            if '"' in line or "''" in line:
                raise StartupParseError("PowerShell 自动适配仅支持普通字面词或单引号参数。")
            tokens = re.findall(r"(?:[^\s']+|'[^']*')+", line)
            if line.count("'") % 2:
                raise StartupParseError("PowerShell 参数引号未闭合。")
            if any(word.startswith("@") for word in tokens):
                raise StartupParseError("PowerShell 未加引号的 @变量是动态参数展开，不能当 Java 参数文件读取。")
            tokens = [word.replace("'", "") for word in tokens]
        else:
            try:
                tokens = shlex.split(line, posix=True)
            except ValueError:
                raise StartupParseError("Shell 参数引号未闭合。") from None
        if not tokens:
            continue
        if tokens[0].replace("\\", "/").rsplit("/", 1)[-1].lower() not in {"java", "java.exe"}:
            raise StartupParseError("第 " + str(number) + " 行不是可确认的字面 Java 启动；原脚本未执行。")
        calls.append(tokens)
    return calls, notes


def _jvm_argument_file(root, token):
    path = _inside(root, token[1:])
    text, source = _read(root, path)
    words = []
    # Ordinary JVM option files contain whitespace, # comments and quoted
    # values. Backslash escape syntax is refused rather than reinterpreted.
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "\\" in line or "'" in line:
            raise StartupParseError("JVM 参数文件包含复杂转义，请在启动设置中明确填写。")
        quoted = False
        cutoff = len(line)
        for index, char in enumerate(line):
            if char == '"':
                quoted = not quoted
            elif char == "#" and not quoted:
                cutoff = index
                break
        words.extend(_cmd_tokens(line[:cutoff]))
    if any(word.startswith("@") for word in words):
        raise StartupParseError("JVM 参数文件不能继续引用其他参数文件。")
    return words, {"path": source["path"], "sha256": source["sha256"]}


def _check_arguments(jvm, game):
    if len(jvm) + len(game) > MAX_ARGUMENTS or any(not word or len(word) > 4096 or any(ord(c) < 32 for c in word) for word in jvm + game):
        raise StartupParseError("启动参数数量、长度或字符超出允许范围。")
    allowed = ("-X", "-XX:", "-D", "-javaagent:", "-agentlib:", "-agentpath:", "-verbose",
               "--add-opens=", "--add-exports=", "--add-modules=", "--enable-native-access=")
    for word in jvm:
        if (not word.startswith(allowed) and word not in {"-ea", "-da", "-esa", "-dsa"}) or word.startswith("-Dqizhang.panel.server_id"):
            raise StartupParseError("无法确认 JVM 参数，或参数覆盖面板实例标识：" + word[:80])


def _profile(root, call, cores, source, notes):
    from native_server_archive import jar_manifest, _validate_classpath_main
    java, tokens = call[0], call[1:]
    jvm, game, argument_files, selected, classpath, main, kind = [], [], [], None, [], "", ""
    index = 0
    while index < len(tokens):
        word = tokens[index]
        if word == "-jar":
            if index + 1 >= len(tokens):
                raise StartupParseError("-jar 后缺少服务端文件。")
            entry = _inside(root, tokens[index + 1]).relative_to(root.resolve()).as_posix()
            selected = [core for core in cores if core[1] == "jar" and core[2].casefold() == entry.casefold()]
            kind, game = "jar", tokens[index + 2:]
            break
        if word in {"-cp", "-classpath", "--class-path"}:
            if index + 2 >= len(tokens):
                raise StartupParseError("Classpath 或启动主类缺失。")
            if "*" in tokens[index + 1] or tokens[index + 1].startswith(";") or tokens[index + 1].endswith(";"):
                raise StartupParseError("Classpath 通配符或空路径不能可靠确定加载顺序。")
            classpath = [_inside(root, value).relative_to(root.resolve()).as_posix() for value in tokens[index + 1].split(";")]
            main = tokens[index + 2]
            if not re.fullmatch(r"[A-Za-z_$][\w.$]*", main) or any(Path(part).suffix.lower() != ".jar" for part in classpath):
                raise StartupParseError("Classpath 必须明确列出包内 JAR 和合法主类。")
            selected = [core for core in cores if core[1] == "jar" and core[2].casefold() in {part.casefold() for part in classpath}
                        and jar_manifest(root / core[2]).get("Main-Class", "").strip() == main]
            kind, game = "classpath", tokens[index + 3:]
            if len(selected) == 1:
                _validate_classpath_main(root, classpath, selected[0][2], main)
            break
        if word.startswith("@"):
            entry = _inside(root, word[1:]).relative_to(root.resolve()).as_posix()
            matches = [core for core in cores if core[1] == "args" and core[2].casefold() == entry.casefold()]
            if matches:
                selected, kind, game = matches, "args", tokens[index + 1:]
                break
            values, descriptor = _jvm_argument_file(root, word)
            jvm.extend(values)
            argument_files.append(descriptor)
        else:
            jvm.append(word)
        index += 1
    if selected is None or len(selected) != 1:
        raise StartupParseError("原启动行没有唯一匹配到已识别的服务端核心。")
    _check_arguments(jvm, game)
    if any(word.startswith("@") for word in game):
        raise StartupParseError("核心入口之后还有参数文件，不能当普通游戏参数静默处理。")
    java_path = Path(java.replace("\\", "/"))
    if "/" not in java.replace("\\", "/"):
        java_hint, java_kind = java, "path"
    elif java_path.is_absolute() and not java_path.resolve().is_relative_to(root.resolve()):
        java_hint, java_kind = str(java_path), "absolute"
        notes.append("原启动文件指定了其他电脑上的绝对 Java 路径；只作为提示，不执行或直接信任该路径。")
    else:
        hint = _inside(root, java, file=False)
        java_hint = hint.relative_to(root.resolve()).as_posix()
        java_kind = "bundled"
        if not hint.is_file():
            notes.append("原脚本指向的包内 Java 不存在；该路径仅作为提示，需另选与服务器版本匹配的运行时。")
    return {"source": source, "core": list(selected[0]), "kind": kind, "entry": selected[0][2],
            "java_hint": java_hint, "java_hint_kind": java_kind, "jvm_args": jvm,
            "game_args": game, "classpath": classpath, "main_class": main,
            "argument_files": argument_files, "cwd": ".", "warnings": list(dict.fromkeys(notes))}


def parse_startup_script(root, source, cores):
    """Return an exact static profile or fail; never fill guessed parameters."""
    root = Path(root).resolve()
    text, descriptor = _read(root, source)
    if len(Path(descriptor["path"]).parts) != 1:
        raise StartupParseError("仅自动适配服务器根目录的启动脚本；子目录脚本的工作目录需要手动确认。")
    if descriptor["format"] in {"bat", "cmd"}:
        calls, notes = _batch_calls(root, text)
    elif descriptor["format"] in {"ps1", "sh"}:
        calls, notes = _literal_shell_calls(root, text, descriptor["format"])
    else:
        raise StartupParseError("仅支持 BAT、CMD、PS1 和 SH 文本启动文件。")
    if len(calls) != 1:
        raise StartupParseError("启动脚本必须包含一个可确认的 Java 服务端调用，检测到 " + str(len(calls)) + " 个。")
    try:
        return _profile(root, calls[0], list(cores), descriptor, notes)
    except StartupParseError:
        raise
    except (OSError, ValueError, KeyError) as error:
        raise StartupParseError("无法完整继承原启动配置：" + str(error)) from None


def discover_startup_scripts(root, cores):
    root = Path(root).resolve()
    candidates = sorted([path for path in root.iterdir() if path.suffix.lower() in {".bat", ".cmd", ".ps1", ".sh"}
                         and path.name.lower() not in GENERATED], key=lambda path: path.name.casefold())
    if len(candidates) > MAX_SCRIPTS:
        raise StartupParseError("服务器根目录的启动脚本超过 32 个，请明确选择启动文件。")
    result = {"status": "missing", "profiles": [], "unsupported": [], "scripts": []}
    for path in candidates:
        source = {"path": path.name, "format": path.suffix.lower().lstrip("."),
                  "can_run_original": path.suffix.lower() in {".bat", ".cmd"}}
        try:
            _, source = _read(root, path)
            profile = parse_startup_script(root, path, cores)
            source = profile["source"]
            result["profiles"].append(profile)
        except (StartupParseError, OSError) as error:
            result["unsupported"].append({"source": source, "reason": str(error)})
        result["scripts"].append(source)
    if len(result["profiles"]) == 1 and not result["unsupported"]:
        result["status"] = "exact"
    elif result["profiles"]:
        result["status"] = "ambiguous"
    elif candidates:
        result["status"] = "unsupported"
    return result
