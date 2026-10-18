"""批次2 app.py 修复回归测试：search limit / 中文描述 / 缓存污染 / total_calls / 二次解码"""
import json


def _make_skill(fake_env, name: str, description: str = "") -> None:
    d = fake_env.base / "skills" / name
    d.mkdir()
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n正文\n",
        encoding="utf-8",
    )


# ── #22 search：limit 截断 ──


def test_search_limit_truncates(client, fake_env):
    """search 支持 limit（默认 50、上限 200），超限截断结果。"""
    for i in range(5):
        _make_skill(fake_env, f"alpha-{i}")

    resp = client.get("/api/search", query_string={"q": "alpha", "limit": "2"})
    assert resp.status_code == 200
    assert len(resp.get_json()) == 2

    # 默认 limit=50：5 条全部返回
    resp = client.get("/api/search", query_string={"q": "alpha"})
    assert len(resp.get_json()) == 5

    # 上限 200：传 999 被封顶到 200（不报错、不截到 999 语义之外）
    resp = client.get("/api/search", query_string={"q": "alpha", "limit": "999"})
    assert resp.status_code == 200
    assert len(resp.get_json()) == 5


# ── #22 search：desc_cache 中文描述可搜 ──


def test_search_hits_desc_cache_chinese(client, fake_env):
    """原始描述无中文时，desc_cache 预置的中文描述参与匹配。"""
    _make_skill(fake_env, "cached-tool", description="english only")
    (fake_env.tmp / "desc_cache.json").write_text(json.dumps({
        "skill::cached-tool": {"desc": "用于隧道网络诊断的独特工具", "usage": "直接用"},
    }), encoding="utf-8")

    resp = client.get("/api/search", query_string={"q": "隧道"})
    assert resp.status_code == 200
    hits = resp.get_json()
    assert any(h["name"] == "cached-tool" for h in hits)


# ── #6 缓存污染回归 ──


def test_no_cache_pollution_after_skills_and_detail(client, fake_env):
    """先调 /api/skills 与 detail 后，/api/search 结果不得携带被原地写入的字段。"""
    _make_skill(fake_env, "pollute-skill", description="污染回归测试")
    plg = fake_env.base / "plugins" / "cache" / "pub" / "plg" / "1.0.0"
    # 插件的 skills 列表来自 skills/ 子目录名（_collect_skills_commands_agents）
    (plg / "skills" / "pollute-skill").mkdir(parents=True)
    (plg / "plugin.json").write_text(json.dumps({
        "name": "plg", "version": "1.0.0", "description": "污染测试插件",
    }), encoding="utf-8")

    # 1) /api/skills 的 plugin_name 写入点（bug 版原地写共享缓存）
    resp = client.get("/api/skills?refresh=1")
    assert resp.status_code == 200
    assert any(t.get("plugin_name") == "plg" for t in resp.get_json())

    # 2) detail 的 _description_cn/_usage_cn 写入点
    resp = client.get("/api/skill/pollute-skill?refresh=1")
    assert resp.status_code == 200
    assert resp.get_json().get("_description_cn")

    # 3) search 复用同一批扫描器缓存 —— 结果必须干净
    resp = client.get("/api/search", query_string={"q": "pollute"})
    hits = resp.get_json()
    assert hits, "search 应命中该技能"
    for h in hits:
        assert "_description_cn" not in h
        assert "_usage_cn" not in h
        assert "plugin_name" not in h


# ── #10 total_calls 全量求和 ──


def test_usage_stats_total_calls_full_sum(client, fake_env):
    """total_calls 是全字典求和，不是 Top30 之和。"""
    proj = fake_env.base / "projects" / "demo"
    proj.mkdir(parents=True)
    lines = [json.dumps({"type": "tool_use", "name": f"Tool{i}"}) for i in range(31)]
    (proj / "s.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    resp = client.get("/api/stats/usage?refresh=1")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["total_calls"] == 31   # Top30 之和只会是 30
    assert len(payload["top"]) == 30


# ── #20 detail 无二次 unquote ──


def test_detail_no_double_unquote(client, fake_env):
    """名字含字面 %20：Flask 已解码一次，二次 unquote 会把它变成空格导致 404。"""
    _make_skill(fake_env, "100%20off", description="字面百分号")
    resp = client.get("/api/skill/100%2520off")
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "100%20off"


# ── #19 summary：recent 分类预览语义 ──


def test_summary_recent_is_category_preview(client, fake_env):
    """扫描器条目无时间字段 → recent 标注为分类预览，且各条目带 type。"""
    _make_skill(fake_env, "s1")
    _make_skill(fake_env, "s2")

    resp = client.get("/api/summary?refresh=1")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["by_type"]["skill"] == 2
    assert "recent_note" in payload
    assert "分类预览" in payload["recent_note"]
    for r in payload["recent"]:
        assert "name" in r and "type" in r
