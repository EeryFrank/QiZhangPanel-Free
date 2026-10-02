# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Official plugin/proxy download providers; archive installation stays unified."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
import re
import subprocess
import uuid
import zipfile

BUILTIN = {'paper', 'purpur', 'folia', 'velocity', 'bedrock'}
OFFICIAL = {
    'paper': 'https://papermc.io/downloads/paper', 'folia': 'https://papermc.io/downloads/folia',
    'velocity': 'https://papermc.io/downloads/velocity', 'purpur': 'https://purpurmc.org/downloads',
    'bukkit': 'https://www.spigotmc.org/wiki/buildtools/', 'spigot': 'https://www.spigotmc.org/wiki/buildtools/',
    'bungeecord': 'https://ci.md-5.net/job/BungeeCord/', 'waterfall': 'https://papermc.io/downloads/waterfall',
    'quilt': 'https://quiltmc.org/en/install/server/', 'sponge': 'https://spongepowered.org/downloads/',
    'arclight': 'https://github.com/IzzelAliz/Arclight/releases', 'catserver': 'https://github.com/Luohuayu/CatServer/releases',
    'mohist': 'https://mohistmc.com/', 'magma': 'https://magmafoundation.org/',
    'bedrock': 'https://www.minecraft.net/en-us/download/server/bedrock',
    'nukkit': 'https://github.com/CloudburstMC/Nukkit', 'pocketmine': 'https://pmmp.io/downloads',
}


def _download_bedrock(url, target):
    """Minecraft's CDN times out on some Python TLS clients; use system curl.

    Fixed official HTTPS origin only. No user curl config, redirects, shell,
    credentials, or executable from the archive is used.
    """
    from native_server_install import _open, ServerInstallError
    if not re.fullmatch(r'https://www\.minecraft\.net/bedrockdedicatedserver/bin-win/bedrock-server-\d+(?:\.\d+){3}\.zip', url):
        raise ServerInstallError('基岩官方下载 URL 格式异常。')
    curl = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32/curl.exe'
    if curl.is_file():
        result = subprocess.run([str(curl), '-q', '--fail', '--max-time', '120', '--connect-timeout', '20',
            '--max-filesize', str(1024**3), '--proto', '=https', '--silent', '--show-error',
            '--user-agent', 'Mozilla/5.0 QiZhangControlPanel/2.5.0',
            '--header', 'Accept: application/zip,*/*', '--referer', OFFICIAL['bedrock'],
            '--output', str(target), url], stdin=subprocess.DEVNULL, capture_output=True,
            timeout=135, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise ServerInstallError('基岩官方下载失败，请稍后重试或通过官方网页下载 ZIP 导入。下载程序退出码：' + str(result.returncode))
    else:
        with _open(url) as response, target.open('xb') as output:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > 1024**3:
                    raise ServerInstallError('基岩服务端压缩包超过 1 GB 限制。')
                output.write(chunk)
    if not zipfile.is_zipfile(target) or target.stat().st_size > 1024**3:
        raise ServerInstallError('官方下载内容不是有效服务端 ZIP，未执行或导入。')


def _version(value):
    return tuple(int(p) if p.isdigit() else p for p in re.split(r'[.\-]', value))


def options():
    from native_platforms import PLATFORMS, profile
    return [dict(profile(key), name=item['label'], official_url=OFFICIAL.get(key, ''),
                 install_method='builtin' if key in BUILTIN or key in {'vanilla', 'fabric', 'forge', 'neoforge'} else 'import')
            for key, item in PLATFORMS.items()]


def catalog(platform, version=None):
    from native_platforms import profile
    from native_server_install import _metadata_json, java_requirement, ServerInstallError
    p = profile(platform)
    base = dict(platform=platform, platform_profile=p, install_method=p['install_method'],
                official_url=OFFICIAL.get(platform, ''), minecraft_versions=[], loader_versions=[],
                default_minecraft_version='', minecraft_version='', default_loader_version='',
                java_requirement={'known': False, 'major': None, 'bits': 64, 'label': '按所选核心检查运行时'},
                support_scope='按平台分别适配。自动下载只选择官方稳定构建；其余可从官网取得文件后导入。')
    if platform not in BUILTIN:
        base['install_method'] = 'import'
        base['support_scope'] = '此平台通过官网取得完整 Windows 服务端后导入；不会下载第三方重新打包的核心。'
        return base
    if platform == 'bedrock':
        source = 'https://net-secondary.web.minecraft-services.net/api/v1.0/download/links'
        links = _metadata_json(source)['result']['links']
        matches = [row['downloadUrl'] for row in links if row.get('downloadType') == 'serverBedrockWindows']
        if len(matches) != 1:
            raise ServerInstallError('官方目录未返回唯一 Windows 稳定版下载。')
        match = re.fullmatch(r'https://www\.minecraft\.net/bedrockdedicatedserver/bin-win/bedrock-server-(\d+(?:\.\d+){3})\.zip', matches[0])
        if not match or version and version != match[1]:
            raise ServerInstallError('所选基岩版本已不在官方当前下载目录中，请刷新；旧版可导入已有完整服务端。')
        value = match[1]
        return dict(base, install_method='builtin', minecraft_versions=[value], minecraft_version=value,
                    default_minecraft_version=value, default_loader_version=value,
                    loader_versions=[{'version': value, 'stable': True, 'recommended': True}],
                    java_requirement={'known': False, 'major': None, 'bits': 64, 'label': '原生 Windows 服务端，无需 Java'},
                    download_url=matches[0], sources=[source],
                    support_scope='仅官方下载目录当前 Windows 稳定版。网络配置随核心版本保留；不自动切换传输模式。')
    if platform == 'purpur':
        endpoint = 'https://api.purpurmc.org/v2/purpur'
        versions = _metadata_json(endpoint).get('versions', [])
    else:
        endpoint = 'https://fill.papermc.io/v3/projects/' + platform
        groups = _metadata_json(endpoint).get('versions', {})
        versions = [v for group in groups.values() for v in group]
    versions = sorted({v for v in versions if re.fullmatch(r'\d+\.\d+(?:\.\d+)?', str(v))}, key=_version, reverse=True)
    if not versions:
        raise ServerInstallError('官方目录没有可识别的正式版本。')
    selected = version or versions[0]
    if selected not in versions:
        raise ServerInstallError('所选版本不在此平台官方目录中，请重新选择。')
    source = endpoint + ('/' + selected if platform == 'purpur' else '/versions/' + selected + '/builds')
    builds = _metadata_json(source)
    if platform == 'purpur':
        rows = [{'version': str(b), 'stable': True, 'recommended': str(b) == str(builds['builds']['latest'])}
                for b in reversed(builds.get('builds', {}).get('all', []))]
    else:
        rows = [{'version': str(b['id']), 'stable': b.get('channel') == 'STABLE', 'recommended': False,
                 'channel': b.get('channel', '')} for b in builds if b.get('downloads', {}).get('server:default')]
        first = next((r for r in rows if r['stable']), None)
        if first:
            first['recommended'] = True
        # Expose experimental availability honestly, never install it as a default.
        rows = [r for r in rows if r['stable']]
    java = java_requirement(selected) if platform != 'velocity' else {'known': True,
        'major': 25 if _version(selected) >= (4, 0, 0) else 17, 'bits': 64,
        'label': 'Java 25（4.x）/ Java 17（3.x）；下载后核对实际核心'}
    return dict(base, minecraft_versions=versions, default_minecraft_version=versions[0],
                minecraft_version=selected, loader_versions=rows, java_requirement=java,
                default_loader_version=next((r['version'] for r in rows if r['recommended']), ''),
                sources=[endpoint, source],
                support_scope=base['support_scope'] if rows else '此版本没有官方稳定构建。请另选版本；实验构建可从官网取得后自行导入。')


def install(platform, destination, java_path, progress, *, minecraft_version, loader_version=None,
            cache_root=None, eula_accepted=False):
    from native_server_install import _metadata_json, _open, ServerInstallError, validate_server_dir
    from native_server_archive import install_archive, core_java_requirement, _enumerate_cores, detect_minecraft_version
    from native_platforms import profile
    if platform not in BUILTIN:
        raise ServerInstallError('此平台请从官方链接取得完整服务端后使用导入功能。')
    validate_server_dir(destination)
    selected = catalog(platform, minecraft_version)
    build = str(loader_version or selected['default_loader_version'])
    if not any(r['version'] == build and r['stable'] for r in selected['loader_versions']):
        raise ServerInstallError('没有选择有效的官方稳定构建。')
    if platform == 'bedrock':
        if not eula_accepted:
            raise ServerInstallError('下载基岩官方端前请明确同意界面中的 Minecraft 服务协议。')
        cache = Path(cache_root or os.environ.get('QIZHANG_CACHE_ROOT', tempfile.gettempdir())) / 'QiZhangPanel-Free-install/platforms'
        cache.mkdir(parents=True, exist_ok=True)
        archive = cache / ('bedrock-' + minecraft_version + '-' + uuid.uuid4().hex + '.zip')
        progress(5, '正在下载基岩官方 Windows 稳定版…')
        _download_bedrock(selected['download_url'], archive)
        result = install_archive(archive, destination, '', progress, cache_root=cache)
        if result['platform'] != 'bedrock':
            raise ServerInstallError('官方下载内容不是预期的基岩服务端。已保留文件，未绑定或启动。')
        result['minecraft_version'] = minecraft_version
        with archive.open('rb') as stream:
            sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
        receipt = {'platform': 'bedrock', 'version': minecraft_version, 'url': selected['download_url'],
                   'metadata_url': selected['sources'][0], 'sha256': sha256,
                   'source_hash_verified': False, 'eula_accepted': True, 'game_started': False}
        (Path(destination) / 'qizhang-install-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        return result
    if platform == 'purpur':
        endpoint = f'https://api.purpurmc.org/v2/purpur/{minecraft_version}/{build}'
        meta = _metadata_json(endpoint)
        if meta.get('result') != 'SUCCESS':
            raise ServerInstallError('官方构建尚未成功。')
        url, expected, algorithm = endpoint + '/download', meta['md5'], 'md5'
    else:
        endpoint = f'https://fill.papermc.io/v3/projects/{platform}/versions/{minecraft_version}/builds/{build}'
        meta = _metadata_json(endpoint)
        if meta.get('channel') != 'STABLE':
            raise ServerInstallError('官方构建不是稳定发布。')
        artifact = meta['downloads']['server:default']
        url, expected, algorithm = artifact['url'], artifact['checksums']['sha256'], 'sha256'
    cache = Path(cache_root or os.environ.get('QIZHANG_CACHE_ROOT', tempfile.gettempdir())) / 'QiZhangPanel-Free-install/platforms'
    cache.mkdir(parents=True, exist_ok=True)
    progress(5, '正在下载并核对官方 ' + profile(platform)['label'] + ' 构建…')
    bundle = cache / (platform + '-' + uuid.uuid4().hex)
    bundle.mkdir()
    jar = bundle / (platform + '-' + minecraft_version + '-' + build + '.jar')
    with _open(url) as response, jar.open('xb') as output:
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > 1024**3:
                raise ServerInstallError('核心文件超过 1 GB 限制。')
            output.write(chunk)
    with jar.open('rb') as stream:
        digest = hashlib.file_digest(stream, algorithm).hexdigest()
    if digest.lower() != str(expected).lower():
        raise ServerInstallError('核心哈希与官方元数据不一致，未安装或执行。')
    cores = _enumerate_cores(bundle)
    if len(cores) != 1:
        raise ServerInstallError('官方下载内容没有唯一可识别核心。')
    core = cores[0]
    mc = '' if platform == 'velocity' else minecraft_version
    requirement = core_java_requirement(bundle, core, mc)
    descriptor = dict(platform=platform, minecraft_version=mc, loader_version=build,
                      java_major=requirement['major'])
    with jar.open('rb') as stream:
        sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
    receipt = dict(platform=platform, version=minecraft_version, build=build, url=url,
                   metadata_url=endpoint, sha256=sha256, source_hash_algorithm=algorithm,
                   source_hash_verified=True, game_started=False)
    archive = bundle / 'official-server.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_STORED) as pack:
        pack.write(jar, jar.name)
        pack.writestr('qizhang-install-receipt.json', json.dumps(receipt, ensure_ascii=False, indent=2))
        if profile(platform)['family'] == 'java':
            pack.writestr('eula.txt', 'eula=' + str(bool(eula_accepted)).lower() + '\n')
    result = install_archive(archive, destination, java_path, progress, cache_root=cache,
                             official_descriptor=descriptor)
    result['content_version'] = '官方 ' + profile(platform)['label'] + ' 构建 ' + build
    return result
