"""CC-Toolbox 配置"""
import os
from pathlib import Path
from typing import List

# ---------- 数据源路径 ----------
# ~/.claude 目录
CLAUDE_BASE = Path.home() / ".claude"

# MCP 配置
CLAUDE_MCP_CONFIG = Path.home() / ".claude.json"

# Skill 扫描路径（默认仅官方目录；自定义路径存 paths_config.json，运行时合并）
SKILL_PATHS: List[Path] = [
    CLAUDE_BASE / "skills",
]

# CLI 扫描路径（默认为空；自定义路径存 paths_config.json，运行时合并。
# scan_all 仍会补扫每个路径下的 node_modules/.bin 与 bin 子目录）
CLI_PATHS: List[Path] = []

# ---------- 服务器配置 ----------
HOST = os.environ.get("CC_TOOLBOX_HOST", "127.0.0.1")
PORT = int(os.environ.get("CC_TOOLBOX_PORT", "0") or "0")  # 0=自动探测
PREFERRED_PORT = 8765
DEBUG = False


def find_free_port(host: str, preferred: int) -> int:
    """从 preferred 起探测可用端口（含 preferred），全部占用则抛 RuntimeError。"""
    import socket
    for port in range(preferred, preferred + 101):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"{host} 的 {preferred}-{preferred+100} 端口段全部被占用")

# ---------- 缓存 ----------
CACHE_TTL = 120  # 秒

# ---------- 跳过 CLI 工具 ----------
# 不含 node/npm/npx/pip/python/git：它们在 desc_cache._KNOWN_DETAILED 里有预定义
# 中文描述（cli:: 前缀），排除会让「用户可见工具 + 描述可用」双双失效（#4 决策：
# 保留描述、从 SKIP 移除）；python3 及 shell 内置命令仍跳过
SKIP_CLI_TOOLS = {
    "python3",
    "curl", "ls", "cd", "dir", "copy", "move",
    "del", "rm", "mkdir", "echo", "cat", "type",
}

# ---------- MCP 已知描述映射 ----------
KNOWN_MCP_DESCRIPTIONS = {
    "filesystem": "安全的文件系统操作 — 读写文件、目录遍历",
    "playwright": "浏览器自动化 — 页面截图、交互、抓取",
    "github": "GitHub API 集成 — 仓库、Issue、PR 管理",
    "mcp-video": "视频编辑 — 剪辑、转码、合成、添加特效",
    "fetch": "HTTP 请求工具 — 获取网页内容",
    "memory": "持久化记忆 — 跨会话存储和检索信息",
    "puppeteer": "浏览器自动化 — 无头浏览器操作",
    "sqlite": "SQLite 数据库操作 — 查询和管理",
    "redis": "Redis 缓存操作 — 键值存储管理",
    "postgres": "PostgreSQL 数据库操作",
}

# ---------- Hook 事件描述 ----------
# 官方 Claude Code hook 事件全集 = settings.json 里 hooks 记录键的合法枚举，
# 取自本机 Claude Code 2.1.150 内置 schema（settings: hooks: h.record(h.enum(W95), ...)）
HOOK_EVENTS = [
    "PreToolUse", "PostToolUse", "PostToolUseFailure", "PostToolBatch",
    "Notification", "UserPromptSubmit", "UserPromptExpansion",
    "SessionStart", "SessionEnd", "Stop", "StopFailure",
    "SubagentStart", "SubagentStop", "PreCompact", "PostCompact",
    "PermissionRequest", "PermissionDenied", "Setup",
    "TeammateIdle", "TaskCreated", "TaskCompleted",
    "Elicitation", "ElicitationResult", "ConfigChange",
    "WorktreeCreate", "WorktreeRemove", "InstructionsLoaded",
    "CwdChanged", "FileChanged",
]
HOOK_EVENT_DESCRIPTIONS = {e: f"{e} 事件触发" for e in HOOK_EVENTS}
