"""fake_env 隔离完整性测试：全部扫描器与 /api/export 只返回 tmp 造的数据"""
import json


def _seed_minimal_tools(fake_env):
    """在隔离环境里造最小数据集：1 skill + 1 mcp + 1 command + 1 plugin。"""
    # skill：目录 + SKILL.md
    skill_dir = fake_env.base / "skills" / "demo-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: 隔离测试技能\n---\n\n正文\n",
        encoding="utf-8",
    )

    # mcp：全局 .claude.json 的 mcpServers
    (fake_env.tmp / ".claude.json").write_text(
        json.dumps({"mcpServers": {"demo-mcp": {"command": "echo", "args": []}}}),
        encoding="utf-8",
    )

    # command：commands/*.md
    (fake_env.base / "commands" / "demo-cmd.md").write_text(
        "# demo-cmd\n\n隔离测试命令\n",
        encoding="utf-8",
    )

    # plugin：plugins/cache/<publisher>/<name>/<version>/plugin.json（扫描器方式二）
    plugin_dir = (
        fake_env.base / "plugins" / "cache" / "demo-pub" / "demo-plugin" / "1.0.0"
    )
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({
            "name": "demo-plugin",
            "version": "1.0.0",
            "description": "隔离测试插件",
        }),
        encoding="utf-8",
    )


def test_fake_env_isolated(client, fake_env):
    """export 的 total 只统计 tmp 造的 4 个工具；7 个扫描器都不返回真实系统数据。"""
    from scanners import (
        skill_scanner,
        mcp_scanner,
        cli_scanner,
        hook_scanner,
        plugin_scanner,
        command_scanner,
        stats_scanner,
    )

    _seed_minimal_tools(fake_env)

    # ── 逐个扫描器验证（force_refresh 绕过缓存）──
    assert [s["name"] for s in skill_scanner.get_skills(force_refresh=True)] == ["demo-skill"]
    assert [m["name"] for m in mcp_scanner.get_mcp_servers(force_refresh=True)] == ["demo-mcp"]
    assert cli_scanner.get_cli_tools(force_refresh=True) == []          # CLI_PATHS 为空 + 系统 PATH 已隔离
    assert hook_scanner.get_hooks(force_refresh=True) == []             # 无 settings.json
    assert [p["name"] for p in plugin_scanner.get_plugins(force_refresh=True)] == ["demo-plugin"]
    assert [c["name"] for c in command_scanner.get_commands(force_refresh=True)] == ["demo-cmd"]
    assert stats_scanner.get_usage_stats(force_refresh=True) == {}      # 无 projects 目录

    # ── /api/export 全链路验证 ──
    resp = client.get("/api/export?format=json&refresh=1")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["total"] == 4
    assert {t["name"] for t in payload["tools"]} == {
        "demo-skill", "demo-mcp", "demo-cmd", "demo-plugin",
    }
