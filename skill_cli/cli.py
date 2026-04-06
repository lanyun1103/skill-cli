#!/usr/bin/env python3
"""skill-cli: 从 Git 仓库按组安装 Claude Code / Codex Skills

用法:
    skill-cli add <git-url>                     添加一个 skill 仓库源
    skill-cli list [<source>]                   列出某个源（或所有源）的分组
    skill-cli install <source> <group>          安装一组 skills 到当前项目
    skill-cli install <source> <group> -g       安装一组 skills 到用户全局
    skill-cli sync [<source>]                   重同步已安装 skills 到目标目录
    skill-cli uninstall <source> <group>        从当前项目卸载
    skill-cli uninstall <source> <group> -g     从用户全局卸载
    skill-cli sync <source> <group>             同步某组到最新（pull + 重装）
    skill-cli sync <source> <group> -g          同步某组到全局
    skill-cli status                            查看所有安装状态
    skill-cli update [<source>]                 更新源（git pull）
    skill-cli remove <source>                   删除一个源

仓库约定:
    仓库中需有 skills.yaml 定义分组，skills/ 目录下放 SKILL.md 文件。
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

CACHE_DIR = Path.home() / ".skill-cli" / "sources"
REGISTRY_FILE = Path.home() / ".skill-cli" / "registry.json"
INSTALL_TRACK_FILE = Path.home() / ".skill-cli" / "installed.json"
CLAUDE_USER_SKILLS = Path.home() / ".claude" / "skills"
CODEX_USER_SKILLS = Path.home() / ".codex" / "skills"
CLAUDE_USER_AGENTS = Path.home() / ".claude" / "agents"
CODEX_USER_AGENTS = Path.home() / ".codex" / "agents"


def _ensure_dirs():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not REGISTRY_FILE.exists():
        REGISTRY_FILE.write_text("{}", encoding="utf-8")
    if not INSTALL_TRACK_FILE.exists():
        INSTALL_TRACK_FILE.write_text("{}", encoding="utf-8")


def _load_registry() -> dict:
    _ensure_dirs()
    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))


def _save_registry(reg: dict):
    REGISTRY_FILE.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_install_track() -> dict:
    """加载安装追踪记录: {scope: {skill_name: source_name}}"""
    _ensure_dirs()
    return json.loads(INSTALL_TRACK_FILE.read_text(encoding="utf-8"))


def _save_install_track(track: dict):
    INSTALL_TRACK_FILE.write_text(json.dumps(track, indent=2, ensure_ascii=False), encoding="utf-8")


def _track_key(global_install: bool) -> str:
    return "global" if global_install else str(Path.cwd())


def _track_scope_is_global(track_key: str) -> bool:
    return track_key == "global"


def _source_name_from_url(url: str) -> str:
    """从 git URL 提取名称: github.com/user/repo → repo"""
    name = url.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


def _is_local_source(url: str) -> bool:
    return Path(url).expanduser().exists()


def _sync_local_source(url: str, name: str) -> Path:
    src = Path(url).expanduser().resolve()
    dest = CACHE_DIR / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git", ".git/*", "__pycache__", "*.pyc"))
    return dest


def _clone_or_pull(url: str, name: str) -> Path:
    if _is_local_source(url):
        action = "同步本地源" if (CACHE_DIR / name).exists() else "导入本地源"
        print(f"  🔄 {action} {name}...")
        return _sync_local_source(url, name)

    dest = CACHE_DIR / name
    if dest.exists():
        print(f"  🔄 更新 {name}...")
        subprocess.run(["git", "-C", str(dest), "pull", "--ff-only", "-q"], check=True)
    else:
        print(f"  📥 克隆 {name}...")
        subprocess.run(["git", "clone", "-q", url, str(dest)], check=True)
    return dest


def _load_source_config(name: str) -> tuple[dict, Path, Path]:
    """加载某个源的 skills.yaml、skills 目录、agents 目录路径"""
    source_dir = CACHE_DIR / name
    config_file = source_dir / "skills.yaml"
    if not config_file.exists():
        print(f"❌ 源 {name} 中没有 skills.yaml")
        sys.exit(1)
    with open(config_file, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config, source_dir / "skills", source_dir / "agents"


def _normalize_target(target: str | None) -> str:
    value = (target or "claude").strip().lower()
    aliases = {
        "claude": "claude",
        "claude-code": "claude",
        "claudecode": "claude",
        "cloudcode": "claude",
        "codex": "codex",
    }
    if value not in aliases:
        print(f"❌ 不支持的 skill target: {target}")
        print("   支持: claude, codex")
        sys.exit(1)
    return aliases[value]


def _parse_skill_ref(skill_ref) -> dict:
    if isinstance(skill_ref, str):
        return {"name": skill_ref}
    if isinstance(skill_ref, dict):
        name = skill_ref.get("name") or skill_ref.get("skill")
        if not name:
            print(f"❌ 非法的 skill 定义: {skill_ref}")
            sys.exit(1)
        return {"name": name, "target": skill_ref.get("target")}
    print(f"❌ 非法的 skill 定义: {skill_ref}")
    sys.exit(1)


def _parse_agent_ref(agent_ref) -> dict:
    if isinstance(agent_ref, str):
        return {"name": agent_ref}
    if isinstance(agent_ref, dict):
        name = agent_ref.get("name") or agent_ref.get("agent")
        if not name:
            print(f"❌ 非法的 agent 定义: {agent_ref}")
            sys.exit(1)
        return {"name": name, "target": agent_ref.get("target")}
    print(f"❌ 非法的 agent 定义: {agent_ref}")
    sys.exit(1)


def _get_skill_meta(config: dict, skill_name: str) -> dict:
    meta = config.get("skills", {}).get(skill_name, {})
    return meta if isinstance(meta, dict) else {}


def _resolve_skill_target(config: dict, skill_ref: dict) -> str:
    skill_name = skill_ref["name"]
    target = skill_ref.get("target") or _get_skill_meta(config, skill_name).get("target")
    return _normalize_target(target)


def _get_agent_meta(config: dict, agent_name: str) -> dict:
    meta = config.get("agents", {}).get(agent_name, {})
    return meta if isinstance(meta, dict) else {}


def _resolve_agent_target(config: dict, agent_ref: dict) -> str:
    agent_name = agent_ref["name"]
    target = agent_ref.get("target") or _get_agent_meta(config, agent_name).get("target") or "codex"
    return _normalize_target(target)


def _group_skill_refs(group: dict) -> list[dict]:
    return [_parse_skill_ref(item) for item in group.get("skills", [])]


def _group_agent_refs(group: dict) -> list[dict]:
    return [_parse_agent_ref(item) for item in group.get("agents", [])]


def _iter_source_skill_refs(config: dict):
    seen = set()
    for group in config.get("groups", {}).values():
        for skill_ref in _group_skill_refs(group):
            name = skill_ref["name"]
            if name in seen:
                continue
            seen.add(name)
            yield skill_ref


def _iter_source_agent_refs(config: dict):
    seen = set()
    for group in config.get("groups", {}).values():
        for agent_ref in _group_agent_refs(group):
            name = agent_ref["name"]
            if name in seen:
                continue
            seen.add(name)
            yield agent_ref


def _get_target_dir(target: str, global_install: bool, kind: str = "skill") -> Path:
    target = _normalize_target(target)
    if kind not in {"skill", "agent"}:
        print(f"❌ 未知类型: {kind}")
        sys.exit(1)
    if global_install:
        if kind == "skill":
            return CLAUDE_USER_SKILLS if target == "claude" else CODEX_USER_SKILLS
        return CLAUDE_USER_AGENTS if target == "claude" else CODEX_USER_AGENTS
    project_root = Path.cwd()
    leaf = "skills" if kind == "skill" else "agents"
    return project_root / (".claude" if target == "claude" else ".codex") / leaf


def _target_artifact_path(kind: str, target: str, global_install: bool, name: str) -> Path:
    root = _get_target_dir(target, global_install, kind=kind)
    return root / name if kind == "skill" else root / f"{name}.toml"


def _alternate_target_paths(kind: str, name: str, global_install: bool) -> list[Path]:
    return [
        _target_artifact_path(kind, "claude", global_install, name),
        _target_artifact_path(kind, "codex", global_install, name),
    ]


def _read_skill_file(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _skill_dir_digest(path: Path) -> str:
    if not path.exists():
        return ""

    digest = hashlib.sha256()
    for file_path in sorted(p for p in path.rglob("*") if p.is_file()):
        rel = file_path.relative_to(path).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _file_digest(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _artifact_digest(kind: str, path: Path) -> str:
    return _skill_dir_digest(path) if kind == "skill" else _file_digest(path)


def _tracked_record(track: dict, track_key: str, skill_name: str) -> dict:
    raw = track.get(track_key, {}).get(skill_name)
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return {"source": raw}
    return {}


def _tracked_source(track: dict, track_key: str, skill_name: str) -> str:
    return _tracked_record(track, track_key, skill_name).get("source", "")


def _track_item_name(kind: str, name: str) -> str:
    return name if kind == "skill" else f"agent:{name}"


def _set_tracked_record(track: dict, track_key: str, skill_name: str, source: str, target: str, kind: str = "skill"):
    track.setdefault(track_key, {})
    track[track_key][_track_item_name(kind, skill_name)] = {"source": source, "target": target, "kind": kind}


def _remove_stale_copies(kind: str, skill_name: str, global_install: bool, keep: Path | None = None):
    for candidate in _alternate_target_paths(kind, skill_name, global_install):
        if keep and candidate == keep:
            continue
        if candidate.exists():
            if candidate.is_dir():
                shutil.rmtree(candidate)
            else:
                candidate.unlink()


def _install_artifact_copy(kind: str, src: Path, dst: Path, skill_name: str, source: str, target: str, track: dict, track_key: str):
    dst.parent.mkdir(parents=True, exist_ok=True)
    _remove_stale_copies(kind, skill_name, _track_scope_is_global(track_key), keep=dst)
    if kind == "skill":
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    _set_tracked_record(track, track_key, skill_name, source, target, kind=kind)


def _find_skill_in_source(config: dict, skill_name: str) -> bool:
    for group in config.get("groups", {}).values():
        for skill_ref in _group_skill_refs(group):
            if skill_ref["name"] == skill_name:
                return True
    return False


def _find_agent_in_source(config: dict, agent_name: str) -> bool:
    for group in config.get("groups", {}).values():
        for agent_ref in _group_agent_refs(group):
            if agent_ref["name"] == agent_name:
                return True
    return False


def _sync_tracked_skills(source_filter: str | None = None, include_project: bool = True) -> tuple[int, int]:
    reg = _load_registry()
    track = _load_install_track()
    scopes = [("global", True)]
    if include_project:
        scopes.append((str(Path.cwd()), False))

    synced = 0
    total = 0
    config_cache: dict[str, tuple[dict, Path, Path]] = {}

    def discover_scope_skills(track_key: str, global_install: bool) -> dict[str, str]:
        discovered = {}
        for skill_name, raw_record in track.get(track_key, {}).items():
            if skill_name.startswith("agent:"):
                continue
            record = raw_record if isinstance(raw_record, dict) else {"source": raw_record}
            source = record.get("source", "")
            if source and (not source_filter or source == source_filter):
                discovered[skill_name] = source

        sources = [source_filter] if source_filter else list(reg.keys())
        for source in sources:
            if not source or source not in reg:
                continue
            config, _skills_dir, _agents_dir = config_cache.setdefault(source, _load_source_config(source))
            for skill_ref in _iter_source_skill_refs(config):
                skill_name = skill_ref["name"]
                target = _resolve_skill_target(config, skill_ref)
                installed_path = _target_artifact_path("skill", target, global_install, skill_name) / "SKILL.md"
                if not installed_path.exists() or skill_name in discovered:
                    continue
                discovered[skill_name] = source
        return discovered

    for track_key, global_install in scopes:
        candidates = discover_scope_skills(track_key, global_install)
        for skill_name, source in candidates.items():
            if source not in reg:
                print(f"  ⚠️  {skill_name} — 源 [{source}] 不在 registry 中，跳过")
                continue

            if source not in config_cache:
                config_cache[source] = _load_source_config(source)
            config, skills_dir, _agents_dir = config_cache[source]

            if not _find_skill_in_source(config, skill_name):
                print(f"  ⚠️  {skill_name} — 源 [{source}] 当前配置里不存在，跳过")
                continue

            src = skills_dir / skill_name
            if not src.exists() or not (src / "SKILL.md").exists():
                print(f"  ⚠️  {skill_name} — 源文件不存在，跳过")
                continue

            target = _resolve_skill_target(config, {"name": skill_name})
            dst = _target_artifact_path("skill", target, global_install, skill_name)
            dst.parent.mkdir(parents=True, exist_ok=True)
            total += 1

            if dst.exists() and _artifact_digest("skill", src) == _artifact_digest("skill", dst):
                _remove_stale_copies("skill", skill_name, global_install, keep=dst)
                _set_tracked_record(track, track_key, skill_name, source, target, kind="skill")
                print(f"  ✅ {skill_name} [{target}] — 已是最新")
                synced += 1
                continue

            if dst.exists():
                shutil.rmtree(dst)
                print(f"  🔄 {skill_name} [{target}] — 更新")
            else:
                print(f"  ✅ {skill_name} [{target}] — 同步")

            _install_artifact_copy("skill", src, dst, skill_name, source, target, track, track_key)
            synced += 1

    _save_install_track(track)
    return synced, total


def _sync_tracked_agents(source_filter: str | None = None, include_project: bool = True) -> tuple[int, int]:
    reg = _load_registry()
    track = _load_install_track()
    scopes = [("global", True)]
    if include_project:
        scopes.append((str(Path.cwd()), False))

    synced = 0
    total = 0
    config_cache: dict[str, tuple[dict, Path, Path]] = {}

    def discover_scope_agents(track_key: str, global_install: bool) -> dict[str, str]:
        discovered = {}
        for item_name, raw_record in track.get(track_key, {}).items():
            if item_name.startswith("agent:"):
                record = raw_record if isinstance(raw_record, dict) else {"source": raw_record}
                source = record.get("source", "")
                if source and (not source_filter or source == source_filter):
                    discovered[item_name.removeprefix("agent:")] = source

        sources = [source_filter] if source_filter else list(reg.keys())
        for source in sources:
            if not source or source not in reg:
                continue
            config, _skills_dir, _agents_dir = config_cache.setdefault(source, _load_source_config(source))
            for agent_ref in _iter_source_agent_refs(config):
                agent_name = agent_ref["name"]
                target = _resolve_agent_target(config, agent_ref)
                installed_path = _target_artifact_path("agent", target, global_install, agent_name)
                if not installed_path.exists() or agent_name in discovered:
                    continue
                discovered[agent_name] = source
        return discovered

    for track_key, global_install in scopes:
        candidates = discover_scope_agents(track_key, global_install)
        for agent_name, source in candidates.items():
            if source not in reg:
                print(f"  ⚠️  {agent_name} — 源 [{source}] 不在 registry 中，跳过")
                continue

            if source not in config_cache:
                config_cache[source] = _load_source_config(source)
            config, _skills_dir, agents_dir = config_cache[source]

            if not _find_agent_in_source(config, agent_name):
                print(f"  ⚠️  {agent_name} — 源 [{source}] 当前配置里不存在，跳过")
                continue

            src = agents_dir / f"{agent_name}.toml"
            if not src.exists():
                print(f"  ⚠️  {agent_name} — 源文件不存在，跳过")
                continue

            target = _resolve_agent_target(config, {"name": agent_name})
            dst = _target_artifact_path("agent", target, global_install, agent_name)
            dst.parent.mkdir(parents=True, exist_ok=True)
            total += 1

            if dst.exists() and _artifact_digest("agent", src) == _artifact_digest("agent", dst):
                _remove_stale_copies("agent", agent_name, global_install, keep=dst)
                _set_tracked_record(track, track_key, agent_name, source, target, kind="agent")
                print(f"  ✅ {agent_name} [agent:{target}] — 已是最新")
                synced += 1
                continue

            if dst.exists():
                dst.unlink()
                print(f"  🔄 {agent_name} [agent:{target}] — 更新")
            else:
                print(f"  ✅ {agent_name} [agent:{target}] — 同步")

            _install_artifact_copy("agent", src, dst, agent_name, source, target, track, track_key)
            synced += 1

    _save_install_track(track)
    return synced, total


# ── Commands ──────────────────────────────────────────────────────────────────


def cmd_add(args):
    url = args.url
    name = args.name or _source_name_from_url(url)
    reg = _load_registry()

    _clone_or_pull(url, name)

    reg[name] = {"url": url}
    _save_registry(reg)

    # 验证 skills.yaml 存在
    config_file = CACHE_DIR / name / "skills.yaml"
    if not config_file.exists():
        print(f"  ⚠️  仓库中没有 skills.yaml，安装时可能出错")
    else:
        with open(config_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        groups = config.get("groups", {})
        total_skills = sum(len(g.get("skills", [])) for g in groups.values())
        total_agents = sum(len(g.get("agents", [])) for g in groups.values())
        print(f"  ✅ 已添加源 [{name}]: {len(groups)} 个分组, {total_skills} 个 skills, {total_agents} 个 agents")


def cmd_list(args):
    reg = _load_registry()

    if not reg:
        print("\n还没有添加任何源。用 skill-cli add <git-url> 添加。\n")
        return

    sources = [args.source] if args.source else list(reg.keys())

    for name in sources:
        if name not in reg:
            print(f"❌ 未知源: {name}")
            continue

        source_dir = CACHE_DIR / name
        if not source_dir.exists():
            print(f"  ⚠️  [{name}] 缓存不存在，运行 skill-cli update {name}")
            continue

        config, skills_dir, agents_dir = _load_source_config(name)
        groups = config.get("groups", {})

        print(f"\n📦 [{name}] ({reg[name]['url']})")
        print(f"   共 {len(groups)} 个分组\n")

        for gname, group in groups.items():
            desc = group.get("description", "")
            skill_refs = _group_skill_refs(group)
            agent_refs = _group_agent_refs(group)
            print(f"  [{gname}] {desc} ({len(skill_refs) + len(agent_refs)} 个)")
            for skill_ref in skill_refs:
                s = skill_ref["name"]
                target = _resolve_skill_target(config, skill_ref)
                exists = "✓" if (skills_dir / s / "SKILL.md").exists() else "✗ 缺失"
                print(f"    - {s} [{target}]  {exists}")
            for agent_ref in agent_refs:
                a = agent_ref["name"]
                target = _resolve_agent_target(config, agent_ref)
                exists = "✓" if (agents_dir / f"{a}.toml").exists() else "✗ 缺失"
                print(f"    - {a} [agent:{target}]  {exists}")
            print()


def cmd_install(args):
    reg = _load_registry()
    source = args.source
    group_name = args.group

    if source not in reg:
        print(f"❌ 未知源: {source}，先用 skill-cli add <url> 添加")
        sys.exit(1)

    config, skills_dir, agents_dir = _load_source_config(source)
    groups = config.get("groups", {})

    if group_name not in groups:
        print(f"❌ 源 [{source}] 中没有分组: {group_name}")
        print(f"   可用: {', '.join(groups.keys())}")
        sys.exit(1)

    skill_refs = _group_skill_refs(groups[group_name])
    agent_refs = _group_agent_refs(groups[group_name])

    scope = "全局" if args.g else f"项目 ({Path.cwd()})"
    print(f"\n📥 [{source}] 安装分组 [{group_name}] → {scope}")
    print(f"   包含 {len(skill_refs)} 个 skills, {len(agent_refs)} 个 agents\n")

    track = _load_install_track()
    tk = _track_key(args.g)
    if tk not in track:
        track[tk] = {}

    installed = 0
    for skill_ref in skill_refs:
        skill_name = skill_ref["name"]
        target = _resolve_skill_target(config, skill_ref)
        src = skills_dir / skill_name
        dst = _get_target_dir(target, args.g) / skill_name

        if not src.exists() or not (src / "SKILL.md").exists():
            print(f"  ⚠️  {skill_name} — 源文件不存在，跳过")
            continue

        # 冲突检测：已被其他源安装
        existing_source = _tracked_source(track, tk, skill_name)
        if existing_source and existing_source != source:
            print(f"  ⚠️  {skill_name} — 冲突！已由 [{existing_source}] 安装")
            answer = input(f"     覆盖为 [{source}] 的版本？(y/N): ").strip().lower()
            if answer != "y":
                print(f"     跳过")
                continue
            _remove_stale_copies("skill", skill_name, args.g)
        elif dst.exists():
            if _skill_dir_digest(src) == _skill_dir_digest(dst):
                print(f"  ✅ {skill_name} [{target}] — 已是最新")
                _set_tracked_record(track, tk, skill_name, source, target, kind="skill")
                _remove_stale_copies("skill", skill_name, args.g, keep=dst)
                installed += 1
                continue
            else:
                print(f"  🔄 {skill_name} [{target}] — 更新")
                shutil.rmtree(dst)

        _install_artifact_copy("skill", src, dst, skill_name, source, target, track, tk)
        print(f"  ✅ {skill_name} [{target}] — 已安装")
        installed += 1

    for agent_ref in agent_refs:
        agent_name = agent_ref["name"]
        target = _resolve_agent_target(config, agent_ref)
        src = agents_dir / f"{agent_name}.toml"
        dst = _target_artifact_path("agent", target, args.g, agent_name)

        if not src.exists():
            print(f"  ⚠️  {agent_name} — 源文件不存在，跳过")
            continue

        existing_source = _tracked_source(track, tk, _track_item_name("agent", agent_name))
        if existing_source and existing_source != source:
            print(f"  ⚠️  {agent_name} — 冲突！已由 [{existing_source}] 安装")
            answer = input(f"     覆盖为 [{source}] 的版本？(y/N): ").strip().lower()
            if answer != "y":
                print(f"     跳过")
                continue
            _remove_stale_copies("agent", agent_name, args.g)
        elif dst.exists():
            if _artifact_digest("agent", src) == _artifact_digest("agent", dst):
                print(f"  ✅ {agent_name} [agent:{target}] — 已是最新")
                _set_tracked_record(track, tk, agent_name, source, target, kind="agent")
                _remove_stale_copies("agent", agent_name, args.g, keep=dst)
                installed += 1
                continue
            else:
                print(f"  🔄 {agent_name} [agent:{target}] — 更新")
                dst.unlink()

        _install_artifact_copy("agent", src, dst, agent_name, source, target, track, tk)
        print(f"  ✅ {agent_name} [agent:{target}] — 已安装")
        installed += 1

    _save_install_track(track)
    print(f"\n完成: {installed}/{len(skill_refs) + len(agent_refs)}\n")


def cmd_uninstall(args):
    reg = _load_registry()
    source = args.source
    group_name = args.group

    if source not in reg:
        print(f"❌ 未知源: {source}")
        sys.exit(1)

    config, _, _ = _load_source_config(source)
    groups = config.get("groups", {})

    if group_name not in groups:
        print(f"❌ 未知分组: {group_name}")
        sys.exit(1)

    skill_refs = _group_skill_refs(groups[group_name])
    agent_refs = _group_agent_refs(groups[group_name])

    scope = "全局" if args.g else "项目"
    print(f"\n🗑️  [{source}] 卸载分组 [{group_name}] ← {scope}\n")

    track = _load_install_track()
    tk = _track_key(args.g)

    removed = 0
    for skill_ref in skill_refs:
        skill_name = skill_ref["name"]
        removed_this = False
        for dst in _alternate_target_paths("skill", skill_name, args.g):
            if dst.exists():
                shutil.rmtree(dst)
                removed_this = True
        if removed_this:
            print(f"  ✅ {skill_name} — 已删除")
            removed += 1
            if tk in track:
                track[tk].pop(skill_name, None)
        else:
            print(f"  ⏭️  {skill_name} — 未安装")

    for agent_ref in agent_refs:
        agent_name = agent_ref["name"]
        removed_this = False
        for dst in _alternate_target_paths("agent", agent_name, args.g):
            if dst.exists():
                dst.unlink()
                removed_this = True
        if removed_this:
            print(f"  ✅ {agent_name} — 已删除")
            removed += 1
            if tk in track:
                track[tk].pop(_track_item_name("agent", agent_name), None)
        else:
            print(f"  ⏭️  {agent_name} — 未安装")

    _save_install_track(track)
    print(f"\n完成: 删除了 {removed} 个\n")


def cmd_update(args):
    reg = _load_registry()
    sources = [args.source] if args.source else list(reg.keys())

    for name in sources:
        if name not in reg:
            print(f"❌ 未知源: {name}")
            continue
        _clone_or_pull(reg[name]["url"], name)
        print(f"  ✅ [{name}] 已更新")


def cmd_sync(args):
    reg = _load_registry()
    if args.source and args.source not in reg:
        print(f"❌ 未知源: {args.source}")
        sys.exit(1)

    scope_text = "全局 + 当前项目" if not args.global_only else "仅全局"
    print(f"\n🔄 同步已安装 skills ({scope_text})\n")
    synced_skills, total_skills = _sync_tracked_skills(source_filter=args.source, include_project=not args.global_only)
    synced_agents, total_agents = _sync_tracked_agents(source_filter=args.source, include_project=not args.global_only)
    print(f"\n完成: {synced_skills + synced_agents}/{total_skills + total_agents}\n")


def cmd_remove(args):
    reg = _load_registry()
    name = args.source

    if name not in reg:
        print(f"❌ 未知源: {name}")
        sys.exit(1)

    dest = CACHE_DIR / name
    if dest.exists():
        shutil.rmtree(dest)

    del reg[name]
    _save_registry(reg)
    print(f"✅ 已删除源 [{name}]")


def cmd_sync(args):
    """同步某个组到最新：先 git pull 更新源，再重新安装该组 skills"""
    reg = _load_registry()
    source = args.source
    group_name = args.group

    if source not in reg:
        print(f"❌ 未知源: {source}，先用 skill-cli add <url> 添加")
        sys.exit(1)

    # Step 1: git pull 更新源
    print(f"\n🔄 同步 [{source}] / [{group_name}]")
    _clone_or_pull(reg[source]["url"], source)

    # Step 2: 加载最新的 skills.yaml
    config, skills_dir = _load_source_config(source)
    groups = config.get("groups", {})

    if group_name not in groups:
        print(f"❌ 源 [{source}] 中没有分组: {group_name}")
        print(f"   可用: {', '.join(groups.keys())}")
        sys.exit(1)

    skills = groups[group_name].get("skills", [])
    target = _get_target_dir(args.g)
    target.mkdir(parents=True, exist_ok=True)

    scope = "全局 (~/.claude/skills/)" if args.g else f"项目 ({target})"
    print(f"  → {scope}")
    print(f"  包含 {len(skills)} 个 skills\n")

    track = _load_install_track()
    tk = _track_key(args.g)
    if tk not in track:
        track[tk] = {}

    updated = 0
    unchanged = 0
    for skill_name in skills:
        src = skills_dir / skill_name
        dst = target / skill_name

        if not src.exists() or not (src / "SKILL.md").exists():
            print(f"  ⚠️  {skill_name} — 源文件不存在，跳过")
            continue

        if dst.exists():
            src_content = (src / "SKILL.md").read_text(encoding="utf-8")
            dst_content = (dst / "SKILL.md").read_text(encoding="utf-8") if (dst / "SKILL.md").exists() else ""
            if src_content == dst_content:
                unchanged += 1
                continue
            else:
                shutil.rmtree(dst)
                shutil.copytree(src, dst)
                track[tk][skill_name] = source
                print(f"  🔄 {skill_name} — 已更新")
                updated += 1
        else:
            shutil.copytree(src, dst)
            track[tk][skill_name] = source
            print(f"  ✅ {skill_name} — 新安装")
            updated += 1

    _save_install_track(track)
    print(f"\n完成: {updated} 个更新, {unchanged} 个已是最新\n")


def cmd_status(args):
    reg = _load_registry()
    track = _load_install_track()
    claude_project_skills = Path.cwd() / ".claude" / "skills"
    codex_project_skills = Path.cwd() / ".codex" / "skills"
    claude_project_agents = Path.cwd() / ".claude" / "agents"
    codex_project_agents = Path.cwd() / ".codex" / "agents"

    print(f"\n📊 安装状态")
    print(f"  Claude 全局: {CLAUDE_USER_SKILLS}")
    print(f"  Codex  全局: {CODEX_USER_SKILLS}")
    print(f"  Claude Agents 全局: {CLAUDE_USER_AGENTS}")
    print(f"  Codex  Agents 全局: {CODEX_USER_AGENTS}")
    print(f"  Claude 项目: {claude_project_skills}")
    print(f"  Codex  项目: {codex_project_skills}")
    print(f"  Claude Agents 项目: {claude_project_agents}")
    print(f"  Codex  Agents 项目: {codex_project_agents}\n")

    if not reg:
        print("  还没有添加任何源。\n")
        return

    for name in reg:
        source_dir = CACHE_DIR / name
        if not source_dir.exists():
            print(f"  [{name}] ⚠️ 缓存不存在")
            continue

        config_file = source_dir / "skills.yaml"
        if not config_file.exists():
            continue

        with open(config_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        groups = config.get("groups", {})
        print(f"  [{name}]")

        for gname, group in groups.items():
            desc = group.get("description", "")
            skill_refs = _group_skill_refs(group)
            agent_refs = _group_agent_refs(group)
            print(f"    [{gname}] {desc}")
            for skill_ref in skill_refs:
                s = skill_ref["name"]
                target = _resolve_skill_target(config, skill_ref)
                global_root = _get_target_dir(target, True, kind="skill")
                project_root = _get_target_dir(target, False, kind="skill")
                g_ok = (global_root / s / "SKILL.md").exists()
                p_ok = (project_root / s / "SKILL.md").exists()
                # 来源追踪
                g_src = _tracked_source(track, "global", s)
                p_src = _tracked_source(track, str(Path.cwd()), s)
                if g_ok and p_ok:
                    st = f"🌐+📁 (全局←{g_src}, 项目←{p_src})" if g_src or p_src else "🌐+📁"
                elif g_ok:
                    st = f"🌐 全局 (←{g_src})" if g_src else "🌐 全局"
                elif p_ok:
                    st = f"📁 项目 (←{p_src})" if p_src else "📁 项目"
                else:
                    st = "—"
                print(f"      {s} [{target}]: {st}")
            for agent_ref in agent_refs:
                a = agent_ref["name"]
                target = _resolve_agent_target(config, agent_ref)
                g_ok = _target_artifact_path("agent", target, True, a).exists()
                p_ok = _target_artifact_path("agent", target, False, a).exists()
                g_src = _tracked_source(track, "global", _track_item_name("agent", a))
                p_src = _tracked_source(track, str(Path.cwd()), _track_item_name("agent", a))
                if g_ok and p_ok:
                    st = f"🌐+📁 (全局←{g_src}, 项目←{p_src})" if g_src or p_src else "🌐+📁"
                elif g_ok:
                    st = f"🌐 全局 (←{g_src})" if g_src else "🌐 全局"
                elif p_ok:
                    st = f"📁 项目 (←{p_src})" if p_src else "📁 项目"
                else:
                    st = "—"
                print(f"      {a} [agent:{target}]: {st}")
        print()


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(prog="skill-cli", description="从 Git 仓库按组安装 Claude Code / Codex Skills")
    sub = parser.add_subparsers(dest="command")

    p_add = sub.add_parser("add", help="添加 skill 仓库源")
    p_add.add_argument("url", help="Git 仓库地址")
    p_add.add_argument("-n", "--name", help="自定义源名称（默认取仓库名）")

    p_list = sub.add_parser("list", help="列出分组")
    p_list.add_argument("source", nargs="?", help="指定源名称")

    p_install = sub.add_parser("install", help="安装一组 skills")
    p_install.add_argument("source", help="源名称")
    p_install.add_argument("group", help="分组名称")
    p_install.add_argument("-g", action="store_true", help="安装到全局")

    p_uninstall = sub.add_parser("uninstall", help="卸载一组 skills")
    p_uninstall.add_argument("source", help="源名称")
    p_uninstall.add_argument("group", help="分组名称")
    p_uninstall.add_argument("-g", action="store_true", help="从全局卸载")

    p_update = sub.add_parser("update", help="更新源")
    p_update.add_argument("source", nargs="?", help="指定源（不填更新所有）")

    p_sync = sub.add_parser("sync", help="重同步已安装 skills 到目标目录")
    p_sync.add_argument("source", nargs="?", help="指定源（不填同步所有）")
    p_sync.add_argument("--global-only", action="store_true", help="只同步全局安装")

    p_remove = sub.add_parser("remove", help="删除源")
    p_remove.add_argument("source", help="源名称")

    sub.add_parser("status", help="查看安装状态")

    args = parser.parse_args()
    cmds = {
        "add": cmd_add, "list": cmd_list, "install": cmd_install,
        "uninstall": cmd_uninstall, "update": cmd_update,
        "remove": cmd_remove, "sync": cmd_sync, "status": cmd_status,
    }

    if args.command in cmds:
        cmds[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
