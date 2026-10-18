"""CC-Toolbox 后台启动助手：相对定位解释器、子进程启动 app.py、轮询实际地址后打开浏览器"""
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ADDR_FILE = BASE_DIR / "server_addr.txt"
PID_FILE = BASE_DIR / ".launcher.pid"
LOG_FILE = BASE_DIR / "server.log"

# 优先用项目本地 venv，否则回退到当前解释器
VENV_PYTHON = BASE_DIR / "venv" / "Scripts" / "python.exe"
PY = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable

# 清理旧的地址文件，避免读到过期数据
if ADDR_FILE.exists():
    ADDR_FILE.unlink()

# 后台启动 app.py（日志写 server.log）
proc = subprocess.Popen(
    [PY, str(BASE_DIR / "app.py")],
    cwd=str(BASE_DIR),
    stdout=open(LOG_FILE, "w"),
    stderr=subprocess.STDOUT,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP") else 0,
)
PID_FILE.write_text(str(proc.pid), encoding="utf-8")
print(f"CC-Toolbox 已启动 (PID: {proc.pid})")

# 轮询 server_addr.txt（最多 20 次 × 0.5s）
addr = None
for _ in range(40):
    time.sleep(0.5)
    if ADDR_FILE.exists():
        addr = ADDR_FILE.read_text(encoding="utf-8").strip()
        if addr:
            break

if addr:
    print(f"服务地址: {addr}")
    print("正在打开浏览器...")
    webbrowser.open(addr)
    print("OK! 浏览器已打开")
else:
    print(f"警告：20 秒内未读到 server_addr.txt，服务可能启动失败，详见 {LOG_FILE}")

print("如需停止，请运行: taskkill /F /PID <PID>")
print(f"或读取 {PID_FILE} 中的 PID 后手动 taskkill")
