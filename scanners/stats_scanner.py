"""使用统计扫描器 — 从 JSONL 会话中提取工具调用数据"""
import json
import logging
import threading
import time
from typing import Optional

import config

logger = logging.getLogger(__name__)

_cache = {}
_cache_time: Optional[float] = None
_cache_lock = threading.Lock()


def _iter_tool_nodes(node):
    """用显式栈遍历 JSON 结构，产出所有 type 为 tool_use/tool_result 的 dict 节点。

    真实会话里 tool_use 嵌套在 {"type":"assistant", "message": {"content": [...]}}
    中，必须深度遍历；这里读结构化字段，绝不对整行文本做子串匹配（#9）。
    迭代而非递归：深嵌套 JSON（数千层）不会叠加 Python 调用栈触发
    RecursionError（#I-1）。
    """
    stack = [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if cur.get("type") in ("tool_use", "tool_result"):
                yield cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _scan_jsonl_files() -> dict:
    """扫描 ~/.claude/projects/ 下的 JSONL 文件，统计工具调用次数。"""
    stats = {}  # tool_name → count
    projects_dir = config.CLAUDE_BASE / "projects"
    if not projects_dir.exists():
        return stats

    # 只扫一层 projects/<session_dir>/*.jsonl（rglob 会递归进 subagents 造成重复统计）
    candidates = []
    try:
        for f in projects_dir.glob("*/*.jsonl"):
            try:
                candidates.append((f.stat().st_mtime, f))
            except OSError as exc:
                logger.warning("会话文件不可读，跳过 %s：%s", f, exc)
    except OSError as exc:
        logger.warning("projects 目录不可读，跳过统计：%s", exc)
        return stats

    # 按 mtime 降序排序，取最新 20 个文件
    candidates.sort(key=lambda t: -t[0])
    session_files = [f for _, f in candidates[:20]]

    for fp in session_files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except (ValueError, RecursionError):
                        # JSONDecodeError ⊂ ValueError；深嵌套合法 JSON 抛的是
                        # RecursionError（非 ValueError）——两者都按坏行跳过（#I-1）
                        continue
                    if not isinstance(data, dict):
                        continue
                    # 只保留结构化 tool_use/tool_result 提取（#9：删整行子串匹配）
                    for nd in _iter_tool_nodes(data):
                        tname = nd.get("name") or nd.get("tool") or nd.get("tool_name")
                        if (isinstance(tname, str) and tname
                                and len(tname) < 50 and not tname.startswith("_")):
                            key = tname.lower()
                            stats[key] = stats.get(key, 0) + 1
        except (OSError, ValueError, RecursionError) as exc:
            # 单文件解析失败：告警跳过，不影响其余文件（#13）；RecursionError
            # 覆盖 json.loads / 遍历在极深嵌套下的递归溢出（#I-1）
            logger.warning("会话 JSONL 解析失败，跳过 %s：%s", fp, exc)
            continue

    return stats


def get_usage_stats(force_refresh: bool = False) -> dict:
    """获取使用统计。返回 {tool_name: count, ...}。

    加锁 + double-checked 防并发重复扫描（_cache 是 dict，写法与 list 型一致）。
    """
    global _cache, _cache_time
    now = time.time()
    if not force_refresh and _cache_time is not None and (now - _cache_time) <= config.CACHE_TTL:
        return _cache
    with _cache_lock:
        now = time.time()
        if not force_refresh and _cache_time is not None and (now - _cache_time) <= config.CACHE_TTL:
            return _cache
        _cache = _scan_jsonl_files()
        _cache_time = now
        return _cache


def get_top_tools(limit: int = 20, force_refresh: bool = False) -> list:
    """获取最常用的工具排行。"""
    stats = get_usage_stats(force_refresh)
    sorted_items = sorted(stats.items(), key=lambda x: -x[1])
    return [{"name": name, "count": count} for name, count in sorted_items[:limit]]
