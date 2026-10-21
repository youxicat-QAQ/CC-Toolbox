"""launch_w.pyw（桌面图标无窗口启动器）PID 判活与启停分支测试。

launch_w 是 .pyw 文件，不在标准 import 模块名空间——用 importlib 按路径加载。
所有弹窗（notify）与 tasklist/taskkill 子进程均打桩，不触碰真实系统进程。
"""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent


def _load_launch_w():
    """按文件路径加载 launch_w.pyw 为名为 launch_w 的模块。

    .pyw 只在 Windows 是合法源码后缀，Linux/macOS 上 spec_from_file_location
    识别不了会返回 None——显式指定 SourceFileLoader 保证跨平台可加载。
    """
    path = BASE / "launch_w.pyw"
    loader = SourceFileLoader("launch_w", str(path))
    spec = importlib.util.spec_from_file_location("launch_w", path, loader=loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


launch_w = _load_launch_w()


class _FakeResult:
    """subprocess.run 的最小打桩返回值。"""

    def __init__(self, stdout: str = ""):
        self.stdout = stdout


# 仿真 tasklist 头 + 一行 python.exe（真实 tasklist /FI 输出风格，含大小写）
_TASKLIST_PYTHON = (
    "Image Name                     PID Session Name        Session#    Mem Usage\n"
    "=========================     ================ =============== ===========\n"
    "python.exe                    4242 Console                    1    100,000 K\n"
)
_TASKLIST_NOTES = (
    "Image Name                     PID Session Name        Session#    Mem Usage\n"
    "=========================     ================ =============== ===========\n"
    "notes.exe                     4242 Console                    1     50,000 K\n"
)


@pytest.fixture
def lw(tmp_path, monkeypatch):
    """隔离 PID/ADDR 文件到 tmp，并禁止真实弹窗。"""
    monkeypatch.setattr(launch_w, "PID_FILE", tmp_path / ".launcher.pid")
    monkeypatch.setattr(launch_w, "ADDR_FILE", tmp_path / "server_addr.txt")
    monkeypatch.setenv("CC_TOOLBOX_NO_GUI", "1")
    return launch_w


def _patch_notify(lw_mod, monkeypatch, sink):
    monkeypatch.setattr(lw_mod, "notify", lambda text, *a, **k: sink.append(text))


# ── is_alive：进程名精确匹配 ──


def test_is_alive_python_exe(lw, monkeypatch):
    monkeypatch.setattr(lw, "_tasklist", lambda pid: _TASKLIST_PYTHON.lower())
    assert lw.is_alive(4242) is True


def test_is_alive_pythonw_exe(lw, monkeypatch):
    monkeypatch.setattr(lw, "_tasklist", lambda pid: "pythonw.exe  4242 console  1  10,000 k")
    assert lw.is_alive(4242) is True


def test_is_alive_unrelated_process_false(lw, monkeypatch):
    """输出只含 notes.exe（无 python 行）→ False。"""
    monkeypatch.setattr(lw, "_tasklist", lambda pid: _TASKLIST_NOTES.lower())
    assert lw.is_alive(4242) is False


def test_is_alive_substring_not_enough(lw, monkeypatch):
    """进程名只是包含 python 子串（PID 复用场景）→ 精确匹配下应为 False。"""
    monkeypatch.setattr(lw, "_tasklist", lambda pid: "my_python_tool.exe  4242 console  1  10,000 k")
    assert lw.is_alive(4242) is False


# ── main 分支：pid 存活 → 停止；pid 残留（进程已死）→ 清理后启动 ──


def test_main_pid_alive_stops_service(lw, monkeypatch):
    lw.PID_FILE.write_text("4242", encoding="utf-8")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd and cmd[0] == "tasklist":
            return _FakeResult(_TASKLIST_PYTHON)
        return _FakeResult("")

    monkeypatch.setattr(lw.subprocess, "run", fake_run)
    monkeypatch.setattr(lw, "start_service", lambda: pytest.fail("存活时不应走启动分支"))
    notes = []
    _patch_notify(lw, monkeypatch, notes)

    lw.main()

    assert any(cmd[0] == "taskkill" for cmd in calls), "应调用 taskkill 停止服务"
    assert not lw.PID_FILE.exists()
    assert not lw.ADDR_FILE.exists()
    assert any("已停止" in t for t in notes)


def test_main_stale_pid_file_starts_service(lw, monkeypatch):
    """pid 文件存在但进程已死：删 pid/addr 后走启动分支，不调 taskkill、不谎报已停止。"""
    lw.PID_FILE.write_text("4242", encoding="utf-8")
    lw.ADDR_FILE.write_text("http://127.0.0.1:8765", encoding="utf-8")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return _FakeResult("INFO: No tasks are running which match the specified criteria.\n")

    monkeypatch.setattr(lw.subprocess, "run", fake_run)
    started = []
    monkeypatch.setattr(lw, "start_service", lambda: started.append(True))
    notes = []
    _patch_notify(lw, monkeypatch, notes)

    lw.main()

    assert started == [True], "残留 pid 文件应走启动分支"
    assert not any(cmd[0] == "taskkill" for cmd in calls), "进程已死不应调 taskkill"
    assert not lw.PID_FILE.exists(), "启动前应清理残留 pid 文件"
    assert not lw.ADDR_FILE.exists(), "启动前应清理残留 addr 文件"
    assert not any("已停止" in t for t in notes), "不应谎报已停止"


def test_main_no_pid_file_starts_service(lw, monkeypatch):
    monkeypatch.setattr(lw, "start_service", lambda: None)  # 无 pid 文件时直接启动（不抛错即可）
    lw.main()


# ── stop_service 文案区分：服务已停止 vs 状态文件已清理 ──


def test_stop_service_alive_message(lw, monkeypatch):
    lw.PID_FILE.write_text("4242", encoding="utf-8")
    monkeypatch.setattr(lw, "_tasklist", lambda pid: _TASKLIST_PYTHON.lower())
    killed = []

    def fake_run(cmd, **kwargs):
        killed.append(list(cmd))
        return _FakeResult("")

    monkeypatch.setattr(lw.subprocess, "run", fake_run)
    notes = []
    _patch_notify(lw, monkeypatch, notes)

    lw.stop_service()

    assert any(cmd[0] == "taskkill" for cmd in killed)
    assert notes == ["CC-Toolbox 服务已停止。"]
    assert not lw.PID_FILE.exists()


def test_stop_service_dead_pid_message(lw, monkeypatch):
    """防御分支：pid 有效但进程已死 → 只清理状态文件，文案为"状态文件已清理"。"""
    lw.PID_FILE.write_text("4242", encoding="utf-8")
    monkeypatch.setattr(lw, "_tasklist", lambda pid: _TASKLIST_NOTES.lower())
    monkeypatch.setattr(
        lw.subprocess, "run",
        lambda cmd, **k: pytest.fail("进程已死不应调 taskkill"),
    )
    notes = []
    _patch_notify(lw, monkeypatch, notes)

    lw.stop_service()

    assert notes and "状态文件已清理" in notes[0]
    assert "已停止" not in notes[0]
    assert not lw.PID_FILE.exists()
    assert not lw.ADDR_FILE.exists()
