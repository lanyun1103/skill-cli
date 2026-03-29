# skill-cli

从 Git 仓库按组安装 Claude Code Skills。一个仓库管理所有 Skills，按场景分组，安装时选组装到全局或项目。

## 安装

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/lanyun1103/skill-cli/main/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/lanyun1103/skill-cli/main/install.ps1 | iex
```

**手动安装 (需要 Python 3.10+):**

```bash
git clone https://github.com/lanyun1103/skill-cli.git
cd skill-cli
pip install .
```

## 用法

```bash
# 添加一个 skill 仓库
skill-cli add https://github.com/xxx/my-skills

# 查看有哪些分组
skill-cli list

# 安装一组 skills 到当前项目
skill-cli install my-skills common

# 安装到全局（所有项目可用）
skill-cli install my-skills common -g

# 查看安装状态
skill-cli status

# 更新所有源
skill-cli update

# 卸载
skill-cli uninstall my-skills common -g

# 删除源
skill-cli remove my-skills
```

## Skill 仓库格式

任何 Git 仓库只需包含两个东西：

```
my-skills/
├── skills.yaml       # 分组定义
└── skills/
    ├── skill-a/
    │   └── SKILL.md
    ├── skill-b/
    │   └── SKILL.md
    └── skill-c/
        └── SKILL.md
```

`skills.yaml` 示例：

```yaml
groups:
  common:
    description: 通用工具
    skills:
      - skill-a
      - skill-b

  java:
    description: Java 项目工具集
    skills:
      - skill-b
      - skill-c
```

同一个 skill 可以属于多个分组。

## 安装位置

| 参数 | 位置 | 作用范围 |
|------|------|---------|
| (默认) | `.claude/skills/` (当前目录) | 仅当前项目 |
| `-g` | `~/.claude/skills/` | 所有项目 |

## License

MIT
