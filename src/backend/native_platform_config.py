# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Platform endpoint adapters. Callers must establish stopped/owned state first."""
from pathlib import Path
import ipaddress
import re
import uuid


def _path(root, name):
    root = Path(root).resolve()
    path = root / name
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
            raise ValueError('平台配置路径包含链接，未修改。')
    if not name or path.parent != root or (path.exists() and not path.is_file()):
        raise ValueError('平台配置文件无效。')
    return path


def _records(text):
    from server_manager import ServerManager
    return ServerManager._property_records(text)


def _properties(text):
    values = {}
    for logical, _ in _records(text):
        if logical.lstrip().startswith(('#', '!')) or '=' not in logical:
            continue
        key, value = logical.split('=', 1)
        values[key.strip()] = value.strip()
    return values


def _replace_properties(text, updates):
    """Edit complete logical records, preserving unedited physical bytes."""
    current = _properties(text)
    updates = {key: value for key, value in updates.items()
               if current.get(key, '' if key == 'server-ip' else None) != value}
    if not updates:
        return text
    newline = '\r\n' if '\r\n' in text else '\r' if '\r' in text and '\n' not in text else '\n'
    found, output = set(), []
    for logical, raw in _records(text):
        if not logical.lstrip().startswith(('#', '!')) and '=' in logical:
            key, value = logical.split('=', 1)
            key = key.strip()
            if key in updates:
                found.add(key)
                if value.strip() == updates[key]:
                    output.append(raw)
                else:
                    ending = raw[len(raw.rstrip('\r\n')):]
                    output.append(key + '=' + updates[key] + ending)
                continue
        output.append(raw)
    result = ''.join(output)
    for key, value in updates.items():
        if key in found:
            continue
        records = _records(result)
        tail = records[-1][0] if records else ''
        if not tail.lstrip().startswith(('#', '!')) and (len(tail) - len(tail.rstrip('\\'))) % 2:
            raise ValueError('配置文件末尾存在未结束的续行，未追加端口或地址；原文件保留。')
        if result and not result.endswith(('\r', '\n')):
            result += newline
        result += key + '=' + value + newline
    return result


def read_endpoint(root, platform):
    from native_platforms import profile, proxy_endpoint
    p = profile(platform, root)
    if not p['config_file']:
        raise ValueError('自定义平台尚未配置监听端口，不能推测。')
    path = _path(root, p['config_file'])
    if p['family'] == 'proxy':
        endpoint = proxy_endpoint(Path(root), platform)
        return dict(endpoint, network_protocol=p['network_protocol'])
    if path.is_file() and path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('平台配置文件过大。')
    content = path.read_text(encoding='utf-8-sig') if path.is_file() else ''
    values = _properties(content)
    port = int(values.get('server-port', p['default_port']))
    if not 1 <= port <= 65535:
        raise ValueError('服务器端口超出范围。')
    return {'server-ip': values.get('server-ip', '').strip() if platform != 'bedrock' or values.get('transport') == 'nethernet' else '',
            'server-port': port, 'network_protocol': p['network_protocol']}


def write_endpoint(root, platform, address, port):
    from native_platforms import profile
    p = profile(platform, root)
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError('服务器端口必须为 1～65535。')
    address = str(address).strip()
    if address:
        ipaddress.ip_address(address)
    # Prove the selected parser supports this exact file before any mutation.
    read_endpoint(root, platform)
    path = _path(root, p['config_file'])
    old = path.read_bytes() if path.is_file() else b''
    if len(old) > 2 * 1024 * 1024:
        raise ValueError('平台配置文件过大。')
    text = old.decode('utf-8-sig')
    newline = '\r\n' if '\r\n' in text else '\n'
    bedrock_ip = platform == 'bedrock' and _properties(text).get('transport', 'raknet') == 'nethernet'
    if platform == 'bedrock' and not bedrock_ip and address not in ('', '0.0.0.0', '::'):
        raise ValueError('当前基岩传输模式不使用 server-ip，不能写入无效的监听地址。')
    if p['family'] == 'proxy':
        host = '[' + address + ']' if ':' in address else address or '0.0.0.0'
        endpoint = host + ':' + str(port)
        if platform == 'velocity':
            pattern = r'(?m)^(bind\s*=\s*)["\'][^"\'\r\n]*["\']([^\r\n]*)(?=\r?$)'
            if text and len(re.findall(pattern, text)) != 1:
                raise ValueError('Velocity bind 配置不是唯一可编辑项，请检查原文件。')
            text = re.sub(pattern, lambda m: m[1] + '"' + endpoint + '"' + m[2], text) if text else 'bind = "' + endpoint + '"' + newline
        else:
            # proxy_endpoint has already rejected multiple listeners/hosts.
            pattern = r'(?m)^((?:\s*-\s+|\s+)host:\s*)[^\r\n#]*(.*)$'
            if text and len(re.findall(pattern, text)) != 1:
                raise ValueError('代理 listeners.host 不是唯一可编辑项，请检查原文件。')
            text = re.sub(pattern, lambda m: m[1] + "'" + endpoint + "'" + m[2], text) if text else "listeners:" + newline + "  - host: '" + endpoint + "'" + newline
    else:
        updates = {'server-port': str(port)}
        if platform != 'bedrock' or bedrock_ip:
            updates['server-ip'] = address
        text = _replace_properties(text, updates)
    # Configuration updates do not remove unrelated world/plugin settings.
    data = (b'\xef\xbb\xbf' if old.startswith(b'\xef\xbb\xbf') else b'') + text.encode('utf-8')
    if data == old:
        return read_endpoint(root, platform)
    tmp = path.with_name(path.name + '.qizhang-' + uuid.uuid4().hex + '.tmp')
    tmp.write_bytes(data)
    try:
        if (path.read_bytes() if path.is_file() else b'') != old:
            raise ValueError('配置文件已被其他程序修改，未覆盖。')
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return read_endpoint(root, platform)
