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
    """判断 PID 是否为本工具的 Python 进程。

    tasklist 输出每行形如 "python.exe  1234 Console  1  100,000 K"，
    按行 split 后精确比对第一列（进程名），避免 "python" 裸子串误伤
    PID 复用后的无关进程（如 xxx_python_helper.exe）。
    """
    try:
        lines = _tasklist(pid).splitlines()
    except OSError:
        return False
    for line in lines:
        parts = line.split()
        if parts and parts[0] in ("python.exe", "pythonw.exe"):
            return True
    return False


def _cleanup_state_files() -> None:
    """删除 pid / addr 状态文件（不存在时静默忽略）。"""
    for f in (PID_FILE, ADDR_FILE):
        try:
            f.unlink()
        except OSError:
            pass


def stop_service() -> None:
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid = 0
    killed = bool(pid) and is_alive(pid)
    if killed:
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True, creationflags=CREATE_NO_WINDOW,
        )
    _cleanup_state_files()
    # 文案区分：真停掉服务 vs 仅清理残留状态文件（pid 无效/进程已死的防御分支）
    notify(
        "CC-Toolbox 服务已停止。" if killed
        else "状态文件已清理（未发现运行中的服务）。"
    )


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
    if os.environ.get("CC_TOOLBOX_NO_GUI"):
        _wait_for_server(cli_mode=True)
    else:
        _show_waiting_window()


def _read_addr():
    """读取 server_addr.txt，未就绪返回 None。"""
    try:
        url = ADDR_FILE.read_text(encoding="utf-8").strip()
        return url or None
    except OSError:
        return None


def _finish_start(url: str) -> None:
    webbrowser.open(url)
    notify(f"已启动：{url}\n\n再次双击桌面图标可停止服务。")


def _wait_for_server(cli_mode: bool = False, on_tick=None, on_done=None, on_timeout=None) -> None:
    """轮询 server_addr.txt（最多 25 秒）。cli_mode=打印；否则回调驱动（GUI 用）。"""
    for i in range(50):
        url = _read_addr()
        if url:
            if on_done:
                on_done(url)
            elif cli_mode:
                _finish_start(url)
            return
        if on_tick:
            on_tick(i)
        if cli_mode:
            time.sleep(0.5)
    if on_timeout:
        on_timeout()
    elif cli_mode:
        notify("服务启动超时（25 秒）。\n请查看项目目录 server.log，或双击 launcher.bat 查看详细输出。")


def _show_waiting_window() -> None:
    """启动等待窗口：跑马灯 + 状态文案，服务就绪后自动关闭并打开浏览器。"""
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        _wait_for_server(cli_mode=True)  # tkinter 不可用时退回无界面等待
        return

    BG = "#12294d"       # 深蓝底，与海星图标背景一致
    FG = "#e8f0ff"
    ACCENT = "#ff7a5c"   # 海星橙红
    root = tk.Tk()
    root.title("CC-Toolbox")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)
    try:
        root.iconbitmap(str(BASE / "static" / "app_icon.ico"))
    except tk.TclError:
        pass
    # 屏幕居中
    w, h = 420, 190
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    tk.Label(
        root, text="CC-Toolbox 正在启动", font=("Microsoft YaHei UI", 14, "bold"),
        bg=BG, fg=FG,
    ).pack(pady=(22, 6))
    status = tk.Label(
        root, text="正在启动服务并扫描工具目录…", font=("Microsoft YaHei UI", 10),
        bg=BG, fg=FG,
    )
    status.pack()
    tk.Label(
        root, text="首次启动约需 10~20 秒，请稍候", font=("Microsoft YaHei UI", 9),
        bg=BG, fg="#9db4d8",
    ).pack(pady=(2, 10))
    bar = ttk.Progressbar(root, mode="indeterminate", length=320)
    bar.pack()
    bar.start(12)
    hint = tk.Label(
        root, text="可关闭此窗口，服务将在后台继续启动", font=("Microsoft YaHei UI", 8),
        bg=BG, fg="#6d84a8",
    )
    hint.pack(side="bottom", pady=8)

    closed_by_user = {"flag": False}

    def on_close():
        closed_by_user["flag"] = True
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    # after() 自轮询：不阻塞 UI 渲染
    state = {"ticks": 0}

    def poll():
        if closed_by_user["flag"]:
            return
        url = _read_addr()
        if url:
            root.destroy()
            _finish_start(url)
            return
        state["ticks"] += 1
        if state["ticks"] >= 50:  # 25 秒超时
            bar.stop()
            status.config(text="启动超时（25 秒）。请查看 server.log 或用 launcher.bat 排查。", fg="#ffb4a8")
            hint.config(text="再次双击图标可停止后台服务")
            return
        if state["ticks"] % 2 == 0:
            status.config(text=f"正在启动服务并扫描工具目录…（已等待 {state['ticks'] // 2} 秒）")
        root.after(500, poll)

    root.after(300, poll)
    root.mainloop()


def main() -> None:
    if os.name != "nt":
        return
    if PID_FILE.exists():
        # 读 pid 并判活：活着才停止；残留 pid 文件（重启后进程已死）直接清理，
        # 走启动分支——不停止、不谎报"已停止"，由启动等待窗自然完成
        try:
            pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = 0
        if pid and is_alive(pid):
            stop_service()
            return
        _cleanup_state_files()
    start_service()


if __name__ == "__main__":
    sys.exit(main())
