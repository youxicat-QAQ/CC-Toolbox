"""CC-Toolbox 无窗口启动器 — 双击桌面快捷方式入口。

行为（开关语义）：
- 服务未运行 → 静默启动（无黑窗）→ 自动打开浏览器 → MessageBox 提示地址
- 服务已运行 → 静默停止 → MessageBox 提示已停止

自动化测试：设环境变量 CC_TOOLBOX_NO_GUI=1 时用 print 代替 MessageBox。
"""
import ctypes
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent
PID_FILE = BASE / ".launcher.pid"
ADDR_FILE = BASE / "server_addr.txt"
LOG_FILE = BASE / "server.log"
VENV_PY = BASE / "venv" / "Scripts" / "python.exe"
CREATE_NO_WINDOW = 0x08000000
DETECT_OK = 0x40  # MB_ICONINFORMATION


def notify(text: str, title: str = "CC-Toolbox") -> None:
    """弹窗提示；CC_TOOLBOX_NO_GUI=1 时降级为打印（供自动化测试）。"""
    if os.environ.get("CC_TOOLBOX_NO_GUI"):
        print(f"[{title}] {text}")
        return
    ctypes.windll.user32.MessageBoxW(0, text, title, DETECT_OK)


def _tasklist(pid: int) -> str:
    return subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}"],
        capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
    ).stdout.lower()


def is_alive(pid: int) -> bool:
    try:
        return "python" in _tasklist(pid)
    except OSError:
        return False


def stop_service() -> None:
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid = 0
    if pid and is_alive(pid):
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True, creationflags=CREATE_NO_WINDOW,
        )
    for f in (PID_FILE, ADDR_FILE):
        try:
            f.unlink()
        except OSError:
            pass
    notify("CC-Toolbox 服务已停止。" if pid else "未发现运行中的服务，已清理状态文件。")


def start_service() -> None:
    if not VENV_PY.exists():
        notify(
            "首次使用请先完成安装：\n"
            "双击项目目录里的「一键安装并创建桌面图标.bat」\n"
            "（或 launcher.bat），安装完成后再双击桌面图标。",
        )
        return
    try:
        if ADDR_FILE.exists():
            ADDR_FILE.unlink()
    except OSError:
        pass
    # 子进程无窗口运行，输出写入 server.log 便于排障
    log = open(LOG_FILE, "w", encoding="utf-8", errors="replace")
    subprocess.Popen(
        [str(VENV_PY), "app.py"],
        cwd=str(BASE),
        creationflags=CREATE_NO_WINDOW,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    log.close()
    for _ in range(50):  # 最多等 25 秒
        try:
            if ADDR_FILE.exists():
                url = ADDR_FILE.read_text(encoding="utf-8").strip()
                if url:
                    webbrowser.open(url)
                    notify(f"已启动：{url}\n\n再次双击桌面图标可停止服务。")
                    return
        except OSError:
            pass
        time.sleep(0.5)
    notify("服务启动超时（25 秒）。\n请查看项目目录 server.log，或双击 launcher.bat 查看详细输出。")


def main() -> None:
    if os.name != "nt":
        return
    if PID_FILE.exists():
        stop_service()
    else:
        start_service()


if __name__ == "__main__":
    sys.exit(main())
