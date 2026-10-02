# 七章控制面板 · © 2026 EeryFrank 所有 · https://github.com/EeryFrank
"""Import plans and generated launch files. Archive scripts are only read."""
import hashlib
import json
from pathlib import Path
import shutil
import uuid


def split_selection(selected):
    if isinstance(selected, str) and "-script-" in selected:
        core_id, token = selected.split("-script-", 1)
        return core_id, token
    return selected, None


def _token(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:32]


def bootstrap_plan(prepared):
    """Use a statically verified installer template, never its dynamic shell code."""
    profile = prepared["profile"]
    return {"enabled": True, "requested": True, "original_fallback": False,
            "profile": profile, "original_launcher": None,
            "original_scripts": prepared["original_scripts"], "unsupported": [],
            "source": profile["source"], "manifest_used": False,
            "inferred_without_script": False, "bootstrap": prepared["provenance"],
            "warnings": prepared.get("warnings", []),
            "restart_policy": prepared.get("restart_policy", {})}


def plan(root, core, staging, selected, adapt, manifest):
    from native_server_archive import ArchiveInstallError, ArchiveSelectionRequired, _choice, _enumerate_cores
    from native_startup_import import discover_startup_scripts
    scan = discover_startup_scripts(root, _enumerate_cores(root))
    source_records = scan["scripts"]
    originals = [s for s in source_records if s.get("can_run_original") and Path(s["path"]).name == s["path"]]
    profiles = [p for p in scan["profiles"] if tuple(p["core"]) == tuple(core)]
    # This is a Windows panel. A companion Unix script is not an ambiguous
    # Windows entry when a complete native BAT/CMD profile is available.
    windows_profile = any(p["source"].get("format") in {"bat", "cmd"} for p in profiles)
    relevant_unsupported = scan.get("unsupported", [])
    if windows_profile:
        profiles = [p for p in profiles if p["source"].get("format") != "sh"]
        relevant_unsupported = [s for s in relevant_unsupported if s["source"].get("format") != "sh"]
    base = _choice(root, core, root.relative_to(staging).as_posix())
    _, chosen_token = split_selection(selected)
    original_fallback = bool(adapt and not manifest and not profiles and originals)
    effective_adapt = bool(adapt and not original_fallback)
    candidates = profiles if effective_adapt else originals
    choices = []
    for candidate in candidates:
        source = candidate["source"] if effective_adapt else candidate
        record = dict(base, id=base["id"] + "-script-" + _token({"original": candidate} if original_fallback else candidate),
                      startup_script=source["path"],
                      reason=("沿用原启动文件（复杂逻辑保持原样）：" if original_fallback else "读取并适配启动文件：" if effective_adapt else "沿用原启动文件：") + source["path"])
        choices.append((candidate, record))
    chosen = None
    if chosen_token:
        hits = [c for c, item in choices if item["id"].endswith("-script-" + chosen_token)]
        if len(hits) != 1:
            raise ArchiveSelectionRequired([item for _, item in choices] or [base], "启动文件或参数已变化，请重新选择入口。")
        chosen = hits[0]
    elif adapt and manifest:
        # An explicit, validated launch contract is stronger than a text guess.
        chosen = None
    elif original_fallback:
        raise ArchiveSelectionRequired([item for _, item in choices],
            "原启动文件包含动态逻辑，无法完整生成专属文件。可选择原启动项直接导入并由面板管理，无需改造服务器；原文件保持原样。")
    elif len(choices) == 1 and (not adapt or not relevant_unsupported):
        chosen = choices[0][0]
    elif choices:
        raise ArchiveSelectionRequired([item for _, item in choices], "请选择要适配的原启动文件。" if adapt else "请选择要沿用的原启动文件。")
    elif not adapt:
        raise ArchiveInstallError("未找到可直接绑定的原 BAT/CMD 启动文件。请勾选“生成七章面板专用启动文件”，或在压缩包内提供 Windows 启动文件。")
    elif source_records and not manifest:
        details = "；".join(item["source"]["path"] + "：" + item["reason"] for item in scan.get("unsupported", [])[:3])
        raise ArchiveInstallError("无法完整读取原启动逻辑，未生成会丢失参数的启动文件。可取消启动适配沿用原 BAT/CMD，或整理脚本后重试。" + details)
    return {"enabled": effective_adapt, "requested": adapt, "original_fallback": original_fallback,
            "profile": chosen if effective_adapt else None,
            "original_launcher": None if effective_adapt else chosen["path"],
            "original_scripts": originals, "unsupported": scan.get("unsupported", []),
            "source": chosen["source"] if effective_adapt and chosen else chosen if not effective_adapt else None,
            "manifest_used": bool(adapt and manifest), "inferred_without_script": bool(adapt and not manifest and not chosen)}


def _effective_jvm(arguments):
    # JVM heap options use the final occurrence. Keep that behavior when a
    # script appends its own heap after @user_jvm_args.txt.
    last = {}
    for index, arg in enumerate(arguments):
        if arg.startswith(("-Xms", "-Xmx")):
            last[arg[:4]] = index
    return [arg for index, arg in enumerate(arguments) if arg[:4] not in last or last[arg[:4]] == index]


def write(root, core, import_plan, manifest, server_id, minecraft, java, java_major):
    from native_launch_settings import (CONFIG, SCRIPT, LAUNCHER, IMPORT_JVM_FILE,
                                        _jvm_file, write_imported_launch)
    profile = import_plan["profile"]
    kind, entry, cp, main = core[1], core[2], [], ""
    if manifest:
        kind, cp, main = "classpath", manifest["classpath"], manifest["main_class"]
        jvm = list(manifest["jvm_args"])
        if (root / "user_jvm_args.txt").is_file():
            jvm += _jvm_file(root)
        game = list(manifest["game_args"])
    elif profile:
        kind, entry = profile["kind"], profile["entry"]
        cp, main = profile.get("classpath", []), profile.get("main_class", "")
        jvm, game = list(profile["jvm_args"]), list(profile["game_args"])
    else:
        jvm, game = _jvm_file(root), ([] if core[0] in {"velocity", "bungeecord", "waterfall", "nukkit"} else ["nogui"])
    config = dict(schema=1, server_id=server_id, minecraft_version=minecraft,
                  platform=core[0], kind=kind, entry=entry, classpath=cp,
                  main_class=main, java_major=java_major, java_path=java,
                  server_args=game)
    # Existing panel files from a re-exported ZIP remain recoverable byte for byte.
    names = [CONFIG, SCRIPT, LAUNCHER, IMPORT_JVM_FILE, "qizhang-java-path.txt", "qizhang-import.json"]
    old = [root / name for name in names if (root / name).is_file()]
    backup = None
    if old:
        backup = root / "qizhang-original-startup" / uuid.uuid4().hex
        backup.mkdir(parents=True)
        for item in old:
            shutil.copy2(item, backup / item.name)
    launcher = write_imported_launch(root, config, _effective_jvm(jvm))
    import_plan["generated"] = [LAUNCHER, SCRIPT, CONFIG, IMPORT_JVM_FILE]
    import_plan["original_backup"] = backup.relative_to(root).as_posix() if backup else None
    import_plan["message"] = ("已生成七章专用启动文件并自动绑定；原启动文件保留。"
        + ("读取来源：" + import_plan["source"]["path"] + "。" if import_plan["source"] else ""))
    return launcher
