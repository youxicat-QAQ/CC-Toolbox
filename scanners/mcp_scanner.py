"""MCP 扫描器 — 读取 ~/.claude.json 和项目 .mcp.json"""
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import config
from paths_config import get_extra_mcp_dirs

logger = logging.getLogger(__name__)

_cache: List[dict] = []
_cache_time: Optional[float] = None
_cache_lock = threading.Lock()

# 项目级 .mcp.json 最多检查的项目路径数（防爆）
_MAX_PROJECT_PATHS = 30


def _read_mcp_config(path: Path) -> Dict:
    """读取 JSON 中的 mcpServers；文件缺失/损坏/结构畸形返回空 dict，不抛异常。

    健壮性：顶层非对象（如裸数组/字符串）或 mcpServers 非 dict（null、字符串）
    时返回 {}——调用方直接 .items()，若放行会让 MCP 全线 500。
    全局与项目两个来源都经本函数统一收敛。
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("MCP 配置解析失败，跳过 %s：%s", path, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("MCP 配置顶层应为对象，跳过 %s：actual=%s",
                       path, type(data).__name__)
        return {}
    servers = data.get("mcpServers", data.get("mcp_servers", {}))
    if not isinstance(servers, dict):
        logger.warning("mcpServers 应为对象，跳过 %s：actual=%s",
                       path, type(servers).__name__)
        return {}
    return servers


def _enabled_flag(conf: dict) -> bool:
    """识别 enabled/disabled：默认启用；enabled 显式生效，否则看 disabled:true。"""
    if "enabled" in conf:
        return bool(conf.get("enabled"))
    return not conf.get("disabled", False)


def _describe_mcp(name: str, conf: dict) -> str:
    """推导 MCP 可读描述。"""
    if name in config.KNOWN_MCP_DESCRIPTIONS:
        return config.KNOWN_MCP_DESCRIPTIONS[name]
    url = conf.get("url")
    if conf.get("type") == "url" or (url and not conf.get("command")):
        if url:
            return f"URL 型 MCP 服务 — {str(url)[:60]}"
        return "URL 型 MCP 服务"
    cmd = conf.get("command", "")
    args = conf.get("args")
    # args 畸形（数字/字符串/null）时收敛为空表：直接迭代会 TypeError
    # 从 scan_all 冒出 → 扫描期全线 500
    if not isinstance(args, (list, tuple)):
        args = []
    else:
        # 元素也可能非 str（如 5），统一转 str 防 startswith 再炸
        args = [str(a) for a in args]
    if cmd == "npx" and args:
        pkg = next((a for a in args if not a.startswith("-")), args[0])
        pkg = pkg.replace("-", " ").replace("/", " ").title()
        return f"{pkg} MCP 服务"
    if cmd:
        return f"通过 {cmd} 启动的 MCP 服务"
    return ""


def _build_server(name: str, conf: dict, scope: str, project_path: str = "") -> dict:
    """由一条 mcpServers 配置构造扫描条目。"""
    args = conf.get("args", [])
    # args 畸形（数字/字符串/null）收敛为空表：与 _describe_mcp 同款，
    # 否则 test_connection 里 [str(a) for a in args] 会 TypeError → 500
    if not isinstance(args, (list, tuple)):
        args = []
    item = {
        "name": name,
        "command": conf.get("command", ""),
        "args": list(args),
        "description": _describe_mcp(name, conf),
        "scope": scope,
        "enabled": _enabled_flag(conf),
        # url 型 MCP 需要的透传字段（test_connection / 详情展示用）
        "type": conf.get("type", ""),
        "url": conf.get("url", ""),
        "headers": conf.get("headers", {}),
    }
    if project_path:
        item["project_path"] = project_path
    return item


def scan_global() -> List[dict]:
    """扫描全局 MCP 配置。"""
    servers = []
    cfg_path = config.CLAUDE_MCP_CONFIG.expanduser()
    if not cfg_path.exists():
        return servers
    for name, conf in _read_mcp_config(cfg_path).items():
        if isinstance(conf, dict):
            servers.append(_build_server(name, conf, "global"))
    return servers


def _read_project_paths(cfg_path: Path) -> List[str]:
    """从 ~/.claude.json 的 projects 键读取真实项目路径。

    实际结构：{"projects": {"C:\\path\\to\\proj": {...}, ...}} —— 键即项目根路径。
    文件损坏/键缺失返回空列表。
    """
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception as exc:
        logger.warning("~/.claude.json 解析失败，跳过项目级 MCP 扫描：%s", exc)
        return []
    projects = data.get("projects")
    if not isinstance(projects, dict):
        return []
    return [k for k in projects if isinstance(k, str) and k]


def scan_project() -> List[dict]:
    """扫描项目级 MCP 配置。

    项目路径来源 = ~/.claude.json 的 projects 键解析结果 + paths_config.json
    的 extra_mcp_project_dirs 自定义目录。**extra 目录优先**：用户显式配置，
    去重后全量保留；projects 来源截断到 _MAX_PROJECT_PATHS - len(extra)（最小 0）
    防爆——否则 projects ≥ 上限时，排在后面的 extra 会被统一截断静默丢弃。
    注意：~/.claude.json 缺失/损坏时不再 early return，仍继续检查 extra 目录。
    对每个项目检查 <proj>/.mcp.json 与 <proj>/.claude/.mcp.json；单文件解析
    失败由 _read_mcp_config 记 warning 跳过。
    """
    servers = []
    cfg_path = config.CLAUDE_MCP_CONFIG.expanduser()

    # projects 键解析（文件不存在/损坏由 _read_project_paths 返回 []）
    projs: List[str] = []
    if cfg_path.exists():
        projs = _read_project_paths(cfg_path)

    # extra 目录优先（get_extra_mcp_dirs 返回 list[Path]）：单独收集并全量保留
    extra_dirs: List[str] = []
    seen_set: set = set()
    for p in get_extra_mcp_dirs():
        s = str(p)
        if not s or s in seen_set:
            continue
        seen_set.add(s)
        extra_dirs.append(s)

    # projects 来源字符串级去重保序（含与 extra 的跨源去重）
    proj_dirs: List[str] = []
    for proj in projs:
        if not proj or proj in seen_set:
            continue
        seen_set.add(proj)
        proj_dirs.append(proj)

    # extra 全量 + projects 用剩余名额截断
    budget = max(0, _MAX_PROJECT_PATHS - len(extra_dirs))
    seen_projs = extra_dirs + proj_dirs[:budget]

    seen_files = set()
    # 无需再截断：extra 全量在前，projects 已按剩余名额截到 budget
    for proj in seen_projs:
        proj_root = Path(proj).expanduser()
        for mcp_file in (proj_root / ".mcp.json", proj_root / ".claude" / ".mcp.json"):
            key = str(mcp_file)
            if key in seen_files:
                continue
            seen_files.add(key)
            if not mcp_file.is_file():
                continue
            for name, conf in _read_mcp_config(mcp_file).items():
                if isinstance(conf, dict):
                    servers.append(_build_server(name, conf, "project",
                                                 project_path=str(proj_root)))
    return servers


def scan_all() -> List[dict]:
    """合并全局和项目 MCP，项目覆盖全局同名。"""
    by_name: Dict[str, dict] = {}
    for m in scan_global():
        by_name[m["name"]] = m
    for m in scan_project():
        by_name[m["name"]] = m
    return list(by_name.values())


def get_mcp_servers(force_refresh: bool = False) -> List[dict]:
    """带缓存获取（120s TTL；加锁 + double-checked 防并发重复扫描）。"""
    global _cache, _cache_time
    now = time.time()
    if not force_refresh and _cache_time is not None and (now - _cache_time) <= config.CACHE_TTL:
        return _cache
    with _cache_lock:
        now = time.time()
        if not force_refresh and _cache_time is not None and (now - _cache_time) <= config.CACHE_TTL:
            return _cache
        _cache = scan_all()
        _cache_time = now
        return _cache


# ── 连通性测试 ──────────────────────────────────────────────

_INIT_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "cc-toolbox", "version": "1.0"},
    },
}


def _has_initialize_response(out: str) -> bool:
    """逐行解析 stdout，检查最后一个可解析 JSON 对象是否为 initialize 响应。

    initialize 响应形如 {"jsonrpc":"2.0","id":1,"result":{...}}。取「最后一个
    可解析对象」判定，替代裸 '"jsonrpc"' 子串匹配——日志里偶然出现该字样不再
    误判为握手成功（#M-4）。
    """
    last_obj = None
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            last_obj = obj
    return (isinstance(last_obj, dict)
            and last_obj.get("id") == 1 and "result" in last_obj)


def _resolve_executable(cmd: str) -> str:
    """Windows 下裸命令名经 shutil.which 解析 PATHEXT（npx → npx.cmd）；找不到返回原值。"""
    import shutil
    if os.path.sep in cmd or (os.path.altsep and os.path.altsep in cmd):
        return cmd  # 已是路径
    found = shutil.which(cmd)
    return found or cmd


def _test_stdio(cmd: str, args: list) -> dict:
    """stdio 型：原样执行命令（不追加 --version），stdin 发 MCP initialize 后读响应。

    8s 超时；服务器响应后常不退出——超时后 kill 再收集已产出的 stdout，
    最后一个可解析 JSON 对象为 initialize 响应即算成功。响应统一 {success, output, error}。
    """
    full_cmd = [_resolve_executable(cmd)] + [str(a) for a in args]
    try:
        proc = subprocess.Popen(
            full_cmd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, text=True, encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        return {"success": False, "output": "", "error": f"命令 {cmd} 未找到"}
    except Exception as exc:
        return {"success": False, "output": "", "error": str(exc)}

    request_line = json.dumps(_INIT_REQUEST) + "\n"
    try:
        out, err = proc.communicate(request_line, timeout=8)
    except subprocess.TimeoutExpired:
        # 响应已写出但进程未退出：kill 后再收集输出
        proc.kill()
        try:
            out, err = proc.communicate(timeout=3)
        except Exception:
            # 二次超时：尽力直接读已产出的 stdout/stderr，而非置空
            try:
                out = proc.stdout.read() if proc.stdout else ""
            except Exception:
                out = ""
            try:
                err = proc.stderr.read() if proc.stderr else ""
            except Exception:
                err = ""
        finally:
            # 收尾 wait，防僵尸进程 / ResourceWarning
            try:
                proc.wait(timeout=3)
            except Exception:
                pass
    except Exception as exc:
        proc.kill()
        try:
            proc.wait(timeout=3)
        except Exception:
            pass
        return {"success": False, "output": "", "error": str(exc)}

    out = (out or "").strip()
    err = (err or "").strip()
    if _has_initialize_response(out):
        return {"success": True, "output": out[:2000], "error": ""}
    return {
        "success": False,
        "output": out[:2000],
        "error": err[:500] or "未收到 MCP initialize 响应",
    }


def _test_url(url: str, headers: dict) -> dict:
    """url 型：HEAD 探测，2xx/3xx/405 视为可达，5s 超时。"""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, method="HEAD",
                                 headers=headers if isinstance(headers, dict) else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            code = resp.status
        ok = 200 <= code < 400
        return {"success": ok, "output": f"HTTP {code}",
                "error": "" if ok else f"HTTP {code}"}
    except urllib.error.HTTPError as exc:
        # HEAD 不被支持（405）等价于服务可达
        if exc.code == 405 or 200 <= exc.code < 400:
            return {"success": True, "output": f"HTTP {exc.code}", "error": ""}
        return {"success": False, "output": f"HTTP {exc.code}",
                "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"success": False, "output": "", "error": str(exc)}


def test_connection(name: str) -> dict:
    """测试 MCP 连通性。

    stdio 型：原命令 + MCP initialize 握手；url 型：HEAD 探测。
    不再强加 --version、不再截断 args。返回统一 {success, output, error}。
    """
    servers = get_mcp_servers(force_refresh=True)
    target = next((s for s in servers if s["name"] == name), None)
    if not target:
        return {"success": False, "output": "", "error": "未找到该 MCP 服务"}

    cmd = target.get("command", "")
    url = target.get("url", "")
    # url 型（type=url 或有 url 无 command）
    if target.get("type") == "url" or (url and not cmd):
        return _test_url(str(url), target.get("headers") or {})

    if not cmd:
        return {"success": False, "output": "", "error": "没有可执行的命令"}

    return _test_stdio(str(cmd), target.get("args") or [])
