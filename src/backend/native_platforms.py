# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Conservative runtime capabilities, not a promise that every release was tested."""
from copy import deepcopy
import re


from native_platform_templates import catalog as _template_catalog

PLATFORMS = _template_catalog()


def profile(platform, root=None):
    key = str(platform or '').strip().lower()
    if key not in PLATFORMS:
        raise ValueError('不支持的平台标识：' + key)
    value = deepcopy(PLATFORMS[key])
    if key == 'bedrock' and root is not None:
        from native_platform_config import _path, _properties
        path = _path(root, value['config_file'])
        if path.is_file() and path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('基岩配置文件过大，无法判断传输模式。')
        values = _properties(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}
        transport = values.get('transport', 'raknet').lower()
        if transport not in {'raknet', 'nethernet'}:
            raise ValueError('未识别的基岩传输模式，无法安全判断网络协议。')
        value['transport'] = transport
        value['network_protocol'] = 'TCP' if transport == 'nethernet' else 'UDP'
        if transport == 'nethernet':
            value['editable_properties'].append('server-ip')
    return value


def process_images(platform):
    runtime = profile(platform)['runtime']
    return {'java.exe', 'javaw.exe'} if runtime == 'java' else {'bedrock_server.exe'} if runtime == 'native' else {'php.exe'} if runtime == 'php' else set()


# Log consumption can process thousands of lines per second. Rules are immutable
# for this process; do not deep-copy a UI profile for every ready/stop probe.
_LOG_RULES = {key: (re.compile(spec['ready_pattern']),
                    re.compile(spec['stopping_pattern'], 0 if spec['family'] == 'java' else re.I))
              for key, spec in PLATFORMS.items()}


def _log_rule(platform):
    key = str(platform or '').strip().lower()
    if key not in _LOG_RULES:
        raise ValueError('不支持的平台标识：' + key)
    return _LOG_RULES[key]


def ready_line(platform, line):
    return bool(_log_rule(platform)[0].search(line))


def stopping_line(platform, line):
    return bool(_log_rule(platform)[1].search(line))


def uses_capture_log(platform):
    return profile(platform)['family'] != 'java'


def proxy_endpoint(root, platform):
    """Read the actual proxy listener; ambiguous multi-listener state is unknown."""
    from pathlib import Path
    spec = profile(platform)
    path = Path(root) / spec['config_file']
    if not path.exists():
        return {'server-ip': '', 'server-port': str(spec['default_port'])}
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('代理配置过大，无法确认监听端口。')
    text = path.read_text(encoding='utf-8-sig')
    if platform == 'velocity':
        import tomllib
        address = tomllib.loads(text).get('bind')
        if not isinstance(address, str):
            raise ValueError('velocity.toml 缺少有效 bind，无法确认端口。')
    else:
        # Bungee/Waterfall may intentionally expose several listeners. Never
        # guess a global unrelated host key or silently select the first one.
        lines = text.splitlines()
        blocks = [index for index, line in enumerate(lines) if re.fullmatch(r'listeners:\s*(?:#.*)?', line)]
        if len(blocks) != 1:
            raise ValueError('代理配置中 listeners 不唯一，无法确认端口。')
        values = []
        for line in lines[blocks[0] + 1:]:
            if line and not line[0].isspace() and not line.startswith(('-', '#')):
                break
            match = re.fullmatch(r'(?:\s*-\s+|\s+)host:\s*[\'"]?([^\'"#]+?)[\'"]?\s*(?:#.*)?', line)
            if match:
                values.append(match.group(1).strip())
        if len(values) != 1:
            raise ValueError('代理存在多个或未识别的监听入口，请先在原配置中保留唯一可管理入口。')
        address = values[0]
    match = re.fullmatch(r'(?:\[([^\]]+)\]|([^:]*)):(\d{1,5})', address)
    if not match or not 1 <= int(match[3]) <= 65535:
        raise ValueError('代理监听地址无效；必须包含明确端口。')
    return {'server-ip': match[1] or match[2], 'server-port': match[3]}
