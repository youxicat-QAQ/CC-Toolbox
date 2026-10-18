"""desc_cache 单元测试：回退链 / 内存缓存 / 原子写 / 并发安全 / 损坏容错"""
import json
import threading

import pytest

import desc_cache


def _make_entries(count: int, prefix: str = "tool") -> dict:
    """生成 count 条完整的缓存条目（desc + usage 均非空）。"""
    return {
        f"skill::{prefix}{i}": {"desc": f"描述{i}", "usage": f"用法{i}"}
        for i in range(count)
    }


def test_get_falls_back_to_known(fake_env):
    """CACHE_FILE 不存在时，应回退到 _KNOWN_DETAILED 预定义映射。"""
    key = "skill::pdf"
    assert key in desc_cache._KNOWN_DETAILED, "测试数据前提：skill::pdf 必须存在"
    assert not desc_cache.CACHE_FILE.exists()

    assert (
        desc_cache.get_description("pdf", "skill")
        == desc_cache._KNOWN_DETAILED[key]["desc"]
    )
    assert (
        desc_cache.get_usage("pdf", "skill")
        == desc_cache._KNOWN_DETAILED[key]["usage"]
    )


def test_cache_hit_no_reparse(fake_env, monkeypatch):
    """文件未变化时命中内存缓存，第二次调用不再 json.loads。"""
    desc_cache.CACHE_FILE.write_text(
        json.dumps(_make_entries(100), ensure_ascii=False), encoding="utf-8"
    )

    original_loads = json.loads
    calls = {"n": 0}

    def counting_loads(*args, **kwargs):
        calls["n"] += 1
        return original_loads(*args, **kwargs)

    monkeypatch.setattr(desc_cache.json, "loads", counting_loads)

    calls["n"] = 0
    desc_cache.get_description("tool0", "skill")
    first = calls["n"]

    calls["n"] = 0
    desc_cache.get_description("tool1", "skill")
    second = calls["n"]

    assert first <= 1, f"首次加载最多解析一次，实际 {first} 次"
    assert second == 0, f"缓存命中不应再解析，实际 {second} 次"


def test_save_atomic_on_failure(fake_env, monkeypatch):
    """os.replace 失败时，原缓存文件必须保持完整且不残留 .tmp。"""
    original = _make_entries(5, prefix="exist")
    desc_cache.CACHE_FILE.write_text(
        json.dumps(original, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    def failing_replace(src, dst):
        raise OSError("模拟磁盘故障")

    monkeypatch.setattr(desc_cache.os, "replace", failing_replace)

    new_cache = {**original, "skill::brand_new": {"desc": "新条目", "usage": "新用法"}}
    with pytest.raises(OSError):
        desc_cache._save_cache(new_cache)

    data = json.loads(desc_cache.CACHE_FILE.read_text(encoding="utf-8"))
    assert len(data) == 5, "失败后原文件条数必须不变"
    assert "skill::brand_new" not in data

    tmp = desc_cache.CACHE_FILE.with_name(desc_cache.CACHE_FILE.name + ".tmp")
    assert not tmp.exists(), "失败后不应残留 .tmp 文件"


def test_update_concurrent_no_loss(fake_env):
    """两个并发 update_descriptions 不能互相覆盖（读-改-写需整体加锁）。"""
    desc_cache.CACHE_FILE.write_text(
        json.dumps(_make_entries(100, prefix="base"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    barrier = threading.Barrier(2, timeout=5)
    results = {}
    errors = []

    def run(tag: str):
        try:
            # 未知工具走「原始描述含中文」/模板分支，确保一定会写入
            tools = [
                {"_type": "skill", "name": f"{tag}-skill-{i}", "description": f"中文描述 {tag} {i}"}
                for i in range(10)
            ]
            barrier.wait(timeout=5)
            results[tag] = desc_cache.update_descriptions(tools)
        except Exception as exc:  # 收集线程内异常，避免 excepthook 吞掉根因
            errors.append((tag, exc))

    threads = [threading.Thread(target=run, args=(t,)) for t in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not any(t.is_alive() for t in threads), "并发线程超时未结束（barrier/update 卡死）"
    assert not errors, f"线程内出现异常：{errors}"

    data = json.loads(desc_cache.CACHE_FILE.read_text(encoding="utf-8"))
    assert len(data) == 120, f"预置 100 + 两线程各 10 应为 120，实际 {len(data)}"
    assert results["a"]["updated"] == 10
    assert results["b"]["updated"] == 10


def test_update_concurrent_same_key(fake_env):
    """两线程同时更新相同 key：加锁后条目应完整且不损坏文件。"""
    desc_cache.CACHE_FILE.write_text(
        json.dumps({"skill::same": {"desc": "旧描述"}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    barrier = threading.Barrier(2, timeout=5)
    errors = []

    def run(tag: str):
        try:
            tools = [{"_type": "skill", "name": "same", "description": f"中文描述 {tag}"}]
            barrier.wait(timeout=5)
            desc_cache.update_descriptions(tools)
        except Exception as exc:
            errors.append((tag, exc))

    threads = [threading.Thread(target=run, args=(t,)) for t in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not any(t.is_alive() for t in threads), "并发线程超时未结束"
    assert not errors, f"线程内出现异常：{errors}"

    data = json.loads(desc_cache.CACHE_FILE.read_text(encoding="utf-8"))
    entry = data.get("skill::same")
    assert isinstance(entry, dict), f"相同 key 条目应为对象，实际 {entry!r}"
    assert entry.get("desc"), "desc 不应为空"
    assert entry.get("usage"), "usage 不应为空"


def test_update_save_failure_keeps_old_memory(fake_env, monkeypatch):
    """I-1 回归：预热内存后 os.replace 失败，get 必须返回旧值而非就地改出的幽灵新值。"""
    # 条目缺 usage → update 不会 skip，必然走到写盘路径
    desc_cache.CACHE_FILE.write_text(
        json.dumps({"skill::x": {"desc": "旧描述"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    # 预热：数据进入 _mem["data"]（活对象）
    assert desc_cache.get_description("x", "skill") == "旧描述"

    def failing_replace(src, dst):
        raise OSError("模拟磁盘故障")

    monkeypatch.setattr(desc_cache.os, "replace", failing_replace)

    tools = [{"_type": "skill", "name": "x", "description": "中文新描述"}]
    with pytest.raises(OSError):
        desc_cache.update_descriptions(tools)

    # 磁盘未变，内存也不允许被就地改脏（否则命中幽灵数据直到重启）
    assert desc_cache.get_description("x", "skill") == "旧描述"
    assert desc_cache.get_usage("x", "skill") == ""
    data = json.loads(desc_cache.CACHE_FILE.read_text(encoding="utf-8"))
    assert data["skill::x"]["desc"] == "旧描述", "磁盘文件不应被修改"


def test_non_dict_entry_does_not_raise(fake_env):
    """I-2 回归：缓存值为非 dict 脏数据时，get 不应抛 AttributeError。"""
    desc_cache.CACHE_FILE.write_text(
        json.dumps({"skill::y": "oops"}, ensure_ascii=False), encoding="utf-8"
    )

    assert desc_cache.get_description("y", "skill") == ""
    assert desc_cache.get_usage("y", "skill") == ""


def test_corrupt_file_parses_once_per_version(fake_env, monkeypatch):
    """I-3 回归：损坏文件热路径只解析一次，第二次 get 不再 json.loads。"""
    desc_cache.CACHE_FILE.write_text(
        json.dumps(_make_entries(5, prefix="warm"), ensure_ascii=False), encoding="utf-8"
    )
    # 预热合法数据进内存
    assert desc_cache.get_description("warm0", "skill") == "描述0"

    # 改成损坏内容（stat 变化触发重读）
    desc_cache.CACHE_FILE.write_text("{{{ 不是合法 JSON", encoding="utf-8")

    original_loads = json.loads
    calls = {"n": 0}

    def counting_loads(*args, **kwargs):
        calls["n"] += 1
        return original_loads(*args, **kwargs)

    monkeypatch.setattr(desc_cache.json, "loads", counting_loads)

    calls["n"] = 0
    assert desc_cache.get_description("warm0", "skill") == "描述0", "损坏后应保留内存旧数据"
    first = calls["n"]

    calls["n"] = 0
    assert desc_cache.get_description("warm1", "skill") == "描述1"
    second = calls["n"]

    assert first == 1, f"同一损坏版本首次 get 应解析一次，实际 {first} 次"
    assert second == 0, f"同一损坏版本第二次 get 不应再解析，实际 {second} 次"


def test_corrupt_file_keeps_memory(fake_env):
    """缓存文件损坏时保留内存中的旧数据，不清空。"""
    desc_cache.CACHE_FILE.write_text(
        json.dumps(_make_entries(10, prefix="keep"), ensure_ascii=False),
        encoding="utf-8",
    )

    # 首次读取，数据进入内存缓存
    assert desc_cache.get_description("keep5", "skill") == "描述5"

    # 把文件写成非法 JSON
    desc_cache.CACHE_FILE.write_text("{{{ 不是合法 JSON", encoding="utf-8")

    assert desc_cache.get_description("keep5", "skill") == "描述5"
    assert desc_cache.get_usage("keep5", "skill") == "用法5"
