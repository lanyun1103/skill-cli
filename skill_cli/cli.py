#!/usr/bin/env python3
"""skill-cli: 从 Git 仓库按组安装 Claude Code Skills

用法:
    skill-cli add <git-url>                     添加一个 skill 仓库源
    skill-cli list [<source>]                   列出某个源（或所有源）的分组
    skill-cli install <source> <group>          安装一组 skills 到当前项目
    skill-cli install <source> <group> -g       安装一组 skills 到用户全局
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
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

CACHE_DIR = Path.home() / ".skill-cli" / "sources"
REGISTRY_FILE = Path.home() / ".skill-cli" / "registry.json"
INSTALL_TRACK_FILE = Path.home() / ".skill-cli" / "installed.json"
USER_SKILLS = Path.home() / ".claude" / "skills"


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


def _source_name_from_url(url: str) -> str:
    """从 git URL 提取名称: github.com/user/repo → repo"""
    name = url.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


def _clone_or_pull(url: str, name: str) -> Path:
    dest = CACHE_DIR / name
    if dest.exists():
        print(f"  🔄 更新 {name}...")
        subprocess.run(["git", "-C", str(dest), "pull", "--ff-only", "-q"], check=True)
    else:
        print(f"  📥 克隆 {name}...")
        subprocess.run(["git", "clone", "-q", url, str(dest)], check=True)
    return dest


def _load_source_config(name: str) -> tuple[dict, Path]:
    """加载某个源的 skills.yaml 和 skills 目录路径"""
    source_dir = CACHE_DIR / name
    config_file = source_dir / "skills.yaml"
    if not config_file.exists():
        print(f"❌ 源 {name} 中没有 skills.yaml")
        sys.exit(1)
    with open(config_file, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config, source_dir / "skills"


def _get_target_dir(global_install: bool) -> Path:
    if global_install:
        return USER_SKILLS
    return Path.cwd() / ".claude" / "skills"


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
        print(f"  ✅ 已添加源 [{name}]: {len(groups)} 个分组, {total_skills} 个 skills")


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

        config, skills_dir = _load_source_config(name)
        groups = config.get("groups", {})

        print(f"\n📦 [{name}] ({reg[name]['url']})")
        print(f"   共 {len(groups)} 个分组\n")

        for gname, group in groups.items():
            desc = group.get("description", "")
            skills = group.get("skills", [])
            print(f"  [{gname}] {desc} ({len(skills)} 个)")
            for s in skills:
                exists = "✓" if (skills_dir / s / "SKILL.md").exists() else "✗ 缺失"
                print(f"    - {s}  {exists}")
            print()


def cmd_install(args):
    reg = _load_registry()
    source = args.source
    group_name = args.group

    if source not in reg:
        print(f"❌ 未知源: {source}，先用 skill-cli add <url> 添加")
        sys.exit(1)

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
    print(f"\n📥 [{source}] 安装分组 [{group_name}] → {scope}")
    print(f"   包含 {len(skills)} 个 skills\n")

    track = _load_install_track()
    tk = _track_key(args.g)
    if tk not in track:
        track[tk] = {}

    installed = 0
    for skill_name in skills:
        src = skills_dir / skill_name
        dst = target / skill_name

        if not src.exists() or not (src / "SKILL.md").exists():
            print(f"  ⚠️  {skill_name} — 源文件不存在，跳过")
            continue

        # 冲突检测：已被其他源安装
        existing_source = track[tk].get(skill_name)
        if existing_source and existing_source != source:
            print(f"  ⚠️  {skill_name} — 冲突！已由 [{existing_source}] 安装")
            answer = input(f"     覆盖为 [{source}] 的版本？(y/N): ").strip().lower()
            if answer != "y":
                print(f"     跳过")
                continue
            shutil.rmtree(dst, ignore_errors=True)
        elif dst.exists():
            src_content = (src / "SKILL.md").read_text(encoding="utf-8")
            dst_content = (dst / "SKILL.md").read_text(encoding="utf-8") if (dst / "SKILL.md").exists() else ""
            if src_content == dst_content:
                print(f"  ✅ {skill_name} — 已是最新")
                track[tk][skill_name] = source
                installed += 1
                continue
            else:
                print(f"  🔄 {skill_name} — 更新")
                shutil.rmtree(dst)

        shutil.copytree(src, dst)
        track[tk][skill_name] = source
        print(f"  ✅ {skill_name} — 已安装")
        installed += 1

    _save_install_track(track)
    print(f"\n完成: {installed}/{len(skills)}\n")


def cmd_uninstall(args):
    reg = _load_registry()
    source = args.source
    group_name = args.group

    if source not in reg:
        print(f"❌ 未知源: {source}")
        sys.exit(1)

    config, _ = _load_source_config(source)
    groups = config.get("groups", {})

    if group_name not in groups:
        print(f"❌ 未知分组: {group_name}")
        sys.exit(1)

    skills = groups[group_name].get("skills", [])
    target = _get_target_dir(args.g)

    scope = "全局" if args.g else "项目"
    print(f"\n🗑️  [{source}] 卸载分组 [{group_name}] ← {scope}\n")

    track = _load_install_track()
    tk = _track_key(args.g)

    removed = 0
    for skill_name in skills:
        dst = target / skill_name
        if dst.exists():
            shutil.rmtree(dst)
            print(f"  ✅ {skill_name} — 已删除")
            removed += 1
            if tk in track:
                track[tk].pop(skill_name, None)
        else:
            print(f"  ⏭️  {skill_name} — 未安装")

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
    project_skills = Path.cwd() / ".claude" / "skills"

    print(f"\n📊 安装状态")
    print(f"  全局: {USER_SKILLS}")
    print(f"  项目: {project_skills}\n")

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
            skills = group.get("skills", [])
            print(f"    [{gname}] {desc}")
            for s in skills:
                g_ok = (USER_SKILLS / s / "SKILL.md").exists()
                p_ok = (project_skills / s / "SKILL.md").exists()
                # 来源追踪
                g_src = track.get("global", {}).get(s, "")
                p_src = track.get(str(Path.cwd()), {}).get(s, "")
                if g_ok and p_ok:
                    st = f"🌐+📁 (全局←{g_src}, 项目←{p_src})" if g_src or p_src else "🌐+📁"
                elif g_ok:
                    st = f"🌐 全局 (←{g_src})" if g_src else "🌐 全局"
                elif p_ok:
                    st = f"📁 项目 (←{p_src})" if p_src else "📁 项目"
                else:
                    st = "—"
                print(f"      {s}: {st}")
        print()


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(prog="skill-cli", description="从 Git 仓库按组安装 Claude Code Skills")
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

    p_remove = sub.add_parser("remove", help="删除源")
    p_remove.add_argument("source", help="源名称")

    p_sync = sub.add_parser("sync", help="同步某组到最新（pull + 重装）")
    p_sync.add_argument("source", help="源名称")
    p_sync.add_argument("group", help="分组名称")
    p_sync.add_argument("-g", action="store_true", help="同步到全局")

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
