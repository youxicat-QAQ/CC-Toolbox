"""paths_config 路径配置系统测试"""
import json
import os

import paths_config


def test_load_missing_file_returns_empty(fake_env):
    """配置文件缺失时 get_config 返回空结构且不抛。"""
    cfg = paths_config.get_config()
    assert cfg == {}  # 文件不存在时 _load 返回 {}
    assert cfg.get("skill_paths", []) == []
    assert cfg.get("cli_paths", []) == []
    assert cfg.get("extra_mcp_project_dirs", []) == []


def test_corrupt_file_returns_empty(fake_env, tmp_path):
    """非法 JSON 时 get_config 不抛，按空配置处理。"""
    paths_config.PATHS_CONFIG_FILE.write_text("{ not valid json", encoding="utf-8")
    cfg = paths_config.get_config()
    assert cfg == {}


def test_update_and_merged(fake_env, tmp_path):
    """update_group 后 get_merged_skill_paths 含默认项与自定义项。"""
    custom = tmp_path / "myskills"
    custom.mkdir()
    paths_config.update_group("skill_paths", [str(custom)])

    merged = [str(p) for p in paths_config.get_merged_skill_paths()]
    import config as _config
    # 默认项（fake_env monkeypatch 的 config.SKILL_PATHS）在前，自定义项在后
    assert str(_config.SKILL_PATHS[0]) in merged
    assert str(custom) in merged
    assert merged.index(str(_config.SKILL_PATHS[0])) < merged.index(str(custom))


def test_api_paths_crud(client, fake_env):
    """GET 默认返回 defaults；POST 更新后 GET 反映；非法 group → 400。"""
    r = client.get("/api/paths")
    assert r.status_code == 200
    data = r.get_json()
    assert "defaults" in data
    assert "skill" in data["defaults"]
    assert "cli" in data["defaults"]

    # POST 更新 skill_paths
    r = client.post("/api/paths", json={
        "group": "skill_paths", "paths": [str(fake_env.tmp / "extra-skills")],
    })
    assert r.status_code == 200
    assert r.get_json()["success"] is True

    # GET 反映自定义项
    r = client.get("/api/paths")
    data = r.get_json()
    assert str(fake_env.tmp / "extra-skills") in data["merged"]["skill"]

    # 非法 group → 400
    r = client.post("/api/paths", json={"group": "bogus", "paths": []})
    assert r.status_code == 400
    assert r.get_json()["success"] is False


def test_load_filters_non_string_elements_no_500(client, fake_env):
    """手改配置混入 null/数字/空串时被 _load 过滤，接口仍 200 不全站 500。"""
    paths_config.PATHS_CONFIG_FILE.write_text(
        json.dumps({"skill_paths": ["D:/x", None, 5, "", "  "]}),
        encoding="utf-8",
    )
    # 元素级过滤：只保留 strip 后非空的 str
    cfg = paths_config.get_config()
    assert cfg["skill_paths"] == ["D:/x"]
    # 合并路径不因坏元素抛 TypeError（Path(None) 场景）
    assert any(str(p).replace("\\", "/") == "D:/x"
               for p in paths_config.get_merged_skill_paths())

    assert client.get("/api/paths").status_code == 200
    assert client.get("/api/skills?refresh=1").status_code == 200


def test_open_rejects_unconfigured(client, fake_env):
    """未配置的路径 → 403（在 startfile 之前）。"""
    r = client.post("/api/paths/open", json={"path": "C:/Windows"})
    assert r.status_code == 403
    assert r.get_json()["success"] is False


def test_open_allows_configured(client, fake_env, monkeypatch, tmp_path):
    """已配置路径 → 200；monkeypatch os.startfile 防真打开。"""
    calls = []
    monkeypatch.setattr(os, "startfile", lambda p: calls.append(p), raising=False)

    target = tmp_path / "opendir"
    target.mkdir()
    paths_config.update_group("skill_paths", [str(target)])

    r = client.post("/api/paths/open", json={"path": str(target)})
    assert r.status_code == 200
    assert r.get_json()["success"] is True
    assert calls and calls[0] == str(target)


def test_reset_ai_desc_missing_example(client, fake_env, monkeypatch, tmp_path):
    """应用目录无 ai_descriptions.example.json 时 → 404。

    示例文件现已随应用发布（真实存在于应用目录），指向 tmp 空目录以隔离覆盖 404 分支。
    """
    import app as app_module
    monkeypatch.setattr(
        app_module, "AI_DESC_EXAMPLE_FILE", tmp_path / "ai_descriptions.example.json"
    )
    r = client.post("/api/paths/reset-ai-desc")
    assert r.status_code == 404
    assert r.get_json()["success"] is False
