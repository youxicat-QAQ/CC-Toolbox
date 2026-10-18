"""pytest 共享 fixture：隔离的 Claude 扫描环境 + Flask 测试客户端"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# 保证以顶层模块方式 import（app.py 用 `import config` / `from desc_cache import ...`）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import desc_cache
import paths_config as _paths_config
from scanners import (
    skill_scanner,
    mcp_scanner,
    cli_scanner,
    hook_scanner,
    plugin_scanner,
    command_scanner,
    stats_scanner,
)

# (扫描器模块, _cache 是否为 dict) —— stats_scanner 是 dict，其余是 list
_SCANNERS = [
    (skill_scanner, False),
    (mcp_scanner, False),
    (cli_scanner, False),
    (hook_scanner, False),
    (plugin_scanner, False),
    (command_scanner, False),
    (stats_scanner, True),
]


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    """把所有扫描路径与 desc_cache 缓存文件指到 tmp_path，并清零扫描器缓存。"""
    base = tmp_path / ".claude"
    (base / "skills").mkdir(parents=True)
    (base / "commands").mkdir(parents=True)
    (base / "plugins").mkdir(parents=True)
    (tmp_path / "cli").mkdir()

    monkeypatch.setattr(config, "CLAUDE_BASE", base)
    monkeypatch.setattr(config, "CLAUDE_MCP_CONFIG", tmp_path / ".claude.json")
    monkeypatch.setattr(config, "SKILL_PATHS", [base / "skills"])
    monkeypatch.setattr(config, "CLI_PATHS", [tmp_path / "cli"])

    # cli_scanner 的 _scan_path 硬编码读系统 PATH（limit=200），会把真实系统
    # 的 ~200 个 CLI 扫进结果 —— 指向一个值为「空目录」的环境变量：
    # 注意不能直接让读值为空串，否则 "".split(sep) == [""] → Path("") 解析成
    # 当前工作目录，会把 cwd 里的文件当 CLI 扫进来
    empty_path_dir = tmp_path / "empty-path"
    empty_path_dir.mkdir()
    monkeypatch.setenv("__CC_TOOLBOX_TEST_PATH__", str(empty_path_dir))
    monkeypatch.setattr(cli_scanner, "PATH_ENV_VAR", "__CC_TOOLBOX_TEST_PATH__")

    monkeypatch.setattr(desc_cache, "CACHE_FILE", tmp_path / "desc_cache.json")
    # 重置内存缓存，避免跨测试串数据
    monkeypatch.setattr(desc_cache, "_mem", {"data": None, "mtime_ns": -1, "size": -1})

    # AI 描述文件同样指到 tmp 并重置其内存缓存，避免读取应用目录真实文件 / 跨测试串数据
    monkeypatch.setattr(desc_cache, "AI_DESC_FILE", tmp_path / "ai_descriptions.json")
    monkeypatch.setattr(desc_cache, "_ai_mem", {"data": None, "mtime_ns": -1, "size": -1})

    # 路径配置文件指到 tmp，避免污染应用目录 / 跨测试串数据
    monkeypatch.setattr(_paths_config, "PATHS_CONFIG_FILE", tmp_path / "paths_config.json")

    # hook 的 sidecar 禁用档案指到 tmp，避免污染应用目录 / 跨测试串数据
    monkeypatch.setattr(hook_scanner, "SIDECAR_FILE", tmp_path / "hook_disabled.json")

    for mod, is_dict in _SCANNERS:
        monkeypatch.setattr(mod, "_cache", {} if is_dict else [])
        monkeypatch.setattr(mod, "_cache_time", None)

    return SimpleNamespace(base=base, tmp=tmp_path)


@pytest.fixture
def client(fake_env):
    """Flask 测试客户端（依赖 fake_env 完成路径隔离）。"""
    from app import app

    app.config["TESTING"] = True
    return app.test_client()
