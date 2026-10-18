"""/api/export 导出端点测试：Markdown 必须返回真 Markdown，JSON 分支保持不变"""
import json
import re


def _make_skill(fake_env):
    """在隔离 skills 目录下造一个带 frontmatter 的技能 foo。"""
    skill_dir = fake_env.base / "skills" / "foo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: foo\ndescription: 测试用技能描述\n---\n\n正文内容\n",
        encoding="utf-8",
    )
    return skill_dir


def test_export_markdown_is_markdown(client, fake_env):
    """Markdown 导出：200 + text/markdown + 正文以 # 开头（不是 JSON 数组）。"""
    _make_skill(fake_env)
    resp = client.get("/api/export?format=markdown")
    assert resp.status_code == 200
    ct = resp.headers["Content-Type"]
    assert ct.startswith("text/markdown")
    # Werkzeug 对 text/* 只补一个 charset；mimetype 里手写 charset 会导致重复
    assert ct.count("charset") == 1
    text = resp.get_data(as_text=True)
    # 首字符必须是 Markdown 标题，而不是 JSON 数组/对象的 [ 或 {
    assert text.startswith("# CC-Toolbox")
    assert "foo" in text
    # 分割线前必须有空行，否则 setext 规则会把 meta 段吞成 h2，--- 不渲染
    assert "\n\n---" in text


def test_export_markdown_escapes_pipes(client, fake_env):
    """Markdown 导出：单元格内竖线被转义（名称列与描述列都转义），表格行分隔结构仍完整。"""
    (fake_env.tmp / ".claude.json").write_text(
        json.dumps({"mcpServers": {"a|b": {"command": "x", "args": []}}}),
        encoding="utf-8",
    )
    # 再造一个 description 列里带竖线的技能，验证 desc 列同样被转义
    skill_dir = fake_env.base / "skills" / "bar"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: bar\ndescription: 描述含竖线 x|y 测试\n---\n\n正文\n",
        encoding="utf-8",
    )
    resp = client.get("/api/export?format=markdown&refresh=1")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    # 名称列（MCP 名 a|b）与描述列（技能描述 x|y）都被转义
    assert "a\\|b" in text
    assert "x\\|y" in text
    # 取出包含该工具的表格数据行，验证结构没被未转义竖线撑坏
    row = next(line for line in text.splitlines() if "a\\|b" in line)
    # 未转义的 | 应恰好 3 个：| 名称 | 描述 |（单元格内的竖线已被转义，不参与分列）
    assert len(re.findall(r"(?<!\\)\|", row)) == 3
    assert row.startswith("| ") and row.rstrip("\n").endswith("|")


def test_export_json_regression(client):
    """JSON 导出回归：仍返回 application/json，且含 total 与 tools。"""
    resp = client.get("/api/export?format=json")
    assert resp.status_code == 200
    assert "json" in resp.headers["Content-Type"]
    payload = resp.get_json()
    assert payload is not None
    assert "total" in payload
    assert "tools" in payload


def test_export_markdown_download_header(client, fake_env):
    """Markdown 导出：Content-Disposition 为附件下载且文件名前缀正确。"""
    _make_skill(fake_env)
    resp = client.get("/api/export?format=markdown")
    cd = resp.headers.get("Content-Disposition", "")
    assert "attachment" in cd
    assert "cc-toolbox-export-" in cd
