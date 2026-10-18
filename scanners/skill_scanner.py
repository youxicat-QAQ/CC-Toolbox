"""Skill 扫描器 — 扫描 skills 目录下的 SKILL.md"""
import logging
import re
import threading
import time
from pathlib import Path
from typing import List, Optional

import config
from paths_config import get_merged_skill_paths

logger = logging.getLogger(__name__)

_cache: List[dict] = []
_cache_time: Optional[float] = None
_cache_lock = threading.Lock()


def _read_skill_metadata(skill_dir: Path) -> Optional[dict]:
    """从 SKILL.md 中提取名称和描述。

    frontmatter 的 name 优先，目录名兜底；文件不可读（坏项）返回 None，
    由调用方跳过，绝不让单个坏技能把整个扫描打崩（#13）。
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        # 尝试找其他 .md 文件（排序取首个，保证顺序稳定）
        try:
            mds = sorted(skill_dir.glob("*.md"))
        except OSError as exc:
            logger.warning("技能目录 glob 失败，跳过 %s：%s", skill_dir, exc)
            return None
        skill_md = mds[0] if mds else None
    if not skill_md:
        return {"name": skill_dir.name, "description": ""}

    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("SKILL.md 不可读，跳过技能 %s：%s", skill_dir, exc)
        return None

    # 尝试解析 frontmatter：name 非空则优先，否则目录名兜底
    name = skill_dir.name
    description = ""

    fm_match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if fm_match:
        fm = fm_match.group(1)
        n = re.search(r'^name:\s*(.+)', fm, re.MULTILINE)
        if n:
            fm_name = n.group(1).strip().strip('"\'')
            if fm_name:
                name = fm_name
        d = re.search(r'^description:\s*(.+)', fm, re.MULTILINE)
        if d:
            description = d.group(1).strip().strip('"\'')
    else:
        # 取第一个非标题行
        for line in text.split("\n")[:20]:
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 10:
                description = line[:200]
                break

    # 提取子技能（H2 标题）
    sub_skills = re.findall(r'^##\s+(.+)', text, re.MULTILINE)

    return {
        "name": name,
        "description": description[:300],
        "sub_skills": sub_skills[:20],
        "path": str(skill_md),
    }


def scan_all() -> List[dict]:
    """扫描所有 skills 目录。"""
    tools = []
    seen = set()

    for base_path in get_merged_skill_paths():
        p = base_path.expanduser()
        if not p.exists():
            continue
        try:
            items = sorted(p.iterdir())
        except OSError as exc:
            logger.warning("技能目录不可读，跳过 %s：%s", p, exc)
            continue
        for item in items:
            if not item.is_dir() or item.name.startswith("."):
                continue
            if item.name in seen:
                continue

            meta = _read_skill_metadata(item)
            if meta is None:
                continue  # 坏项已告警，跳过
            seen.add(item.name)
            # frontmatter name 已在 _read_skill_metadata 中优先解析、目录名兜底，
            # 不再用目录名无条件覆盖（#23）
            meta["source"] = str(base_path)
            tools.append(meta)

    return tools


def get_skills(force_refresh: bool = False) -> List[dict]:
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
