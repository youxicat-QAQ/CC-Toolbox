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
    """search 支持 limit（默认 50、上限 200），超限截断结果（响应为对象形态）。"""
    for i in range(5):
        _make_skill(fake_env, f"alpha-{i}")

    resp = client.get("/api/search", query_string={"q": "alpha", "limit": "2"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["results"]) == 2
    assert data["truncated"] is True          # 5 条 > limit 2
    assert data["total_matched"] == 5         # limit 截断前的匹配总数

    # 默认 limit=50：5 条全部返回
    resp = client.get("/api/search", query_string={"q": "alpha"})
    data = resp.get_json()
    assert len(data["results"]) == 5
    assert data["truncated"] is False

    # 上限 200：传 999 被封顶到 200（不报错、不截到 999 语义之外）
    resp = client.get("/api/search", query_string={"q": "alpha", "limit": "999"})
    assert resp.status_code == 200
    assert len(resp.get_json()["results"]) == 5


def test_search_per_type_quota_keeps_small_classes(client, fake_env, monkeypatch):
    """每类独立配额：大类不把小类整类挤出，响应带 truncated / total_matched。"""
    import app as app_module

    # skills 60 条、commands 60 条都含关键词，其余类为空
    monkeypatch.setattr(app_module, "scan_skills", lambda force=False: [
        {"name": f"q-skill-{i}", "description": "contains q"} for i in range(60)
    ])
    monkeypatch.setattr(app_module, "scan_commands", lambda force=False: [
        {"name": f"q-cmd-{i}", "description": "contains q"} for i in range(60)
    ])
    for fn in ("scan_mcp_servers", "scan_cli_tools", "scan_hooks", "scan_plugins"):
        monkeypatch.setattr(app_module, fn, lambda force=False: [])

    # limit=50：不再被 skills 整类占据，两类都有条目
    resp = client.get("/api/search", query_string={"q": "q"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["truncated"] is True
    assert len(data["results"]) == 50
    types = {r["type"] for r in data["results"]}
    assert "skill" in types and "command" in types
    # total_matched = 各类收集数之和（每类封顶 per_cap=50 → 100；真实值 120 的下限估计）
    assert data["total_matched"] >= len(data["results"])

    # limit=200：两类全部装下 → 不截断，total_matched 为准确值 120
    resp = client.get("/api/search", query_string={"q": "q", "limit": "200"})
    data = resp.get_json()
    assert data["truncated"] is False
    assert data["total_matched"] == 120
    assert len(data["results"]) == 120


# ── #22 search：desc_cache 中文描述可搜 ──


def test_search_hits_desc_cache_chinese(client, fake_env):
    """原始描述无中文时，desc_cache 预置的中文描述参与匹配。"""
    _make_skill(fake_env, "cached-tool", description="english only")
    (fake_env.tmp / "desc_cache.json").write_text(json.dumps({
        "skill::cached-tool": {"desc": "用于隧道网络诊断的独特工具", "usage": "直接用"},
    }), encoding="utf-8")

    resp = client.get("/api/search", query_string={"q": "隧道"})
    assert resp.status_code == 200
    hits = resp.get_json()["results"]
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
    hits = resp.get_json()["results"]
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


# ── 纵深防御：search 对漏网非 str 字段不 500 ──


def test_search_survives_non_string_name_and_description(client, fake_env, monkeypatch):
    """扫描器漏网 description=123 / name=None 时 /api/search 仍 200。"""
    import app as app_module

    monkeypatch.setattr(app_module, "scan_skills", lambda force=False: [
        {"name": None, "description": 123},
        {"name": 999, "description": None},
    ])
    for fn in ("scan_mcp_servers", "scan_cli_tools", "scan_hooks",
               "scan_plugins", "scan_commands"):
        monkeypatch.setattr(app_module, fn, lambda force=False: [])

    resp = client.get("/api/search", query_string={"q": "x"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data["results"], list)
    assert data["truncated"] is False


# ── _build_plugin_index 吃 force：?refresh=1 连插件关联一起强刷 ──


def test_skills_refresh_rebuilds_plugin_index(client, fake_env):
    """预热插件缓存为空后新增插件 → GET /api/skills?refresh=1 应带上 plugin_name。"""
    # 预热：空插件扫描结果写入 120s TTL 缓存
    resp = client.get("/api/plugins")
    assert resp.status_code == 200
    assert resp.get_json() == []

    # 预热之后再新增技能 + 带该技能的插件
    _make_skill(fake_env, "plugged-skill", description="被插件关联的技能")
    plg = fake_env.base / "plugins" / "cache" / "pub" / "newplg" / "1.0.0"
    (plg / "skills" / "plugged-skill").mkdir(parents=True)
    (plg / "plugin.json").write_text(json.dumps({
        "name": "newplg", "version": "1.0.0", "description": "后加的插件",
    }), encoding="utf-8")

    resp = client.get("/api/skills?refresh=1")
    assert resp.status_code == 200
    data = resp.get_json()
    hit = next((s for s in data if s.get("name") == "plugged-skill"), None)
    assert hit is not None, "技能应出现在 /api/skills"
    # 不吃旧缓存：插件关联必须随 refresh 一起重建
    assert hit.get("plugin_name") == "newplg"
