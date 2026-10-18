"""批次2 扫描器修复回归测试：mcp / cli / command / skill / plugin / stats"""
import json
import os
import time

from scanners import (
    cli_scanner,
    command_scanner,
    mcp_scanner,
    plugin_scanner,
    skill_scanner,
    stats_scanner,
)


# ── MCP（#8 项目级路径 / #17 健壮性 / #11 统一响应） ──


def test_mcp_corrupt_claude_json_no_crash(fake_env):
    """损坏的 ~/.claude.json 只告警返回空，不抛异常不崩。"""
    (fake_env.tmp / ".claude.json").write_text("{not-valid-json", encoding="utf-8")
    assert mcp_scanner.get_mcp_servers(force_refresh=True) == []


def test_mcp_disabled_flag_recognized(fake_env):
    """disabled:true 识别为 enabled=False；enabled 显式生效；缺省默认启用。"""
    (fake_env.tmp / ".claude.json").write_text(json.dumps({"mcpServers": {
        "dis1": {"command": "echo", "disabled": True},
        "en1": {"command": "echo", "enabled": True},
        "def1": {"command": "echo"},
    }}), encoding="utf-8")
    by = {s["name"]: s for s in mcp_scanner.get_mcp_servers(force_refresh=True)}
    assert by["dis1"]["enabled"] is False
    assert by["en1"]["enabled"] is True
    assert by["def1"]["enabled"] is True


def test_mcp_url_type_description_nonempty(fake_env):
    """url 型 MCP 生成「URL 型 MCP 服务 — …」描述且非空。"""
    (fake_env.tmp / ".claude.json").write_text(json.dumps({"mcpServers": {
        "remote-thing": {"type": "url", "url": "https://example.com/mcp-endpoint"},
    }}), encoding="utf-8")
    by = {s["name"]: s for s in mcp_scanner.get_mcp_servers(force_refresh=True)}
    desc = by["remote-thing"]["description"]
    assert desc
    assert "URL 型 MCP 服务" in desc


def test_mcp_project_paths_from_claude_json(fake_env):
    """从 ~/.claude.json projects 键解析真实项目路径，扫 .mcp.json 两级位置。"""
    # 项目 A：.claude/.mcp.json
    proj_a = fake_env.tmp / "proj-a"
    (proj_a / ".claude").mkdir(parents=True)
    (proj_a / ".claude" / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"proj-a-mcp": {"command": "uvx", "args": ["a-mcp"]}},
    }), encoding="utf-8")
    # 项目 B：根下 .mcp.json
    proj_b = fake_env.tmp / "proj-b"
    proj_b.mkdir()
    (proj_b / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"proj-b-mcp": {"command": "npx", "args": ["b-mcp"]}},
    }), encoding="utf-8")
    # projects 键里混一个不存在的路径（解析不崩）
    (fake_env.tmp / ".claude.json").write_text(json.dumps({
        "projects": {
            str(proj_a): {"mcpServers": {}},
            str(proj_b): {},
            str(fake_env.tmp / "no-such-proj"): {},
        },
    }), encoding="utf-8")

    by = {s["name"]: s for s in mcp_scanner.get_mcp_servers(force_refresh=True)}
    assert by["proj-a-mcp"]["scope"] == "project"
    assert by["proj-a-mcp"]["project_path"] == str(proj_a)
    assert by["proj-b-mcp"]["scope"] == "project"
    assert by["proj-b-mcp"]["project_path"] == str(proj_b)


def test_mcp_test_connection_uniform_error_shape(client, fake_env):
    """test_connection 响应统一 {success, output, error}：失败时 error 非空。"""
    resp = client.post("/api/mcp/no-such-server/test")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is False
    assert "output" in data and "error" in data
    assert data["error"]


# ── CLI（#4 去重 / #14 _is_executable / #35 get_version） ──


def test_cli_parent_child_dedup(fake_env):
    """CLI_PATHS 父目录与其 node_modules/.bin 子目录同名文件只出现一次。"""
    bin_dir = fake_env.tmp / "cli" / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    (fake_env.tmp / "cli" / "foo.cmd").write_text("@echo off", encoding="utf-8")
    (bin_dir / "foo.cmd").write_text("@echo off", encoding="utf-8")

    tools = cli_scanner.scan_all()
    assert sum(1 for t in tools if t["name"] == "foo") == 1


def test_is_executable_rules():
    """后缀白名单 + 无扩展名仅认 .bin 内 npm shim，LICENSE 类文件不收。"""
    # 白名单后缀
    assert cli_scanner._is_executable("a.exe")
    assert cli_scanner._is_executable("a.cmd")
    assert cli_scanner._is_executable("a.ps1")
    # 无扩展名 + .bin 目录 → npm shim 认
    assert cli_scanner._is_executable("shimtool", parent=r"C:\x\node_modules\.bin")
    # 无扩展名 + 非 .bin 目录 → 不收
    assert not cli_scanner._is_executable("LICENSE")
    assert not cli_scanner._is_executable("README", parent=r"C:\x\cli")
    # 非白名单后缀不收
    assert not cli_scanner._is_executable("mcp.json")
    assert not cli_scanner._is_executable("pkg.zip")


def test_cli_license_not_collected_but_bin_shim_is(fake_env):
    """集成验证：cli 根下无扩展名 LICENSE 不进列表，.bin 内无扩展名 shim 进。"""
    cli_dir = fake_env.tmp / "cli"
    (cli_dir / "LICENSE").write_text("MIT", encoding="utf-8")
    bin_dir = cli_dir / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "shimtool").write_text("#!/bin/sh\n", encoding="utf-8")

    names = [t["name"] for t in cli_scanner.scan_all()]
    assert "LICENSE" not in names
    assert "shimtool" in names


def test_cli_get_version_lazy_writeback(fake_env, monkeypatch):
    """get_version：真实执行 --version，取首行 ≤40 字符，并写回缓存该条目。"""
    import sys

    monkeypatch.setattr(cli_scanner, "_cache", [{
        "name": "fakepy", "path": sys.executable, "version": None,
        "description": "", "category": "cli_path",
    }])
    monkeypatch.setattr(cli_scanner, "_cache_time", time.time())

    ver = cli_scanner.get_version("fakepy")
    assert ver and ver.startswith("Python")
    assert len(ver) <= 40
    assert cli_scanner._cache[0]["version"] == ver   # 写回成功后详情不再重跑子进程


# ── Command（#16 子目录命名空间） ──


def test_command_namespace_subdir(fake_env):
    """子目录 git/commit.md → name git:commit；顶层 commit.md → commit。"""
    git_dir = fake_env.base / "commands" / "git"
    git_dir.mkdir(parents=True)
    (git_dir / "commit.md").write_text("# 提交\n\n提交代码\n", encoding="utf-8")
    (fake_env.base / "commands" / "commit.md").write_text(
        "# 顶层命令\n\n顶层内容\n", encoding="utf-8")

    by = {c["name"]: c for c in command_scanner.get_commands(force_refresh=True)}
    assert "git:commit" in by
    assert "commit" in by
    assert by["git:commit"]["path"].endswith("commit.md")


# ── Skill（#23 frontmatter name / #13 坏项跳过） ──


def test_skill_frontmatter_name_beats_dirname(fake_env):
    """frontmatter name 非空时优先于目录名。"""
    d = fake_env.base / "skills" / "dir-name"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: fm-name\ndescription: 描述\n---\n\n正文\n", encoding="utf-8")
    skills = skill_scanner.get_skills(force_refresh=True)
    assert [s["name"] for s in skills] == ["fm-name"]


def test_skill_broken_md_skipped_no_500(client, fake_env):
    """SKILL.md 不可读（坏项）时跳过该技能，扫描与 API 均不 500。"""
    bad = fake_env.base / "skills" / "broken-skill"
    bad.mkdir()
    (bad / "SKILL.md").mkdir()          # 目录占位 → read_text 抛 OSError
    good = fake_env.base / "skills" / "good-skill"
    good.mkdir()
    (good / "SKILL.md").write_text(
        "---\nname: good\ndescription: 好技能\n---\n\n正文\n", encoding="utf-8")

    names = [s["name"] for s in skill_scanner.get_skills(force_refresh=True)]
    assert "good" in names
    assert "broken-skill" not in names

    resp = client.get("/api/skills?refresh=1")
    assert resp.status_code == 200
    assert all(t["name"] != "broken-skill" for t in resp.get_json())


# ── Plugin（#12 条目级容错 / 版本数字段排序） ──


def test_plugin_bad_entry_skips_and_continues(fake_env):
    """坏条目（非对象、installPath 缺失）逐条跳过，后续条目仍解析。"""
    plugins_dir = fake_env.base / "plugins"
    good_dir = plugins_dir / "installed" / "good-plg"
    good_dir.mkdir(parents=True)
    (good_dir / "plugin.json").write_text(
        json.dumps({"name": "good-plg", "version": "1.0.0", "description": "好"}),
        encoding="utf-8")
    (plugins_dir / "installed_plugins.json").write_text(json.dumps({
        "version": 2,
        "plugins": {
            # 字符串条目 → 非对象坏条目
            "bad@1.0.0": ["not-a-dict"],
            # installPath 缺失 → 跳过（不构造 Path("") 落到 cwd 的坑）
            "noip@1.0.0": [{"version": "1.0.0"}],
            # 正常条目在坏条目之后，必须仍被解析
            "good@1.0.0": [{"installPath": str(good_dir), "version": "1.0.0"}],
        },
    }), encoding="utf-8")

    names = [p["name"] for p in plugin_scanner.get_plugins(force_refresh=True)]
    assert "good" in names
    assert "noip" not in names
    assert "bad" not in names


def test_plugin_version_sort_numeric_tuple(fake_env):
    """"10.1.0" 与 "2.9.0" 共存时按数字段选 10.1.0（字符串排序会错选 2.9.0）。"""
    for ver in ("10.1.0", "2.9.0"):
        d = fake_env.base / "plugins" / "cache" / "pub" / "multi-plg" / ver
        d.mkdir(parents=True)
        (d / "plugin.json").write_text(
            json.dumps({"name": "multi-plg", "version": ver}), encoding="utf-8")

    multi = next(p for p in plugin_scanner.get_plugins(force_refresh=True)
                 if p["name"] == "multi-plg")
    assert multi["version"] == "10.1.0"
    assert str(multi["path"]).endswith("10.1.0")


# ── Stats（#9 mtime 排序 + 结构化提取） ──


def test_stats_mtime_desc_top20_and_no_substring(fake_env):
    """按 mtime 降序取前 20：旧文件被截断；普通文本子串不计数。"""
    proj = fake_env.base / "projects" / "demo"
    proj.mkdir(parents=True)
    now = time.time()

    # 最旧文件：结构化 tool_use（应被截断排除）+ 普通文本含 "git" 子串
    old = proj / "old.jsonl"
    old.write_text(
        json.dumps({"type": "tool_use", "name": "OldTool"}) + "\n"
        + json.dumps({"type": "message", "text": "git commit git push"}) + "\n",
        encoding="utf-8")
    os.utime(old, (now - 10000, now - 10000))

    # 19 个中间文件：普通文本含 "git" 子串（会入选但子串不计数）
    for i in range(19):
        f = proj / f"filler{i}.jsonl"
        f.write_text(json.dumps({"type": "message", "text": "git something"}) + "\n",
                     encoding="utf-8")
        os.utime(f, (now - 100, now - 100))

    # 最新文件：嵌套在 assistant 消息里的 tool_use
    new = proj / "new.jsonl"
    new.write_text(json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "NewTool", "input": {}}]},
    }) + "\n", encoding="utf-8")
    os.utime(new, (now, now))

    stats = stats_scanner.get_usage_stats(force_refresh=True)
    assert stats.get("newtool") == 1   # 最新文件入选，且嵌套 tool_use 可提取
    assert "oldtool" not in stats      # 第 21 个（最旧）文件被 mtime 降序截断排除
    assert "git" not in stats          # 整行子串匹配已删除（#9）


def test_stats_deep_nested_jsonl_skips_without_recursion_error(fake_env):
    """约 3000 层嵌套的合法 JSON 行触发 RecursionError：跳过该行，不穿透 API（#I-1）。"""
    proj = fake_env.base / "projects" / "deep"
    proj.mkdir(parents=True)
    # 合法但深嵌套（3000 层带键 dict）：json.loads 抛 RecursionError 而非 ValueError；
    # 同文件后续放正常 tool_use 行，验证是逐行跳过而非整文件丢弃
    deep_line = '{"a":' * 3000 + "1" + "}" * 3000
    (proj / "deep.jsonl").write_text(
        deep_line + "\n"
        + json.dumps({"type": "tool_use", "name": "DeepFileTool"}) + "\n",
        encoding="utf-8")
    # 同会话目录放正常文件，确认扫描整体仍工作
    (proj / "ok.jsonl").write_text(
        json.dumps({"type": "tool_use", "name": "OkTool"}) + "\n", encoding="utf-8")

    # 不应抛 RecursionError；深嵌套行被跳过，同文件后续行与正常文件仍统计
    stats = stats_scanner.get_usage_stats(force_refresh=True)
    assert stats.get("oktool") == 1
    assert stats.get("deepfiletool") == 1


# ── MCP 握手打桩测试（#I-2 / #M-4：不真起进程） ──


def _fake_init_response() -> str:
    """构造合法的 MCP initialize 响应行（id=1 且含 result）。"""
    return json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "result": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "serverInfo": {"name": "fake", "version": "1.0"}},
    })


def test_mcp_test_stdio_initialize_response_success(fake_env, monkeypatch):
    """stdout 返回含 jsonrpc 的 initialize 响应行 → success=True。"""
    class FakeProc:
        def __init__(self, *a, **k):
            self.stdout = None
            self.stderr = None

        def communicate(self, input=None, timeout=None):
            return _fake_init_response(), ""

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(mcp_scanner.subprocess, "Popen", FakeProc)
    res = mcp_scanner._test_stdio("fake-cmd", [])
    assert res["success"] is True
    assert res["error"] == ""


def test_mcp_test_stdio_timeout_then_kill_response_success(fake_env, monkeypatch):
    """首次 communicate 超时、kill 后二次返回响应 → success=True。"""
    class FakeProc:
        def __init__(self, *a, **k):
            self._calls = 0
            self.killed = False
            self.stdout = None
            self.stderr = None

        def communicate(self, input=None, timeout=None):
            self._calls += 1
            if self._calls == 1:
                raise mcp_scanner.subprocess.TimeoutExpired(cmd="fake-cmd", timeout=8)
            return _fake_init_response(), ""

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(mcp_scanner.subprocess, "Popen", FakeProc)
    res = mcp_scanner._test_stdio("fake-cmd", [])
    assert res["success"] is True
    assert res["error"] == ""


def test_mcp_test_stdio_no_initialize_response_fails(fake_env, monkeypatch):
    """输出无 initialize 响应（裸文本/含 jsonrpc 字样但非合法响应）→ success=False 且 error 非空。"""
    class FakeProc:
        def __init__(self, *a, **k):
            self.stdout = None
            self.stderr = None

        def communicate(self, input=None, timeout=None):
            # 无 jsonrpc：纯噪声输出
            return "hello world\nnot json at all", "connection refused"

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(mcp_scanner.subprocess, "Popen", FakeProc)
    res = mcp_scanner._test_stdio("fake-cmd", [])
    assert res["success"] is False
    assert res["error"]


def test_mcp_test_url_head_405_counts_reachable(fake_env, monkeypatch):
    """HEAD 探测抛 HTTPError(405)（服务可达但不支持 HEAD）→ success=True。"""
    import urllib.error

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 405, "Method Not Allowed", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    res = mcp_scanner._test_url("https://example.com/mcp-endpoint", {})
    assert res["success"] is True
    assert "405" in res["output"]
