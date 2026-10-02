# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Connection-address presentation from this host; never probe public services."""
from collections.abc import Mapping
import ipaddress
import re
import socket
import threading
import time

CACHE_SECONDS = 60.0
_cache_lock = threading.Lock()
_cache_expires = 0.0
_cache_ips = ()


def _ip(value):
    if not isinstance(value, str) or len(value) > 128:
        return None
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    if "%" in value:
        scope = value.rsplit("%", 1)[1]
        if not re.fullmatch(r"[A-Za-z0-9_.~-]{1,64}", scope):
            return None
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    if address.is_multicast or str(address) == "255.255.255.255":
        return None
    return address


def _normalized_ips(values):
    addresses = {}
    for value in values:
        address = _ip(value)
        if address is not None and not address.is_unspecified:
            addresses[str(address)] = address
    return sorted(addresses, key=lambda value: (addresses[value].version, int(addresses[value]), value))


def _discover_local_ips():
    """The local hostname's interface addresses; no connection or IP-service call."""
    values = []
    try:
        records = socket.getaddrinfo(socket.gethostname(), None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except OSError:
        return []
    for family, _, _, _, address in records[:256]:
        if family not in {socket.AF_INET, socket.AF_INET6} or not address:
            continue
        value = address[0]
        if family == socket.AF_INET6 and len(address) >= 4 and address[3] and "%" not in value:
            value += "%" + str(address[3])
        values.append(value)
    return _normalized_ips(values)


def local_interface_ips():
    """One in-memory lookup per minute, including failures; no worker is started."""
    global _cache_expires, _cache_ips
    with _cache_lock:
        now = time.monotonic()
        if now >= _cache_expires:
            try:
                _cache_ips = tuple(_normalized_ips(_discover_local_ips()))
            except (OSError, ValueError, TypeError):
                _cache_ips = ()
            _cache_expires = now + CACHE_SECONDS
        return list(_cache_ips)


def _port(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return 0
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,5}", text):
        return 0
    number = int(text)
    return number if 1 <= number <= 65535 else 0


def _endpoint(address, port):
    return ("[" + str(address) + "]" if address.version == 6 else str(address)) + ":" + str(port)


def _public_endpoint(value):
    # Take only a valid endpoint, never a snapshot's message, log, URL or token.
    if not isinstance(value, str) or len(value) > 320 or value != value.strip():
        return ""
    ipv6 = re.fullmatch(r"\[([^\[\]]+)\]:([0-9]{1,5})", value)
    if ipv6:
        address, port = _ip(ipv6[1]), _port(ipv6[2])
        if address is None or address.version != 6 or address.is_unspecified or not port:
            return ""
        return _endpoint(address, port)
    if value.count(":") != 1:
        return ""
    host, raw_port = value.split(":")
    port = _port(raw_port)
    if not port or not host or len(host) > 253:
        return ""
    address = _ip(host)
    if address is not None:
        return _endpoint(address, port) if address.version == 4 and not address.is_unspecified else ""
    if not all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in host.split(".")):
        return ""
    # Numeric strings that were rejected as IPv4 are not useful hostnames here.
    if re.fullmatch(r"[0-9.]+", host):
        return ""
    return host.lower() + ":" + str(port)


def build_connection_addresses(properties, tunnel_snapshot=None, *, interface_ips=None):
    """Build this server's addresses. They are configuration hints, not probes."""
    result = {"bind_ip": "", "port": 0, "ips": [], "ipv4": [], "endpoints": [],
              "note": "", "public_endpoints": [], "public_note": "暂无正在运行的公网穿透地址。"}
    if isinstance(tunnel_snapshot, Mapping):
        if (tunnel_snapshot.get("process_running") is True and tunnel_snapshot.get("online") is True
                and tunnel_snapshot.get("state") == "online"):
            public = _public_endpoint(tunnel_snapshot.get("public_address"))
            if public:
                result["public_endpoints"] = [public]
                result["public_note"] = "当前穿透客户端报告已连接；未进行外网连通测试。"
            else:
                result["public_note"] = "穿透已在线，但尚无可确认格式的连接地址。"
        else:
            result["public_note"] = "穿透未在线，不显示上次保存的地址。"
    if not isinstance(properties, Mapping):
        result["note"] = "暂时无法读取服务器地址配置。"
        return result
    raw_bind = properties.get("server-ip", "")
    if not isinstance(raw_bind, str):
        result["note"] = "server-ip 配置无效，请在服务器设置中检查。"
        return result
    raw_bind = raw_bind.strip()
    bind = _ip(raw_bind) if raw_bind else None
    if raw_bind and bind is None:
        result["note"] = "server-ip 不是有效的 IP 地址，请在服务器设置中检查。"
        return result
    result["bind_ip"] = str(bind) if bind is not None else ""
    result["port"] = _port(properties.get("server-port", 25565))
    if not result["port"]:
        result["note"] = "server-port 必须在 1～65535 之间；当前无法生成连接地址。"
        return result
    if bind is not None and not bind.is_unspecified:
        ips = [str(bind)]  # An explicit bind never advertises unrelated interfaces.
    else:
        detected = local_interface_ips() if interface_ips is None else interface_ips
        ips = _normalized_ips(detected)
        if bind is not None:
            ips = [value for value in ips if _ip(value).version == bind.version]
        non_loopback = [value for value in ips if not _ip(value).is_loopback]
        ips = non_loopback or ips
    result["ips"] = ips
    result["ipv4"] = [value for value in ips if _ip(value).version == 4]
    result["endpoints"] = [_endpoint(_ip(value), result["port"]) for value in ips]
    if not ips:
        result["note"] = "未检测到与监听配置对应的本机 IP；监听通配地址不能作为连接地址。"
    elif all(_ip(value).is_loopback for value in ips):
        result["note"] = "这些地址仅供服务器电脑本机连接，其他电脑不能使用。"
    else:
        result["note"] = "根据服务器电脑和监听配置生成；需服务器已启动且端口可访问，未验证外网连通。"
        if any(_ip(value).is_link_local for value in ips):
            result["note"] += " 链路本地地址仅限同一网络链路；IPv6 区域编号需按连接电脑的网卡调整。"
    return result
