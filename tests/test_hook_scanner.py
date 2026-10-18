"""Hook 扫描器测试：官方 dict 格式解析、事件表、toggle 启停、sidecar 禁用与原子写"""
import json
import os
import threading

import config
from scanners import hook_scanner


def _official_settings() -> dict:
    """官方嵌套格式样例：2 个 event、含 matcher、一组多 command、附敏感非 hooks 键。"""
    return {
        "model": "opus",
        "env": {"ANTHROPIC_AUTH_TOKEN": "sk-test-token"},
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [
                    {"type": "command", "command": "python x.py"},
                    {"type": "command", "command": "python y.py"},
                ]},
            ],
            "SessionStart": [
                {"hooks": [{"type": "command", "command": "echo hi"}]},
            ],
        },
    }


def _write_settings(fake_env, data):
    path = fake_env.base / "settings.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_scan_official_format(fake_env):
    """官方 dict 格式：逐字段解析正确、事件全在官方表内、id/name 唯一且两次扫描稳定。"""
    settings = _write_settings(fake_env, _official_settings())

    items = hook_scanner.scan_all()
    assert len(items) == 3
    assert {i["event"] for i in items} == {"PreToolUse", "SessionStart"}
    assert {i["id"] for i in items} == {"PreToolUse:0:0", "PreToolUse:0:1", "SessionStart:0:0"}
    assert {i["command"] for i in items} == {"python x.py", "python y.py", "echo hi"}

    by_id = {i["id"]: i for i in items}
    assert by_id["PreToolUse:0:0"]["matcher"] == "Bash"
    assert by_id["PreToolUse:0:0"]["command"] == "python x.py"
    assert by_id["PreToolUse:0:1"]["command"] == "python y.py"
    assert by_id["SessionStart:0:0"]["matcher"] == "*"   # matcher 缺省视为全部

    for item in items:
        assert item["event"] in config.HOOK_EVENTS       # 事件全在官方表内
        assert item["event"] != "unknown"                # 不再出现旧版的 "unknown"
        assert item["enabled"] is True                   # 在 settings.json 里就是启用
        assert item["script"] == item["command"]         # 兼容前端的 script 键
        assert item["description"] == config.HOOK_EVENT_DESCRIPTIONS[item["event"]]
        assert item["settings_path"] == str(settings)

    # blocking 由事件推导：PreToolUse 同步阻塞，SessionStart 非阻塞
    assert by_id["PreToolUse:0:0"]["blocking"] is True
    assert by_id["SessionStart:0:0"]["blocking"] is False

    # id / name 均唯一
    assert len({i["id"] for i in items}) == 3
    assert len({i["name"] for i in items}) == 3
    assert by_id["SessionStart:0:0"]["name"] == "SessionStart"   # 该 event 仅一条
    assert by_id["PreToolUse:0:0"]["name"] == "PreToolUse #1"    # 同 event 多条按序编号
    assert by_id["PreToolUse:0:1"]["name"] == "PreToolUse #2"

    # 连续两次扫描 id/name 稳定（toggle 寻址依赖此性质）
    again = hook_scanner.scan_all()
    assert [(i["id"], i["name"]) for i in again] == [(i["id"], i["name"]) for i in items]

    # 扫描不改动文件：非 hooks 键原样保留
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-test-token"


def test_event_table_official():
    """事件表：剔除 TaskStart 等 5 个虚构事件，包含官方的 UserPromptSubmit 等事件。"""
    for fake in ("TaskStart", "TaskComplete", "AgentStart", "AgentEnd", "ToolUse"):
        assert fake not in config.HOOK_EVENT_DESCRIPTIONS
        assert fake not in config.HOOK_EVENTS
    for real in ("UserPromptSubmit", "Stop", "PreCompact", "PermissionRequest", "SubagentStop"):
        assert real in config.HOOK_EVENT_DESCRIPTIONS
        assert real in config.HOOK_EVENTS
    assert set(config.HOOK_EVENTS) == set(config.HOOK_EVENT_DESCRIPTIONS)


def test_toggle_disable_restore_roundtrip(fake_env):
    """禁用后 settings 移除、scan 显示 enabled=False；启用后原位还原、sidecar 清空。"""
    settings = _write_settings(fake_env, _official_settings())
    before = json.loads(settings.read_text(encoding="utf-8"))

    # ── 禁用 ──
    assert hook_scanner.toggle_hook("PreToolUse:0:1") == {"success": True, "enabled": False}
    after_disable = json.loads(settings.read_text(encoding="utf-8"))
    grp = after_disable["hooks"]["PreToolUse"][0]
    assert grp["hooks"] == [{"type": "command", "command": "python x.py"}]  # y 已移除
    assert "python y.py" not in settings.read_text(encoding="utf-8")
    assert after_disable["hooks"]["SessionStart"] == before["hooks"]["SessionStart"]

    items = hook_scanner.scan_all()
    disabled = {i["id"]: i for i in items if i["enabled"] is False}
    assert set(disabled) == {"PreToolUse:0:1"}
    assert disabled["PreToolUse:0:1"]["command"] == "python y.py"

    sidecar = json.loads(hook_scanner.SIDECAR_FILE.read_text(encoding="utf-8"))
    assert len(sidecar["entries"]) == 1
    entry = sidecar["entries"][0]
    assert entry["event"] == "PreToolUse"
    assert entry["group_index"] == 0 and entry["hook_index"] == 1
    assert entry["hook"] == {"type": "command", "command": "python y.py"}

    # ── 启用：原位还原（matcher / 顺序不变）──
    assert hook_scanner.toggle_hook("PreToolUse:0:1") == {"success": True, "enabled": True}
    restored = json.loads(settings.read_text(encoding="utf-8"))
    grp = restored["hooks"]["PreToolUse"][0]
    assert grp["matcher"] == "Bash"
    assert [h["command"] for h in grp["hooks"]] == ["python x.py", "python y.py"]
    assert restored["hooks"]["SessionStart"] == before["hooks"]["SessionStart"]

    assert json.loads(hook_scanner.SIDECAR_FILE.read_text(encoding="utf-8"))["entries"] == []
    items = hook_scanner.scan_all()
    assert len(items) == 3 and all(i["enabled"] for i in items)


def test_disable_first_of_group_no_id_collision(fake_env):
    """禁用组内第一条：后续条目前移不得与 sidecar 条目 id 冲突（禁用项不得从列表消失）。"""
    settings = _write_settings(fake_env, _official_settings())
    assert hook_scanner.toggle_hook("PreToolUse:0:0") == {"success": True, "enabled": False}

    items = hook_scanner.scan_all()
    assert len(items) == 3                       # y 顶上 + x 禁用可见 + SessionStart
    ids = [i["id"] for i in items]
    assert len(set(ids)) == 3                    # 无 id 冲突
    disabled = [i for i in items if i["enabled"] is False]
    assert len(disabled) == 1
    assert disabled[0]["command"] == "python x.py"

    # 用禁用条目的 id 启用 → 原位还原为组内第一条
    assert hook_scanner.toggle_hook(disabled[0]["id"]) == {"success": True, "enabled": True}
    grp = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]
    assert [h["command"] for h in grp["hooks"]] == ["python x.py", "python y.py"]


def test_toggle_preserves_non_hook_keys(fake_env):
    """连续两次 toggle 后，token/model/env 等非 hooks 键值逐一相等。"""
    payload = {
        "model": "opus",
        "env": {"ANTHROPIC_AUTH_TOKEN": "sk-secret", "ANTHROPIC_BASE_URL": "http://localhost:1234"},
        "permissions": {"allow": ["Bash(git status)", "Read"], "deny": []},
        "hooks": {"Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "echo stop"}]}]},
    }
    settings = _write_settings(fake_env, payload)

    assert hook_scanner.toggle_hook("Stop:0:0") == {"success": True, "enabled": False}
    assert hook_scanner.toggle_hook("Stop:0:0") == {"success": True, "enabled": True}

    after = json.loads(settings.read_text(encoding="utf-8"))
    for key in ("model", "env", "permissions"):
        assert after[key] == payload[key]


def test_toggle_atomic_on_failure(fake_env, monkeypatch):
    """原子写失败（os.replace 抛 OSError）：success=False，主文件仍是切换前合法 JSON，无 .tmp 残留。"""
    settings = _write_settings(fake_env, _official_settings())
    before = settings.read_text(encoding="utf-8")

    def _boom(*_args, **_kwargs):
        raise OSError("模拟磁盘故障")

    monkeypatch.setattr(os, "replace", _boom)
    result = hook_scanner.toggle_hook("PreToolUse:0:0")

    assert result["success"] is False
    assert result["error"]
    assert settings.read_text(encoding="utf-8") == before   # 内容为切换前状态
    json.loads(settings.read_text(encoding="utf-8"))       # 仍是合法 JSON
    assert not list(fake_env.tmp.rglob("*.tmp"))           # 无 .tmp 残留


def test_toggle_unknown_id(fake_env, client):
    """未知 id：success=False 带 error，settings.json 与 sidecar 均不变。"""
    settings = _write_settings(fake_env, _official_settings())
    before = settings.read_text(encoding="utf-8")

    result = hook_scanner.toggle_hook("Nope:0:0")
    assert result["success"] is False
    assert result["error"]

    # API 层同样失败但 HTTP 200
    resp = client.post("/api/hooks/Nope:0:0/toggle")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is False

    assert settings.read_text(encoding="utf-8") == before
    assert not hook_scanner.SIDECAR_FILE.exists()


def test_scan_corrupt_settings(fake_env, client):
    """settings.json 损坏：scan_all 返回 []，GET /api/hooks 200 且返回 []。"""
    (fake_env.base / "settings.json").write_text(
        '{"hooks": {"PreToolUse": [oops', encoding="utf-8")

    assert hook_scanner.scan_all() == []
    resp = client.get("/api/hooks?refresh=1")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_legacy_list_format(fake_env):
    """旧扁平 list 残留：防御分支解析出条目（不崩溃），并支持 toggle 往返。"""
    settings = _write_settings(fake_env, {"hooks": [
        {"event": "PreToolUse", "script": "legacy_a.py"},
        {"hookType": "SessionStart", "scriptPath": "legacy_b.sh"},
        {"event": "Stop", "command": "echo stop"},
        "not-a-dict",                     # 非 dict → 跳过
        {"event": "NoCommand"},           # 无 command → 跳过
    ]})

    items = hook_scanner.scan_all()
    assert len(items) == 3
    assert [i["event"] for i in items] == ["PreToolUse", "SessionStart", "Stop"]
    assert [i["command"] for i in items] == ["legacy_a.py", "legacy_b.sh", "echo stop"]
    ids_before = [i["id"] for i in items]
    assert ids_before == ["PreToolUse:0:0", "SessionStart:1:0", "Stop:2:0"]
    assert len(set(ids_before)) == 3

    # 旧格式也走 sidecar 往返
    assert hook_scanner.toggle_hook(ids_before[0]) == {"success": True, "enabled": False}
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["hooks"][0]["hookType"] == "SessionStart"   # 首条被弹出（旧格式用 hookType 键）
    assert hook_scanner.toggle_hook(ids_before[0]) == {"success": True, "enabled": True}
    assert [i["id"] for i in hook_scanner.scan_all()] == ids_before


def test_sidecar_disabled_shows_in_list(fake_env):
    """手动建 sidecar：scan_all 包含 enabled=False 条目；坐标失效时启用会新建组插回。"""
    settings = _write_settings(fake_env, {
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "real.py"}]},
        ]},
    })
    hook_scanner.SIDECAR_FILE.write_text(json.dumps({"entries": [{
        "id": "Stop:3:0",
        "event": "Stop",
        "group_index": 3,
        "hook_index": 0,
        "matcher": None,
        "command": "echo disabled",
        "hook": {"type": "command", "command": "echo disabled"},
    }]}, ensure_ascii=False), encoding="utf-8")

    items = hook_scanner.scan_all()
    assert len(items) == 2
    disabled = [i for i in items if i["enabled"] is False]
    assert len(disabled) == 1
    d = disabled[0]
    assert d["id"] == "Stop:3:0"
    assert d["event"] == "Stop"
    assert d["command"] == "echo disabled"
    assert d["group_index"] == 3 and d["hook_index"] == 0
    assert d["name"] == "Stop"

    # 坐标已失效（settings 里没有 Stop 事件）→ 启用时新建 event 与组
    assert hook_scanner.toggle_hook("Stop:3:0") == {"success": True, "enabled": True}
    data = json.loads(settings.read_text(encoding="utf-8"))
    group = data["hooks"]["Stop"][0]
    assert group["hooks"] == [{"type": "command", "command": "echo disabled"}]
    assert "matcher" not in group                            # 记录 matcher 为 None → 新组省略
    assert json.loads(hook_scanner.SIDECAR_FILE.read_text(encoding="utf-8"))["entries"] == []


def test_backup_created_once(fake_env):
    """首次 toggle 前创建 settings.json.cc-toolbox.bak 且内容=切换前；再次 toggle 不覆盖。"""
    settings = _write_settings(fake_env, _official_settings())
    raw_before = settings.read_text(encoding="utf-8")
    bak = settings.with_name(settings.name + ".cc-toolbox.bak")
    assert not bak.exists()

    assert hook_scanner.toggle_hook("SessionStart:0:0")["success"] is True
    assert bak.exists()
    assert bak.read_text(encoding="utf-8") == raw_before

    assert hook_scanner.toggle_hook("SessionStart:0:0")["success"] is True
    assert bak.read_text(encoding="utf-8") == raw_before                    # 未被覆盖
    assert json.loads(settings.read_text(encoding="utf-8")) == json.loads(raw_before)  # 已还原


def test_toggle_concurrent_different_ids(fake_env):
    """I1 回归：并发 toggle 两条不同 id，写锁串行化 → 两请求均成功且 settings 中两条都被移除。"""
    settings = _write_settings(fake_env, _official_settings())

    barrier = threading.Barrier(2, timeout=5)
    results = {}
    errors = []

    def run(item_id: str):
        try:
            barrier.wait(timeout=5)
            results[item_id] = hook_scanner.toggle_hook(item_id)
        except Exception as exc:  # 收集线程内异常，避免 excepthook 吞掉根因
            errors.append((item_id, exc))

    ids = ("PreToolUse:0:0", "PreToolUse:0:1")
    threads = [threading.Thread(target=run, args=(i,)) for i in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not any(t.is_alive() for t in threads), "并发线程超时未结束（toggle 写锁卡死？）"
    assert not errors, f"线程内出现异常：{errors}"
    assert results["PreToolUse:0:0"] == {"success": True, "enabled": False}
    assert results["PreToolUse:0:1"] == {"success": True, "enabled": False}

    text = settings.read_text(encoding="utf-8")
    data = json.loads(text)
    # 两条均被禁用（移出 settings.json）：组空删组 → event 空删 event
    assert "PreToolUse" not in data.get("hooks", {})
    assert "python x.py" not in text and "python y.py" not in text
    # sidecar 保留两条禁用记录
    entries = json.loads(hook_scanner.SIDECAR_FILE.read_text(encoding="utf-8"))["entries"]
    assert {e["command"] for e in entries} == {"python x.py", "python y.py"}


def test_sidecar_failure_rolls_back_settings(fake_env, monkeypatch):
    """I3 回归：sidecar 写失败 → 用 old_text 原子回滚 settings（第二道数据安全防线）。"""
    settings = _write_settings(fake_env, _official_settings())
    before = settings.read_text(encoding="utf-8")

    real_atomic_write = hook_scanner._atomic_write

    def selective_boom(path, text):
        # 仅 sidecar 写入抛错，其余（备份 / 写 settings / 回滚）透传真实实现
        if path == hook_scanner.SIDECAR_FILE:
            raise OSError("模拟 sidecar 写失败")
        return real_atomic_write(path, text)

    monkeypatch.setattr(hook_scanner, "_atomic_write", selective_boom)

    result = hook_scanner.toggle_hook("PreToolUse:0:0")
    assert result["success"] is False
    assert "sidecar" in result["error"]                # error 文案提及 sidecar
    assert settings.read_text(encoding="utf-8") == before   # settings 已回滚为切换前
    json.loads(settings.read_text(encoding="utf-8"))        # 仍是合法 JSON
    assert not list(fake_env.tmp.rglob("*.tmp"))            # 无 .tmp 残留


def test_enable_appends_to_same_matcher_when_coord_stale(fake_env):
    """M1 分支①：坐标失效但同 event 内存在同 matcher 组 → append 到该组尾部（不新建）。"""
    settings = _write_settings(fake_env, {
        "hooks": {"PreToolUse": [
            {"matcher": "Edit", "hooks": [{"type": "command", "command": "a.py"}]},
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "b.py"}]},
        ]},
    })
    hook_scanner.SIDECAR_FILE.write_text(json.dumps({"entries": [{
        "id": "PreToolUse:9:0",          # group_index=9 越界 → 坐标失效
        "event": "PreToolUse",
        "group_index": 9,
        "hook_index": 0,
        "matcher": "Bash",               # 同 matcher 组存在（组 1）
        "command": "echo target",
        "hook": {"type": "command", "command": "echo target"},
    }]}, ensure_ascii=False), encoding="utf-8")

    assert hook_scanner.toggle_hook("PreToolUse:9:0") == {"success": True, "enabled": True}
    groups = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    assert len(groups) == 2                                   # 未新建组
    assert [h["command"] for h in groups[1]["hooks"]] == ["b.py", "echo target"]  # append 尾部
    assert groups[0]["hooks"] == [{"type": "command", "command": "a.py"}]         # 另一组不动
    assert json.loads(hook_scanner.SIDECAR_FILE.read_text(encoding="utf-8"))["entries"] == []


def test_enable_new_group_keeps_matcher(fake_env):
    """M1 分支②：坐标失效且无同 matcher 组 → 新建组，matcher 非 None 时保留 matcher 键。"""
    settings = _write_settings(fake_env, {
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "b.py"}]},
        ]},
    })
    hook_scanner.SIDECAR_FILE.write_text(json.dumps({"entries": [{
        "id": "PreToolUse:7:0",           # group_index=7 越界 → 坐标失效
        "event": "PreToolUse",
        "group_index": 7,
        "hook_index": 0,
        "matcher": "Write",               # 组内无同 matcher → 走新建
        "command": "echo target",
        "hook": {"type": "command", "command": "echo target"},
    }]}, ensure_ascii=False), encoding="utf-8")

    assert hook_scanner.toggle_hook("PreToolUse:7:0") == {"success": True, "enabled": True}
    groups = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    assert len(groups) == 2
    assert groups[1]["matcher"] == "Write"                    # matcher 非 None → 保留键
    assert groups[1]["hooks"] == [{"type": "command", "command": "echo target"}]
    assert json.loads(hook_scanner.SIDECAR_FILE.read_text(encoding="utf-8"))["entries"] == []
