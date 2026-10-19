"""Hook 扫描器 — 解析 ~/.claude/settings.json 中的官方 dict 格式 hooks 配置

官方格式（Claude Code settings.json）：
    {"hooks": {"PreToolUse": [{"matcher": "Bash",
                               "hooks": [{"type": "command", "command": "python x.py"}]}],
               "SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}

官方 schema 没有 enabled 字段：往条目里写 enabled:false 只会让 UI「看起来禁用」，
Hook 实际照常执行。因此「禁用」= 从 settings.json 弹出条目、连同还原坐标与完整快照
存进应用目录的 sidecar 文件 hook_disabled.json；「启用」= 从 sidecar 原位插回。
settings.json 含 ANTHROPIC_AUTH_TOKEN 等敏感 env，任何写入都走
「首次备份（settings.json.cc-toolbox.bak）+ 原子写（tmp + os.replace）」。
"""
import json
import logging
import os
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

import config

logger = logging.getLogger(__name__)

_cache: List[dict] = []
_cache_time: Optional[float] = None
_lock = threading.Lock()
# 写锁：toggle 整段「重扫定位 + 读改写 settings/sidecar + 清缓存」串行化，
# 防止并发请求读后写覆盖（丢失更新）。锁序固定 _write_lock → _lock 单向：
# toggle 在持有 _write_lock 时会经 get_hooks/_clear_cache 获取 _lock，
# 读侧只拿 _lock，绝不反向获取，故无死锁（_lock 不可重入，不能用它包全程）
_write_lock = threading.Lock()

# sidecar：被禁用 Hook 的还原档案（放应用根目录而非 ~/.claude，区别于 config/ 下的数据文件）
SIDECAR_FILE = Path(__file__).parent.parent / "hook_disabled.json"

# 同步（阻塞）事件：Claude 等待 Hook 执行结果再继续主流程；
# 其余（SessionStart/SessionEnd/Notification 等通知类、ConfigChange 等环境变更类）
# 展示为非阻塞。另外条目级官方字段 "async": true 表示后台执行，同样按非阻塞展示。
BLOCKING_EVENTS = {
    "UserPromptSubmit", "UserPromptExpansion",
    "PreToolUse", "PostToolUse", "PostToolUseFailure", "PostToolBatch",
    "Stop", "StopFailure", "SubagentStop", "SubagentStart",
    "PreCompact", "PostCompact",
    "PermissionRequest", "PermissionDenied",
    "TaskCreated", "TaskCompleted",
    "Elicitation", "ElicitationResult",
}


class _ToggleError(RuntimeError):
    """toggle 的可预期失败；message 原样作为 error 字段返回。"""


# ── 读取解析 ──────────────────────────────────────────────


def _settings_path() -> Path:
    return config.CLAUDE_BASE / "settings.json"


def _find_hooks_key(data: dict) -> Optional[str]:
    """返回原文件实际使用的 hooks 键名（hooks / hookConfigs），写回时沿用同一键。"""
    if isinstance(data.get("hooks"), (dict, list)):
        return "hooks"
    if isinstance(data.get("hookConfigs"), (dict, list)):
        return "hookConfigs"
    return None


def _extract_command(hook: dict) -> str:
    """取 hook 的 command；兼容旧扁平格式的 script / scriptPath 键。"""
    cmd = hook.get("command")
    if not cmd:
        cmd = hook.get("script") or hook.get("scriptPath") or ""
    return cmd if isinstance(cmd, str) else ""


def _iter_hook_entries(raw_hooks) -> Iterator[Tuple[str, str, int, int, dict]]:
    """逐层展开 hooks 配置，yield (event, matcher, group_index, hook_index, hook)。

    官方 dict 格式：hooks[event] 是组数组，组 = {matcher?, hooks: [hook, ...]}；
    matcher 缺省视为 "*"（匹配全部）。跳过非 dict / 无 command 的项。
    """
    if isinstance(raw_hooks, dict):
        for event, groups in raw_hooks.items():
            if not isinstance(event, str) or not isinstance(groups, list):
                continue
            for gi, group in enumerate(groups):
                if not isinstance(group, dict):
                    continue
                inner = group.get("hooks")
                if not isinstance(inner, list):
                    continue
                matcher = group.get("matcher") or "*"
                if not isinstance(matcher, str):
                    matcher = str(matcher)
                for hi, hook in enumerate(inner):
                    if not isinstance(hook, dict) or not _extract_command(hook):
                        continue
                    yield event, matcher, gi, hi, hook
    elif isinstance(raw_hooks, list):
        # 防御分支：历史残留的扁平 list 格式
        # [{event/hookType, script/scriptPath/command, ...}, ...]，尽力解析不崩溃
        for gi, hook in enumerate(raw_hooks):
            if not isinstance(hook, dict) or not _extract_command(hook):
                continue
            event = hook.get("event") or hook.get("hookType") or "unknown"
            matcher = hook.get("matcher") or "*"
            yield str(event), str(matcher), gi, 0, hook


def _build_item(event: str, matcher: str, gi: int, hi: int, hook: dict,
                settings_path: Path, enabled: bool) -> dict:
    command = _extract_command(hook)
    return {
        # id = event:组下标:条目下标 —— 唯一、URL 安全、toggle 寻址用
        "id": f"{event}:{gi}:{hi}",
        "name": "",  # 由 _assign_names 统一填充
        "event": event,
        "matcher": matcher,
        "command": command,
        "script": command,  # 兼容旧前端（Task 4 改为 id 前仍读 script）
        # 仅显式布尔 true 算异步（is True 防字符串 "false" 等 truthy 值误判）
        "blocking": event in BLOCKING_EVENTS and hook.get("async") is not True,
        "enabled": enabled,
        "group_index": gi,   # 还原坐标（sidecar 条目供 toggle 用）
        "hook_index": hi,
        "description": config.HOOK_EVENT_DESCRIPTIONS.get(event, f"{event} 事件触发"),
        "settings_path": str(settings_path),
    }


def _assign_names(items: List[dict]) -> None:
    """生成展示名：该 event 仅一条时用事件名，多条时按扫描顺序编号，全局唯一。"""
    total = Counter(item["event"] for item in items)
    seq = Counter()
    for item in items:
        event = item["event"]
        if total[event] == 1:
            item["name"] = event
        else:
            seq[event] += 1
            item["name"] = f"{event} #{seq[event]}"


def _read_sidecar_entries() -> List[dict]:
    """读 sidecar 中的禁用记录；文件缺失/损坏视为无记录（不崩溃）。"""
    if not SIDECAR_FILE.exists():
        return []
    try:
        data = json.loads(SIDECAR_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("hook_disabled.json 解析失败（视为无禁用记录）：%s", exc)
        return []
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return []
    return [e for e in data["entries"] if isinstance(e, dict)]


def scan_all() -> List[dict]:
    """读取 settings.json 的 hooks + sidecar 禁用项，合并为展示列表。"""
    settings_path = _settings_path()
    if not settings_path.exists():
        return []
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception as exc:
        # 损坏的 JSON：只告警返回空列表，不抛 500
        logger.warning("settings.json 解析失败，跳过 Hook 扫描：%s（%s）", exc, settings_path)
        return []
    if not isinstance(data, dict):
        return []

    hooks_key = _find_hooks_key(data)
    raw_hooks = data.get(hooks_key) if hooks_key else None

    items: List[dict] = []
    seen_ids = set()
    for event, matcher, gi, hi, hook in _iter_hook_entries(raw_hooks):
        item = _build_item(event, matcher, gi, hi, hook, settings_path, enabled=True)
        if item["id"] in seen_ids:
            continue
        seen_ids.add(item["id"])
        items.append(item)

    # sidecar 里的禁用项合回列表（同 id 时以 settings.json 为准，sidecar 视为陈旧记录）
    for entry in _read_sidecar_entries():
        event = entry.get("event")
        gi, hi = entry.get("group_index"), entry.get("hook_index")
        hook = entry.get("hook")
        if (not isinstance(event, str) or not isinstance(gi, int) or not isinstance(hi, int)
                or not isinstance(hook, dict) or not _extract_command(hook)):
            logger.warning("sidecar 条目字段不完整，已跳过：%r", entry.get("id"))
            continue
        matcher = entry.get("matcher") or "*"
        item = _build_item(event, str(matcher), gi, hi, hook, settings_path, enabled=False)
        # 优先用 sidecar 存储的 id（禁用时已避开与 live 条目的坐标冲突）
        stored_id = entry.get("id")
        if isinstance(stored_id, str) and stored_id:
            item["id"] = stored_id
        if item["id"] in seen_ids:
            continue
        seen_ids.add(item["id"])
        items.append(item)

    _assign_names(items)
    return items


def get_hooks(force_refresh: bool = False) -> List[dict]:
    """带缓存获取（120s TTL；加锁 + double-checked 防并发重复扫描）。"""
    global _cache, _cache_time
    now = time.time()
    if not force_refresh and _cache_time is not None and (now - _cache_time) <= config.CACHE_TTL:
        return _cache
    with _lock:
        now = time.time()
        if not force_refresh and _cache_time is not None and (now - _cache_time) <= config.CACHE_TTL:
            return _cache
        _cache = scan_all()
        _cache_time = now
        return _cache


def _clear_cache() -> None:
    global _cache, _cache_time
    with _lock:
        _cache = []
        _cache_time = None


# ── 写入（备份 + 原子写） ─────────────────────────────────


def _atomic_write(path: Path, text: str) -> None:
    """原子写：先写同目录 .tmp 再 os.replace；失败清理 tmp，主文件保持原样。"""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _commit(settings_path: Path, old_text: Optional[str],
            new_settings_text: str, sidecar_entries: List[dict]) -> None:
    """首次改动前备份（原子写），再原子写 settings.json 与 sidecar；sidecar 失败则回滚 settings。"""
    if old_text is not None:
        bak = settings_path.with_name(settings_path.name + ".cc-toolbox.bak")
        if not bak.exists():
            try:
                # 原子备份：写一半崩溃也不会留下半截 bak（半截会导致「已存在」永不重备）
                _atomic_write(bak, settings_path.read_text(encoding="utf-8"))
            except Exception as exc:
                # 与「写 settings 失败」区分文案，便于定位失败环节
                raise _ToggleError(f"备份 settings.json 失败：{exc}") from exc
    try:
        _atomic_write(settings_path, new_settings_text)
    except Exception as exc:
        raise _ToggleError(f"写入 settings.json 失败：{exc}") from exc

    sidecar_text = json.dumps({"entries": sidecar_entries}, indent=2, ensure_ascii=False)
    try:
        _atomic_write(SIDECAR_FILE, sidecar_text)
    except Exception as exc:
        # settings 已更新而 sidecar 未落盘 → 回滚 settings，保持两文件一致
        rollback_failed = False
        try:
            if old_text is None:
                settings_path.unlink(missing_ok=True)
            else:
                _atomic_write(settings_path, old_text)
        except Exception as exc2:
            rollback_failed = True
            logger.error("sidecar 写失败后回滚 settings.json 亦失败：%s", exc2)
        msg = f"写入 sidecar 失败：{exc}"
        if rollback_failed:
            # 回滚也失败 → 两文件状态可能不一致，给出恢复指引
            msg += "；状态已不一致，可用 settings.json.cc-toolbox.bak 恢复"
        raise _ToggleError(msg) from exc


# ── toggle ────────────────────────────────────────────────


def _parse_id(item_id: str) -> Tuple[str, int, int]:
    try:
        event, gi, hi = str(item_id).rsplit(":", 2)
        return event, int(gi), int(hi)
    except ValueError as exc:
        raise _ToggleError(f"无法解析 Hook id：{item_id}") from exc


def _locate_in_groups(groups: List[dict], gi: int, hi: int, command: str) -> Optional[Tuple[int, int]]:
    """坐标优先、命令一致才命中；坐标失效则在该 event 内按 command 兜底搜索。"""
    if 0 <= gi < len(groups):
        group = groups[gi]
        if (isinstance(group, dict) and isinstance(group.get("hooks"), list)
                and 0 <= hi < len(group["hooks"])):
            cand = group["hooks"][hi]
            if isinstance(cand, dict) and _extract_command(cand) == command:
                return gi, hi
    for g_i, group in enumerate(groups):
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            continue
        for h_i, cand in enumerate(group["hooks"]):
            if isinstance(cand, dict) and _extract_command(cand) == command:
                return g_i, h_i
    return None


def _locate_in_list(raw: List, gi: int, command: str) -> Optional[int]:
    """旧扁平 list：坐标优先，失效则按 command 搜索。"""
    if 0 <= gi < len(raw) and isinstance(raw[gi], dict) and _extract_command(raw[gi]) == command:
        return gi
    for i, item in enumerate(raw):
        if isinstance(item, dict) and _extract_command(item) == command:
            return i
    return None


def _find_restore_group(groups: List[dict], gi: int, matcher_raw) -> Tuple[dict, str]:
    """定位启用时的还原目标组：
    坐标 + matcher 仍匹配 → "coord"（原位插回）；
    否则同 event 内找 matcher 相同的组 → "append"；
    都没有则新建组 → "new"（matcher 缺省时省略键，表示匹配全部）。
    """
    want = matcher_raw if isinstance(matcher_raw, str) and matcher_raw else "*"

    def _adopt(g: dict) -> dict:
        if not isinstance(g.get("hooks"), list):
            g["hooks"] = []
        return g

    if 0 <= gi < len(groups):
        g = groups[gi]
        if isinstance(g, dict) and (g.get("matcher") or "*") == want:
            return _adopt(g), "coord"
    for g in groups:
        if isinstance(g, dict) and (g.get("matcher") or "*") == want:
            return _adopt(g), "append"
    g = {"hooks": []}
    if matcher_raw not in (None, "", "*"):
        g["matcher"] = matcher_raw
    groups.append(g)
    return g, "new"


def _disable(target: dict) -> dict:
    """禁用：从 settings.json 弹出该 hook 条目（组空删组、event 空删 event），
    还原坐标 + 完整快照写入 sidecar。"""
    settings_path = _settings_path()
    if not settings_path.exists():
        raise _ToggleError("settings.json 不存在")
    old_text = settings_path.read_text(encoding="utf-8")
    try:
        data = json.loads(old_text)
    except Exception as exc:
        raise _ToggleError(f"settings.json 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise _ToggleError("settings.json 根节点不是对象")

    hooks_key = _find_hooks_key(data) or "hooks"
    raw = data.get(hooks_key)
    event = target["event"]
    _, gi, hi = _parse_id(target["id"])
    command = target["command"]

    if isinstance(raw, dict):
        groups = raw.get(event)
        if not isinstance(groups, list):
            raise _ToggleError(f"settings.json 中 {event} 事件的 hooks 缺失或格式异常")
        loc = _locate_in_groups(groups, gi, hi, command)
        if loc is None:
            raise _ToggleError("settings.json 中未找到匹配的 Hook（可能已被外部修改）")
        g_i, h_i = loc
        group = groups[g_i]
        matcher_raw = group.get("matcher")          # 原组 matcher（None = 未设置 = 全匹配）
        hook_snapshot = dict(group["hooks"][h_i])   # 完整 hook 条目快照
        group["hooks"].pop(h_i)
        if not group["hooks"]:
            groups.pop(g_i)
        if not groups:
            del raw[event]
    elif isinstance(raw, list):
        l_i = _locate_in_list(raw, gi, command)
        if l_i is None:
            raise _ToggleError("settings.json 中未找到匹配的 Hook（可能已被外部修改）")
        g_i, h_i = l_i, 0
        matcher_raw = raw[l_i].get("matcher")
        hook_snapshot = dict(raw[l_i])
        raw.pop(l_i)
    else:
        raise _ToggleError("settings.json 中没有 hooks 配置")

    # 先清掉同 id 的陈旧 sidecar 记录再追加，保证幂等；
    # 新 id 要避开「移除后的 live 条目」——弹出后后续条目坐标前移，
    # 若仍用 event:gi:hi 可能被顶上来的另一条 hook 占用，导致禁用项从列表消失
    entries = [e for e in _read_sidecar_entries() if e.get("id") != target["id"]]
    taken = {e.get("id") for e in entries}
    for ev, _m, g, h, _hk in _iter_hook_entries(data.get(hooks_key)):
        taken.add(f"{ev}:{g}:{h}")
    new_id = f"{event}:{g_i}:{h_i}"
    suffix = 0
    while new_id in taken:
        suffix += 1
        new_id = f"{event}:{g_i}:{h_i}:{suffix}"
    entries.append({
        "id": new_id,
        "event": event,
        "group_index": g_i,
        "hook_index": h_i,
        "matcher": matcher_raw,
        "command": command,
        "hook": hook_snapshot,
    })
    _commit(settings_path, old_text,
            json.dumps(data, indent=2, ensure_ascii=False), entries)
    _clear_cache()
    return {"success": True, "enabled": False}


def _enable(target: dict) -> dict:
    """启用：从 sidecar 取回快照，坐标仍有效则原位插回 settings.json，再移出 sidecar。"""
    settings_path = _settings_path()
    if settings_path.exists():
        old_text = settings_path.read_text(encoding="utf-8")
        try:
            data = json.loads(old_text)
        except Exception as exc:
            raise _ToggleError(f"settings.json 解析失败：{exc}") from exc
        if not isinstance(data, dict):
            raise _ToggleError("settings.json 根节点不是对象")
    else:
        old_text = None
        data = {}

    entries = _read_sidecar_entries()
    record = next((e for e in entries if e.get("id") == target["id"]), None)
    if record is None:
        raise _ToggleError(f"sidecar 中没有该 Hook 的还原记录：{target['id']}")
    hook_snapshot = record.get("hook")
    event = record.get("event")
    gi, hi = record.get("group_index"), record.get("hook_index")
    matcher_raw = record.get("matcher")
    if (not isinstance(hook_snapshot, dict) or not _extract_command(hook_snapshot)
            or not isinstance(event, str)
            or not isinstance(gi, int) or not isinstance(hi, int)):
        raise _ToggleError("sidecar 还原记录损坏")

    hooks_key = _find_hooks_key(data) or "hooks"
    raw = data.get(hooks_key)

    if isinstance(raw, list):
        # 旧扁平 list：坐标失效则追加末尾
        raw.insert(gi if 0 <= gi <= len(raw) else len(raw), hook_snapshot)
    else:
        if not isinstance(raw, dict):
            raw = {}
            data[hooks_key] = raw
        groups = raw.get(event)
        if groups is None:
            groups = []
            raw[event] = groups
        elif not isinstance(groups, list):
            raise _ToggleError(f"settings.json 中 {event} 的 hooks 结构异常（不是数组）")
        group, at = _find_restore_group(groups, gi, matcher_raw)
        hooks_list = group["hooks"]
        if at == "coord":
            hooks_list.insert(min(hi, len(hooks_list)), hook_snapshot)
        elif at == "append":
            hooks_list.append(hook_snapshot)
        else:  # 新建组
            hooks_list.insert(0, hook_snapshot)

    entries = [e for e in entries if e.get("id") != target["id"]]
    _commit(settings_path, old_text,
            json.dumps(data, indent=2, ensure_ascii=False), entries)
    _clear_cache()
    return {"success": True, "enabled": True}


def toggle_hook(id_or_name: str) -> dict:
    """切换 Hook 启用状态。

    按 id 精确匹配（找不到再按 name 兜底）。
    禁用 = settings.json → sidecar；启用 = sidecar → settings.json 原位插回。
    成功返回 {"success": True, "enabled": ...}，失败返回 {"success": False, "error": "..."}。

    并发限制：整段「重扫定位 + 写入 + 清缓存」持模块级 _write_lock 串行执行
    （读侧 get_hooks/_clear_cache 的 _lock 在其内层，锁序 _write_lock → _lock 单向），
    防止两个请求并发读改写 settings.json 造成丢失更新。
    """
    with _write_lock:
        hooks = get_hooks(force_refresh=True)
        target = next((h for h in hooks if h.get("id") == id_or_name), None)
        if target is None:
            target = next((h for h in hooks if h.get("name") == id_or_name), None)
        if target is None:
            return {"success": False, "error": f"未找到该 Hook：{id_or_name}"}
        try:
            if target.get("enabled", True):
                return _disable(target)
            return _enable(target)
        except _ToggleError as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("切换 Hook 失败：%s", id_or_name)
            return {"success": False, "error": str(exc)}
