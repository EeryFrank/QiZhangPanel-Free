# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Versioned, inert platform rules shared by discovery, installation and runtime.

Rules contain data only. Unknown releases remain unknown; a matching rule is
not evidence that every release of that platform was exercised in a real server.
"""
from copy import deepcopy
import hashlib
import json
import re

SCHEMA_VERSION = 1
RULE_VERSION = "2026.09.30.1"

CATSERVER_MAIN = "catserver.server.CatServerLaunch"
CATSERVER_STANDARD_MAIN = "catserver.server.launcher.CatServerLauncher"
LEGACY_FORGE_MAINS = {"net.minecraftforge.fml.relauncher.ServerLaunchWrapper", "cpw.mods.fml.relauncher.ServerLaunchWrapper", "net.minecraftforge.server.ServerMain"}
VANILLA_MAINS = {"net.minecraft.bundler.Main", "net.minecraft.server.Main", "net.minecraft.server.MinecraftServer"}
BUKKIT_MAINS = {"org.bukkit.craftbukkit.Main"}
JAVA_SERVER_MAINS = {
    "com.velocitypowered.proxy.Velocity": "velocity",
    "net.md_5.bungee.Bootstrap": "bungeecord",
    "net.md_5.bungee.BungeeCord": "bungeecord",
    "cn.nukkit.Nukkit": "nukkit",
    "org.spongepowered.vanilla.applaunch.Main": "sponge",
    "org.spongepowered.server.launch.VersionCheckingMain": "sponge",
    "org.quiltmc.loader.impl.launch.server.QuiltServerLauncher": "quilt",
    "io.izzel.arclight.boot.application.Main": "arclight",
    "io.izzel.arclight.server.Launcher": "arclight",
    "com.mohistmc.MohistMC": "mohist",
    "com.mohistmc.MohistMCStart": "mohist",
    "org.magmafoundation.magma.MagmaStart": "magma",
}
PAPERCLIP_MAIN = "io.papermc.paperclip.Main"

def _item(key, label, family='java', runtime='java', config='server.properties',
          stop='stop', protocol='TCP', port=25565, builtin=False):
    game = family == 'java'
    return dict(id=key, label=label, family=family, runtime=runtime, config_file=config,
                stop_command=stop, network_protocol=protocol, default_port=port,
                capabilities=dict(console=True, players=game, save_world=game,
                                  online_backup=False, light_backup=game, rcon=game, java=runtime == 'java',
                                  properties=config == 'server.properties'),
                install_method='builtin' if builtin else 'import')


TEMPLATES = {key: _item(key, label, builtin=key in {'vanilla', 'fabric', 'forge', 'neoforge', 'paper', 'purpur', 'folia'})
             for key, label in [('vanilla', '原版 Java'), ('fabric', 'Fabric'), ('quilt', 'Quilt'),
                                ('forge', 'Forge'), ('neoforge', 'NeoForge'), ('bukkit', 'CraftBukkit'),
                                ('spigot', 'Spigot'), ('paper', 'Paper'), ('purpur', 'Purpur'),
                                ('folia', 'Folia'), ('sponge', 'Sponge'), ('arclight', 'Arclight'),
                                ('catserver', 'CatServer'), ('mohist', 'Mohist'), ('magma', 'Magma')]}
for _key, _label in [('velocity', 'Velocity'), ('bungeecord', 'BungeeCord'), ('waterfall', 'Waterfall')]:
    TEMPLATES[_key] = _item(_key, _label, family='proxy', config='velocity.toml' if _key == 'velocity' else 'config.yml', stop='end', port=25565 if _key == 'velocity' else 25577, builtin=_key == 'velocity')
TEMPLATES['bedrock'] = _item('bedrock', '基岩版官方服务端', family='bedrock', runtime='native', protocol='UDP', port=19132, builtin=True)
TEMPLATES['nukkit'] = _item('nukkit', 'Nukkit', family='bedrock', protocol='UDP', port=19132)
TEMPLATES['pocketmine'] = _item('pocketmine', 'PocketMine-MP', family='bedrock', runtime='php', protocol='UDP', port=19132)
TEMPLATES['custom'] = _item('custom', '自定义服务端', family='custom', runtime='custom', config='')
for _spec in TEMPLATES.values():
    _spec['editable_properties'] = None  # Java game server properties are supplied by ServerManager.
    if _spec['family'] == 'proxy':
        _spec['editable_properties'] = ['server-ip', 'server-port']
    elif _spec['id'] == 'bedrock':
        _spec['editable_properties'] = ['server-port', 'max-players', 'online-mode', 'view-distance']
    elif _spec['id'] in {'nukkit', 'pocketmine'}:
        _spec['editable_properties'] = ['server-ip', 'server-port', 'max-players', 'motd', 'white-list']
    elif _spec['family'] == 'custom':
        _spec['editable_properties'] = []


JAVA_READY = r'\]: Done \([0-9.]+s\)! For help, type "help"'
JAVA_STOPPING = r'\]: Stopping server$'
OTHER_STOPPING = r'\b(?:Stopping server|Stopping the server|Shutting down the proxy|Closing listener|Server stop requested)\b'
READY = {
    'bedrock': r'\bServer started\.',
    'bungeecord': r'\bListening on [/\[]?\S+',
    'waterfall': r'\bListening on [/\[]?\S+',
    'velocity': r'\bDone \([0-9.]+s\)!',
    'nukkit': r'\bDone \([0-9.]+s\)!|\bDone \([0-9.]+s\)! For help',
    'pocketmine': r'\bDone \([0-9.]+s\)!|\bDone \([0-9.]+s\)! For help',
}
CLASS_PREFIX = {'bungeecord': 'net/md_5/bungee/', 'waterfall': 'net/md_5/bungee/',
                'velocity': 'com/velocitypowered/', 'nukkit': 'cn/nukkit/'}
MAIN_CLASSES = {key: [main for main, owner in JAVA_SERVER_MAINS.items() if owner == key]
                for key in TEMPLATES}
MAIN_CLASSES.update(vanilla=sorted(VANILLA_MAINS), forge=sorted(LEGACY_FORGE_MAINS),
                    catserver=[CATSERVER_MAIN, CATSERVER_STANDARD_MAIN],
                    bukkit=sorted(BUKKIT_MAINS), spigot=sorted(BUKKIT_MAINS))
for _name in ('paper', 'purpur', 'folia'):
    MAIN_CLASSES[_name] = [PAPERCLIP_MAIN]
MAIN_CLASSES['waterfall'] = list(MAIN_CLASSES['bungeecord'])

for _key, _spec in TEMPLATES.items():
    _spec.update(template_id='qizhang.' + _key, template_schema=SCHEMA_VERSION,
                 template_version=RULE_VERSION,
                 main_classes=MAIN_CLASSES.get(_key, []), class_prefix=CLASS_PREFIX.get(_key, ''),
                 ready_pattern=READY.get(_key, JAVA_READY),
                 stopping_pattern=JAVA_STOPPING if _spec['family'] == 'java' else OTHER_STOPPING,
                 command_channels=['owned-stdin', 'configured-rcon'] if _spec['capabilities']['rcon'] else ['owned-stdin'],
                 runtime_policy='entry-bytecode-minimum' if _key in {'velocity', 'bungeecord', 'waterfall', 'nukkit'} else
                                'minecraft-and-entry-bytecode' if _spec['runtime'] == 'java' else
                                'bundled-platform-runtime' if _spec['runtime'] in {'native', 'php'} else 'manual',
                 validation_scope='platform rule; validate the selected release separately')


def template(platform):
    key = str(platform or '').strip().lower()
    if key not in TEMPLATES:
        raise ValueError('不支持的平台标识：' + key)
    result = deepcopy(TEMPLATES[key])
    result['template_sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False,
                                                          separators=(',', ':')).encode('utf-8')).hexdigest()
    return result


def catalog():
    return {key: template(key) for key in TEMPLATES}


def receipt(platform):
    value = template(platform)
    return {key: value[key] for key in ('template_id', 'template_schema', 'template_version', 'template_sha256')}


def minecraft_java_requirement(minecraft_version):
    """Pinned existing policy; future releases never silently inherit Java 21."""
    match = re.fullmatch(r"1\.(\d+)(?:\.(\d+))?", minecraft_version or "")
    major = None
    if match:
        minor, patch = int(match.group(1)), int(match.group(2) or 0)
        if 7 <= minor <= 16:
            major = 8
        elif minor == 17:
            major = 16
        elif 18 <= minor <= 19 or minor == 20 and patch <= 4:
            major = 17
        elif minor == 20 and patch >= 5 or minor == 21:
            major = 21
    if re.fullmatch(r"26\.[12](?:\.\d+)?", minecraft_version or ""):
        major = 25
    return {"major": major, "bits": 64, "known": major is not None,
            "label": "64 位 Java " + str(major) if major else "版本未知，请手动选择兼容的 64 位 Java"}
