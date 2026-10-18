"""conftest 基建冒烟测试：client fixture 与扫描路径隔离可用"""


def test_docs_api_smoke(client):
    """/api/docs 在隔离环境下返回 200（验证 client fixture 真实可用）。"""
    resp = client.get("/api/docs")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["total"] >= 0
