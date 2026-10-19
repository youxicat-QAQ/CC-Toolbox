"""AI 描述文件（ai_descriptions.json）测试：最高优先级 / 元键过滤 / 合并 / 损坏容错"""
import json

import desc_cache


def _write_ai(data: dict) -> None:
    """把 AI 描述数据写入 fake_env 隔离后的 AI_DESC_FILE。"""
    desc_cache.AI_DESC_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def test_ai_desc_missing_file_returns_empty(fake_env):
    """AI 文件不存在 → get_ai_entry 为空，get_description 回退到原链（含中文 original）。"""
    assert not desc_cache.AI_DESC_FILE.exists()
    assert desc_cache.get_ai_entry("any", "skill") == {}
    assert desc_cache.count_ai_entries() == 0

    # 原链：无缓存、无 known 命中 → 原始描述含中文则直接返回 original
    assert (
        desc_cache.get_description("no-such-tool", "skill", "中文原始描述")
        == "中文原始描述"
    )


def test_ai_desc_highest_priority(fake_env):
    """AI 文件的 desc 优先于 desc_cache.json 里的旧缓存值。"""
    _write_ai({"skill": {"foo": {"desc": "AI 权威描述"}}})
    # 缓存里预置同名旧值，验证 AI 文件优先
    desc_cache.CACHE_FILE.write_text(
        json.dumps({"skill::foo": {"desc": "旧缓存描述", "usage": "旧缓存用法"}},
                   ensure_ascii=False),
        encoding="utf-8",
    )

    assert desc_cache.get_description("foo", "skill") == "AI 权威描述"


def test_ai_desc_usage_priority(fake_env):
    """AI 文件的 usage 优先于 desc_cache.json 里的旧缓存值。"""
    _write_ai({"skill": {"foo": {"desc": "AI 描述", "usage": "AI 权威用法"}}})
    desc_cache.CACHE_FILE.write_text(
        json.dumps({"skill::foo": {"desc": "旧缓存描述", "usage": "旧缓存用法"}},
                   ensure_ascii=False),
        encoding="utf-8",
    )

    assert desc_cache.get_usage("foo", "skill") == "AI 权威用法"


def test_ai_comment_keys_ignored(fake_env):
    """顶层 _comment 等元键被过滤：不影响查询，也不计入 count_ai_entries。"""
    _write_ai({
        "_comment": "说明文字",
        "_comment_format": "格式说明",
        "skill": {"bar": {"desc": "条目描述"}},
    })

    # 元键不进入解析结果，也不被当成工具类型
    data = desc_cache._load_ai_desc()
    assert "_comment" not in data and "_comment_format" not in data
    assert desc_cache.count_ai_entries() == 1
    assert desc_cache.get_description("bar", "skill") == "条目描述"


def test_update_merges_ai_entries(fake_env):
    """update_descriptions 空扫描结果也合并 AI 条目并落盘，随后 get 返回该值。"""
    _write_ai({"skill": {"prefill": {"desc": "AI 预填描述", "usage": "AI 预填用法"}}})

    result = desc_cache.update_descriptions([])
    assert result["updated"] >= 1, "AI 条目应计入 updated"

    data = json.loads(desc_cache.CACHE_FILE.read_text(encoding="utf-8"))
    entry = data.get("skill::prefill")
    assert isinstance(entry, dict), "AI 条目应写入 desc_cache.json"
    assert entry["desc"] == "AI 预填描述"
    assert entry.get("source") == "ai_desc"

    # 写盘后 get_description / get_usage 都返回 AI 值
    assert desc_cache.get_description("prefill", "skill") == "AI 预填描述"
    assert desc_cache.get_usage("prefill", "skill") == "AI 预填用法"


def test_corrupt_ai_file_degrades(fake_env):
    """AI 文件损坏（非法 JSON）时 get 不抛，回退到原链取值。"""
    desc_cache.AI_DESC_FILE.write_text("{{{ 不是合法 JSON", encoding="utf-8")

    # 不抛异常，且回退到原链（含中文 original）
    assert (
        desc_cache.get_description("no-such-tool", "skill", "中文原始描述")
        == "中文原始描述"
    )
    assert desc_cache.get_usage("no-such-tool", "skill") == ""
    assert desc_cache.count_ai_entries() == 0


def test_ai_entry_removed_falls_back_on_update(fake_env):
    """AI 文件删掉条目后再次 update：缓存中 source=ai_desc 记录被清，描述回退原链。"""
    # 1) AI 文件写 foo → update → 缓存有 foo 且 get 返回 AI 值
    _write_ai({"skill": {"foo": {"desc": "AI 权威文案", "usage": "AI 用法"}}})
    result = desc_cache.update_descriptions([])
    assert result["updated"] >= 1
    data = json.loads(desc_cache.CACHE_FILE.read_text(encoding="utf-8"))
    assert data["skill::foo"]["source"] == "ai_desc"
    assert desc_cache.get_description("foo", "skill") == "AI 权威文案"

    # 2) 从 AI 文件删掉 foo → 再次 update → 缓存无该 key（不再被 skip 永久残留）
    _write_ai({"skill": {}})
    desc_cache.update_descriptions([])
    data = json.loads(desc_cache.CACHE_FILE.read_text(encoding="utf-8"))
    assert "skill::foo" not in data

    # 3) get_description 回退原链：AI 空 → 缓存无 → known 无 → original 含中文
    assert desc_cache.get_description("foo", "skill", "原始中文描述") == "原始中文描述"
    assert desc_cache.get_usage("foo", "skill") == ""


def test_ai_entry_kept_survives_update(fake_env):
    """AI 文件里仍存在的条目不被回退逻辑误删。"""
    _write_ai({"skill": {"keep": {"desc": "保留的 AI 文案", "usage": "用法"}}})
    desc_cache.update_descriptions([])
    _write_ai({"skill": {"keep": {"desc": "更新后的 AI 文案", "usage": "用法"}}})
    desc_cache.update_descriptions([])

    data = json.loads(desc_cache.CACHE_FILE.read_text(encoding="utf-8"))
    assert data["skill::keep"]["source"] == "ai_desc"
    assert data["skill::keep"]["desc"] == "更新后的 AI 文案"
