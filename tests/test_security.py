"""批次 A1：CSRF 防护 / 安全响应头 / npx 路径解析 / 端口占用预检 / 路径更新清缓存"""
import json
import os
import socket
from pathlib import Path

import pytest


# ── 1. CSRF 防护 ──────────────────────────────────────────────


def test_post_with_malicious_origin_rejected(client):
    """POST 带跨站 Origin → 403。"""
    resp = client.post(
        "/api/hooks/x/toggle",
        headers={"Origin": "http://evil.example.com"},
    )
    assert resp.status_code == 403
    assert resp.get_json()["success"] is False
    assert "跨站" in resp.get_json()["error"]


def test_post_with_correct_origin_allowed(client):
    """POST 带正确 Origin（本机 host）→ 非 403（走到业务逻辑）。"""
    # test_client 默认 SERVER_NAME 为 "localhost"
    resp = client.post(
        "/api/hooks/x/toggle",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code != 403


def test_post_without_origin_allowed(client):
    """无 Origin/Referer 的 POST（curl / 本机工具）→ 非 403。"""
    resp = client.post("/api/hooks/x/toggle")
    assert resp.status_code != 403


def test_get_request_unaffected_by_csrf(client):
    """GET 请求不受 CSRF 钩子影响，且响应头含安全头。"""
    resp = client.get("/api/summary")
    assert resp.status_code == 200
    assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"


def test_json_response_referrer_policy(client):
    """JSON 响应额外带 Referrer-Policy: same-origin。"""
    resp = client.get("/api/summary")
    assert resp.mimetype == "application/json"
    assert resp.headers.get("Referrer-Policy") == "same-origin"


def test_referer_malicious_origin_rejected(client):
    """无 Origin 但 Referer 为跨站 → 403。"""
    resp = client.post(
        "/api/hooks/x/toggle",
        headers={"Referer": "http://evil.example.com/attack"},
    )
    assert resp.status_code == 403


# ── 2. npx 型 MCP _resolve_executable ────────────────────────


def test_resolve_executable_bare_npx_resolves(monkeypatch):
    """裸命令名经 shutil.which 解析到真实路径（npx → npx.CMD）。"""
    import shutil
    from scanners import mcp_scanner

    monkeypatch.setattr(
        shutil, "which",
        lambda cmd: "C:/fake/npx.CMD" if cmd == "npx" else None,
    )
    assert mcp_scanner._resolve_executable("npx") == "C:/fake/npx.CMD"


def test_resolve_executable_path_passthrough():
    """已是路径（含分隔符）原样返回，不调用 which。"""
    from scanners import mcp_scanner
    # 含路径分隔符，应直接返回原值
    assert mcp_scanner._resolve_executable("C:/foo/bar") == "C:/foo/bar"


def test_resolve_executable_not_found_returns_original(monkeypatch):
    """which 找不到 → 返回原命令名。"""
    import shutil
    from scanners import mcp_scanner

    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    assert mcp_scanner._resolve_executable("nonexistent-tool") == "nonexistent-tool"


def test_test_stdio_uses_resolved_path_in_argv(monkeypatch):
    """_test_stdio 构造 argv 时 argv[0] 应为 shutil.which 解析后的真实路径。"""
    import shutil
    from scanners import mcp_scanner

    captured_argv = {}

    class FakeProc:
        def __init__(self, argv, *a, **k):
            captured_argv["argv"] = argv
            self.stdout = None
            self.stderr = None

        def communicate(self, input=None, timeout=None):
            return '{"jsonrpc":"2.0","id":1,"result":{}}', ""

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(mcp_scanner.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(
        shutil, "which",
        lambda cmd: "C:/fake/npx.CMD" if cmd == "npx" else None,
    )

    mcp_scanner._test_stdio("npx", ["-y", "some-package"])
    assert captured_argv["argv"][0] == "C:/fake/npx.CMD"
    assert captured_argv["argv"][1:] == ["-y", "some-package"]


# ── 3. 端口占用预检 ──────────────────────────────────────────


def test_run_server_port_occupied_raises_and_no_addr_file(tmp_path, monkeypatch):
    """显式端口被占用 → SystemExit 且 ADDR_FILE 不存在。"""
    import app as app_module

    addr_file = tmp_path / "server_addr.txt"
    pid_file = tmp_path / ".launcher.pid"
    monkeypatch.setattr(app_module, "ADDR_FILE", addr_file)
    monkeypatch.setattr(app_module, "PID_FILE", pid_file)

    # 占住一个端口
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("127.0.0.1", 0))
        occupied_port = blocker.getsockname()[1]

        with pytest.raises(SystemExit):
            app_module.run_server(host="127.0.0.1", port=occupied_port)

    assert not addr_file.exists()
    assert not pid_file.exists()


def test_run_server_normal_port_writes_then_cleans_files(tmp_path, monkeypatch):
    """正常端口启动（monkeypatch app.run 为 no-op）→ 写 addr/pid，返回后 finally 清理。"""
    import app as app_module

    addr_file = tmp_path / "server_addr.txt"
    pid_file = tmp_path / ".launcher.pid"
    monkeypatch.setattr(app_module, "ADDR_FILE", addr_file)
    monkeypatch.setattr(app_module, "PID_FILE", pid_file)

    # monkeypatch app.run 为 no-op，直接 return 触发 finally
    monkeypatch.setattr(app_module.app, "run", lambda **kw: None)

    # 找一个空闲端口
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]

    app_module.run_server(host="127.0.0.1", port=free_port)

    # app.run 返回后 finally 已清理
    assert not addr_file.exists()
    assert not pid_file.exists()


# ── 4. 设置页保存路径后清扫描器缓存 ──────────────────────────


def test_paths_update_clears_skill_scanner_cache(client, fake_env, monkeypatch):
    """POST /api/paths 成功后，skill_scanner._cache_time 被清空，新目录立即可见。"""
    from scanners import skill_scanner

    # 预热缓存（扫描空目录）
    skill_scanner.get_skills()
    assert skill_scanner._cache_time is not None

    # 造一个含 SKILL.md 的临时目录
    new_skill_dir = fake_env.tmp / "new-skills"
    skill_sub = new_skill_dir / "brand-new-skill"
    skill_sub.mkdir(parents=True)
    (skill_sub / "SKILL.md").write_text(
        "---\nname: brand-new-skill\ndescription: 新技能\n---\n\n正文\n",
        encoding="utf-8",
    )

    # POST /api/paths 加新目录
    resp = client.post(
        "/api/paths",
        json={"group": "skill_paths", "paths": [str(new_skill_dir)]},
    )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    # 缓存已被清空
    assert skill_scanner._cache_time is None

    # 立即 GET /api/skills 能看到新技能（无需 refresh=1）
    resp = client.get("/api/skills")
    assert resp.status_code == 200
    names = [s["name"] for s in resp.get_json()]
    assert "brand-new-skill" in names


def test_paths_update_clears_cli_and_mcp_cache(client, fake_env):
    """POST /api/paths 同时清 cli_scanner 与 mcp_scanner 缓存。"""
    from scanners import cli_scanner, mcp_scanner

    cli_scanner.get_cli_tools()
    mcp_scanner.get_mcp_servers()
    assert cli_scanner._cache_time is not None
    assert mcp_scanner._cache_time is not None

    resp = client.post(
        "/api/paths",
        json={"group": "cli_paths", "paths": [str(fake_env.tmp / "cli")]},
    )
    assert resp.status_code == 200
    assert cli_scanner._cache_time is None
    assert mcp_scanner._cache_time is None


def test_paths_update_invalid_group_does_not_clear_cache(client, fake_env):
    """非法 group 返回 400，不清缓存。"""
    from scanners import skill_scanner

    skill_scanner.get_skills()
    cached_time = skill_scanner._cache_time
    assert cached_time is not None

    resp = client.post(
        "/api/paths",
        json={"group": "bogus", "paths": []},
    )
    assert resp.status_code == 400
    assert skill_scanner._cache_time == cached_time
