"""T4 可移植一键启动系统：run_server 写地址/PID、find_free_port 端口探测"""
import os
import socket
from pathlib import Path

import app as app_module
import config


def _free_port() -> int:
    """临时占一个端口拿到编号后立刻释放，返回可用端口号。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_run_server_writes_addr_and_pid(tmp_path, monkeypatch):
    """run_server 写 server_addr.txt（含实际端口）与 .launcher.pid（当前进程 PID）；
    app.run 返回后 finally 清理两文件。"""
    addr_file = tmp_path / "server_addr.txt"
    pid_file = tmp_path / ".launcher.pid"

    monkeypatch.setattr(app_module, "ADDR_FILE", addr_file)
    monkeypatch.setattr(app_module, "PID_FILE", pid_file)

    captured = {}
    during_run = {}

    def fake_run(host=None, port=None, debug=None):
        captured["host"] = host
        captured["port"] = port
        captured["debug"] = debug
        # app.run 尚未返回时（finally 未执行）：文件应存在且内容正确
        during_run["addr"] = addr_file.read_text(encoding="utf-8")
        during_run["pid"] = pid_file.read_text(encoding="utf-8")

    monkeypatch.setattr(app_module.app, "run", fake_run)

    port = _free_port()
    app_module.run_server(host="127.0.0.1", port=port)

    # app.run 收到正确的 host/port
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == port

    # app.run 运行期间 addr 文件内容包含该端口，pid 为当前进程 PID
    assert f":{port}" in during_run["addr"]
    assert during_run["pid"] == str(os.getpid())

    # run_server 返回后 finally 已清理状态文件
    assert not addr_file.exists()
    assert not pid_file.exists()


def test_run_server_auto_detects_free_port(tmp_path, monkeypatch):
    """port=0 / None 时自动探测空闲端口，写入 addr 文件的端口应为非零可用端口；
    app.run 返回后 finally 清理两文件。"""
    addr_file = tmp_path / "server_addr.txt"
    pid_file = tmp_path / ".launcher.pid"

    monkeypatch.setattr(app_module, "ADDR_FILE", addr_file)
    monkeypatch.setattr(app_module, "PID_FILE", pid_file)

    captured = {}
    during_run = {}

    def fake_run(host=None, port=None, debug=None):
        captured["port"] = port
        # app.run 尚未返回时（finally 未执行）：文件应存在且内容正确
        during_run["addr"] = addr_file.read_text(encoding="utf-8")
        during_run["pid"] = pid_file.read_text(encoding="utf-8")

    monkeypatch.setattr(app_module.app, "run", fake_run)

    # port=0 → 走 find_free_port 探测
    app_module.run_server(host="127.0.0.1", port=0)

    detected_port = captured["port"]
    assert detected_port and detected_port > 0

    # app.run 运行期间 addr/pid 文件内容正确
    assert f":{detected_port}" in during_run["addr"]
    assert during_run["pid"] == str(os.getpid())

    # run_server 返回后 finally 已清理状态文件
    assert not addr_file.exists()
    assert not pid_file.exists()


def test_find_free_port_skips_occupied():
    """find_free_port 从 preferred 起探测，跳过被占用端口，返回下一个空闲端口。"""
    host = "127.0.0.1"
    # 先 bind 一个端口占住 preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind((host, 0))
        occupied = blocker.getsockname()[1]

        result = config.find_free_port(host, occupied)

    # 结果不应是被占用的那个，且应为合法可用端口
    assert result != occupied
    assert result >= occupied
    # 再验证结果确实可用（再次探测一次应仍能返回，此处仅作非负校验）
    assert result > 0
