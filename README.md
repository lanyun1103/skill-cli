# skill-cli

从 Git 仓库按组安装 Claude Code / Codex Skills。一个仓库管理所有 Skills，按场景分组，安装时选组装到全局或项目；每个 skill 还可以声明目标平台，自动同步到不同目录。

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

# 将已安装 skill 按目标平台重同步到正确目录
skill-cli sync

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
skills:
  spec-writer:
    target: codex
  review-loop:
    target: codex
  commit:
    target: claude

groups:
  common:
    description: 通用工具
    skills:
      - commit
      - spec-writer
      - review-loop

  java:
    description: Java 项目工具集
    skills:
      - commit
      - spec-writer
```

同一个 skill 可以属于多个分组。

## Skill Target

`skills.yaml` 顶层可选 `skills` 元数据，用来声明每个 skill 的目标平台：

```yaml
skills:
  task-router:
    target: codex
  skill-cli-guide:
    target: claude
```

支持的 `target`：

- `claude`
- `codex`

也支持在组里内联覆盖：

```yaml
groups:
  common:
    description: 通用工具
    skills:
      - name: task-router
        target: codex
      - name: skill-cli-guide
        target: claude
```

未声明 `target` 时默认按 `claude` 处理，兼容现有仓库。

## 安装位置

| Target | 默认安装位置 | `-g` 全局位置 |
|--------|--------------|--------------|
| `claude` | `.claude/skills/` | `~/.claude/skills/` |
| `codex` | `.codex/skills/` | `~/.codex/skills/` |

`skill-cli sync` 会根据 `target` 将已安装 skill 重同步到正确目录，并清理同 scope 下错误平台目录中的旧副本。

## License

MIT
