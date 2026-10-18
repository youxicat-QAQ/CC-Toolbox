"""CC-Toolbox — Claude Code 工具箱管理器"""
import logging
import os
import sys
import time
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

# 统一应用日志格式（#21）；若 root handler 已存在（如测试环境），basicConfig 为 no-op
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("cc-toolbox")

import config
from desc_cache import count_ai_entries, get_description, get_usage, update_descriptions
from scanners import (
    scan_skills, scan_mcp_servers, scan_cli_tools,
    scan_hooks, scan_plugins, scan_commands,
)
from scanners.stats_scanner import get_usage_stats

app = Flask(__name__)

# ── 页面路由 ──────────────────────────────────

@app.route("/")
def dashboard():
    return render_template("dashboard.html", active="dashboard")


@app.route("/<tool_type>")
def tool_list(tool_type: str):
    valid = {"skills", "mcp", "cli", "hooks", "plugins", "commands"}
    if tool_type not in valid:
        return render_template("error.html", message="未知的工具类型"), 404
    return render_template("list.html", tool_type=tool_type,
                         type_labels=_TYPE_LABELS, type_icons=_TYPE_ICONS,
                         active=tool_type)


@app.route("/search")
def search_page():
    return render_template("search.html", active="search")


@app.route("/docs")
def docs_page():
    return render_template("docs.html", active="docs")


@app.route("/settings")
def settings_page():
    # paths_dir 供模板拼出用户数据文件绝对路径（paths_config.json / ai_descriptions.json）
    return render_template("settings.html", active="settings",
                           paths_dir=str(Path(__file__).parent))


# ── 工具详情页 ──────────────────────────────

@app.route("/detail/<tool_type>/<path:name>")
def tool_detail_page(tool_type: str, name: str):
    valid = {"skill", "mcp", "cli", "hook", "plugin", "command"}
    if tool_type not in valid:
        return render_template("error.html", message="未知的工具类型"), 404

    # 构建复数映射供面包屑使用
    _PLURAL_MAP = {"skill":"skills","mcp":"mcp","cli":"cli","hook":"hooks","plugin":"plugins","command":"commands"}
    return render_template("detail.html",
                          tool_type=tool_type,
                          tool_name=name,
                          type_labels=_TYPE_LABELS,
                          type_icons=_TYPE_ICONS,
                          plural_map=_PLURAL_MAP,
                          active=_PLURAL_MAP[tool_type])


# ── API 路由 ──────────────────────────────────

@app.route("/api/summary")
def api_summary():
    force = request.args.get("refresh") == "1"
    # 构造时即带上 type（与 /api/search 一致），不再依赖启发式 _detect_type 判型（#19）
    skills = [{**s, "type": "skill"} for s in scan_skills(force)]
    mcp = [{**m, "type": "mcp"} for m in scan_mcp_servers(force)]
    cli = [{**c, "type": "cli"} for c in scan_cli_tools(force)]
    hooks = [{**h, "type": "hook"} for h in scan_hooks(force)]
    plugins = [{**p, "type": "plugin"} for p in scan_plugins(force)]
    commands = [{**c, "type": "command"} for c in scan_commands(force)]

    groups = [skills, mcp, cli, hooks, plugins, commands]
    all_tools = skills + mcp + cli + hooks + plugins + commands

    # 扫描器条目没有 mtime/created 字段，无法按时间排序；
    # recent 语义改为「分类预览」：各类按扫描顺序轮转取前 10 项（避免全是第一个分类）
    preview = []
    round_i = 0
    while len(preview) < 10:
        progressed = False
        for g in groups:
            if round_i < len(g):
                preview.append(g[round_i])
                progressed = True
                if len(preview) >= 10:
                    break
        if not progressed:
            break
        round_i += 1

    return jsonify({
        "total": len(all_tools),
        "by_type": {
            "skill": len(skills),
            "mcp": len(mcp),
            "cli": len(cli),
            "hook": len(hooks),
            "plugin": len(plugins),
            "command": len(commands),
        },
        "recent": [
            {"name": t["name"], "type": t["type"]}
            for t in preview
        ],
        "recent_note": "分类预览前 10 项（各分类轮转，非按时间排序）",
    })


@app.route("/api/skills")
def api_skills():
    force = request.args.get("refresh") == "1"
    skills = scan_skills(force)
    plugin_idx = _build_plugin_index()
    # 构造新 dict，避免原地写扫描器共享缓存污染后续响应（#6）
    result = []
    for s in skills:
        pname = plugin_idx.get(s.get("name", ""))
        if pname:
            result.append({**s, "plugin_name": pname})
        else:
            result.append({**s})
    return jsonify(result)


@app.route("/api/mcp")
def api_mcp():
    return jsonify(scan_mcp_servers(request.args.get("refresh") == "1"))


@app.route("/api/cli")
def api_cli():
    return jsonify(scan_cli_tools(request.args.get("refresh") == "1"))


@app.route("/api/hooks")
def api_hooks():
    return jsonify(scan_hooks(request.args.get("refresh") == "1"))


@app.route("/api/plugins")
def api_plugins():
    return jsonify(scan_plugins(request.args.get("refresh") == "1"))


@app.route("/api/commands")
def api_commands():
    return jsonify(scan_commands(request.args.get("refresh") == "1"))


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip().lower()
    if not q:
        return jsonify([])

    # 结果上限：默认 50、封顶 200（#22）
    limit = request.args.get("limit", default=50, type=int)
    if not limit or limit <= 0:
        limit = 50
    limit = min(limit, 200)

    force = request.args.get("refresh") == "1"
    results = []
    for scanner, ttype in [
        (scan_skills, "skill"), (scan_mcp_servers, "mcp"),
        (scan_cli_tools, "cli"), (scan_hooks, "hook"),
        (scan_plugins, "plugin"), (scan_commands, "command"),
    ]:
        for item in scanner(force):
            # 名称 / 原始描述 / desc_cache 中文描述 三路匹配（desc_cache 为内存缓存，stat 命中，可接受）
            cn_desc = get_description(item.get("name", ""), ttype,
                                      item.get("description", ""))
            if (q in item.get("name", "").lower()
                    or q in item.get("description", "").lower()
                    or q in (cn_desc or "").lower()):
                results.append({**item, "type": ttype})
                if len(results) >= limit:
                    return jsonify(results)

    return jsonify(results)


# ── 工具文档 API ──────────────────────────────

_USAGE_GUIDE = {
    "skill": "在对话中提及相关场景时自动触发，也可在输入框中输入 /技能名 手动调用",
    "mcp": "通过 MCP 协议自动调用，Claude 会根据需要选择合适的 MCP 服务",
    "cli": "在终端中输入命令名即可使用，如：命令名 --help",
    "hook": "配置后自动触发，无需手动操作",
    "plugin": "安装后自动生效，其中的技能/命令可直接使用",
    "command": "在对话中输入 /命令名 即可执行",
}

def _enrich_with_desc(items: list, type_key: str) -> list:
    """为工具列表添加中文描述和用法。"""
    result = []
    for item in items:
        name = item.get("name", "")
        cn_desc = get_description(name, type_key, item.get("description", ""))
        cn_usage = get_usage(name, type_key)
        result.append({
            **item,
            "_description_cn": cn_desc or item.get("description", "") or "暂无描述",
            "_usage_cn": cn_usage,
        })
    return result

@app.route("/api/docs")
def api_docs():
    force = request.args.get("refresh") == "1"
    ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time()))
    groups = [
        ("skill", "技能", "📦", _enrich_with_desc(scan_skills(force), "skill")),
        ("mcp", "MCP 服务", "🔌", _enrich_with_desc(scan_mcp_servers(force), "mcp")),
        ("cli", "命令行工具", "🖥️", _enrich_with_desc(scan_cli_tools(force), "cli")),
        ("hook", "钩子脚本", "⚡", _enrich_with_desc(scan_hooks(force), "hook")),
        ("plugin", "插件", "🔧", _enrich_with_desc(scan_plugins(force), "plugin")),
        ("command", "斜杠命令", "📝", _enrich_with_desc(scan_commands(force), "command")),
    ]
    return jsonify({
        "timestamp": ts,
        "total": sum(len(g[3]) for g in groups),
        # ai_descriptions.json 中已填写的工具描述条数（0 = 未配置）
        "ai_desc_count": count_ai_entries(),
        "groups": [
            {"type":k,"label":l,"icon":i,"count":len(d),"usage":_USAGE_GUIDE.get(k,""),"items":d}
            for k,l,i,d in groups
        ],
    })


@app.route("/api/update-descriptions", methods=["POST"])
def api_update_descriptions():
    """扫描并更新所有工具的中文描述。"""
    force = True
    all_tools = []
    for scanner, ttype in [
        (scan_skills, "skill"), (scan_mcp_servers, "mcp"),
        (scan_cli_tools, "cli"), (scan_hooks, "hook"),
        (scan_plugins, "plugin"), (scan_commands, "command"),
    ]:
        for item in scanner(force):
            all_tools.append({**item, "_type": ttype})

    result = update_descriptions(all_tools)
    return jsonify(result)


# ── 使用统计 API ─────────────────────────────

@app.route("/api/stats/usage")
def api_usage_stats():
    force = request.args.get("refresh") == "1"
    # total 全量求和（全字典），top 仍取前 30（#10）
    stats = get_usage_stats(force)
    total = sum(stats.values())
    top = [{"name": n, "count": c}
           for n, c in sorted(stats.items(), key=lambda kv: -kv[1])[:30]]
    return jsonify({"total_calls": total, "top": top})


@app.route("/api/stats/raw")
def api_usage_raw():
    force = request.args.get("refresh") == "1"
    return jsonify(get_usage_stats(force))


# ── 导出 API ─────────────────────────────────

@app.route("/api/export")
def api_export():
    fmt = request.args.get("format", "json")
    force = request.args.get("refresh") == "1"
    skills = _enrich_with_desc(scan_skills(force), "skill")
    mcp = _enrich_with_desc(scan_mcp_servers(force), "mcp")
    cli = _enrich_with_desc(scan_cli_tools(force), "cli")
    hooks = _enrich_with_desc(scan_hooks(force), "hook")
    plugins_list = _enrich_with_desc(scan_plugins(force), "plugin")
    commands = _enrich_with_desc(scan_commands(force), "command")
    all_tools = skills + mcp + cli + hooks + plugins_list + commands

    if fmt == "json":
        return jsonify({
            "export_time": time.strftime("%Y-%m-%d %H:%M", time.localtime()),
            "total": len(all_tools),
            "tools": all_tools,
        })

    # Markdown 导出
    def _md_cell(v):
        """转义 Markdown 表格单元格：竖线转义，换行转 <br>。"""
        return str(v or "").replace("|", "\\|").replace("\n", "<br>")

    # meta 段与 --- 前必须有空行，否则 CommonMark setext 规则会把整段吞成 h2，分割线不渲染
    lines = [
        "# CC-Toolbox 工具清单\n",
        f"\n导出时间：{time.strftime('%Y-%m-%d %H:%M', time.localtime())}\n",
        f"\n总计 {len(all_tools)} 个工具\n",
        "\n---\n",
    ]
    groups = [
        ("技能", skills), ("MCP 服务", mcp), ("命令行工具", cli),
        ("钩子", hooks), ("插件", plugins_list), ("斜杠命令", commands),
    ]
    for label, items in groups:
        if not items:
            continue
        lines.append(f"\n## {label}（{len(items)} 个）\n")
        lines.append("| 工具名 | 用途 |\n|------|------|\n")
        for item in items:
            desc = item.get("_description_cn") or item.get("description", "") or "暂无描述"
            name = item.get("name", "")
            lines.append(f"| {_md_cell(name)} | {_md_cell(desc)} |\n")

    filename = f"cc-toolbox-export-{time.strftime('%Y%m%d')}.md"
    return Response(
        "".join(lines),
        mimetype="text/markdown",  # Werkzeug 对 text/* 会自动补一个 charset，手动写会导致重复
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{filename}"},
    )


# ── 快速操作 API ─────────────────────────────

@app.route("/api/mcp/<name>/test", methods=["POST"])
def api_mcp_test(name: str):
    from scanners.mcp_scanner import test_connection
    return jsonify(test_connection(name))


@app.route("/api/hooks/<name>/toggle", methods=["POST"])
def api_hook_toggle(name: str):
    from scanners.hook_scanner import toggle_hook
    return jsonify(toggle_hook(name))


@app.route("/api/cli/<name>/help")
def api_cli_help(name: str):
    from scanners.cli_scanner import get_help_output
    return jsonify(get_help_output(name))


# ── 路径配置 API ─────────────────────────────

@app.route("/api/paths")
def api_paths_get():
    import paths_config
    cfg = paths_config.get_config()
    merged = {
        "skill": [str(p) for p in paths_config.get_merged_skill_paths()],
        "cli": [str(p) for p in paths_config.get_merged_cli_paths()],
        "mcp_extra": [str(p) for p in paths_config.get_extra_mcp_dirs()],
    }
    exists = {p: Path(p).exists() for lst in merged.values() for p in lst}
    defaults = {
        "skill": [str(p) for p in config.SKILL_PATHS],
        "cli": [str(p) for p in config.CLI_PATHS],
    }
    return jsonify({"config": cfg, "merged": merged, "exists": exists, "defaults": defaults})


@app.route("/api/paths", methods=["POST"])
def api_paths_update():
    body = request.get_json(silent=True) or {}
    group = body.get("group")
    paths = body.get("paths")
    if group not in ("skill_paths", "cli_paths", "extra_mcp_project_dirs"):
        return jsonify({"success": False, "error": "未知配置组"}), 400
    if not isinstance(paths, list) or not all(isinstance(x, str) for x in paths):
        return jsonify({"success": False, "error": "paths 必须为字符串列表"}), 400
    import paths_config
    try:
        cfg = paths_config.update_group(group, paths)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400
    return jsonify({"success": True, "config": cfg})


@app.route("/api/paths/open", methods=["POST"])
def api_paths_open():
    body = request.get_json(silent=True) or {}
    raw = (body.get("path") or "").strip()
    if not raw:
        return jsonify({"success": False, "error": "缺少 path"}), 400
    import paths_config
    target = Path(raw).expanduser()
    allowed = paths_config.is_configured_path(raw) or paths_config.is_known_user_file(raw)
    if not allowed:
        return jsonify({"success": False, "error": "该路径不在已配置列表中"}), 403
    if not target.exists():
        return jsonify({"success": False, "error": "路径不存在"}), 404
    try:
        if os.name == "nt":
            os.startfile(str(target))  # noqa
        else:
            import subprocess
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, str(target)])
    except Exception as e:
        return jsonify({"success": False, "error": f"打开失败：{e}"}), 500
    return jsonify({"success": True})


# AI 描述文件的示例与目标路径（reset 路由读写；提为模块常量便于测试隔离）
AI_DESC_EXAMPLE_FILE = Path(__file__).parent / "ai_descriptions.example.json"
AI_DESC_FILE = Path(__file__).parent / "ai_descriptions.json"


@app.route("/api/paths/reset-ai-desc", methods=["POST"])
def api_paths_reset_ai_desc():
    src = AI_DESC_EXAMPLE_FILE
    dst = AI_DESC_FILE
    if not src.exists():
        return jsonify({"success": False, "error": "示例文件不存在"}), 404
    if dst.exists():
        return jsonify({"success": False, "error": "ai_descriptions.json 已存在，未覆盖（可手动删除后再恢复）"}), 409
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return jsonify({"success": True})


# ── 单工具详情 API（放在具体操作路由之后避免冲突） ─

@app.route("/api/<tool_type>/<path:name>")
def api_tool_detail(tool_type: str, name: str):
    """获取单个工具的详细信息。

    Flask path converter 已完成 URL 解码，此处不再 unquote（#20 二次解码）。
    """
    scanner_map = {
        "skill": scan_skills, "mcp": scan_mcp_servers,
        "cli": scan_cli_tools, "hook": scan_hooks,
        "plugin": scan_plugins, "command": scan_commands,
    }
    scanner = scanner_map.get(tool_type)
    if not scanner:
        return jsonify({"error": "未知类型"}), 404

    force = request.args.get("refresh") == "1"
    for item in scanner(force):
        if item.get("name") == name:
            # 构造新 dict 输出，绝不原地改扫描器共享缓存（#6 缓存污染）
            result = {**item, "type": tool_type}
            # 添加中文描述和用法
            cn_desc = get_description(name, tool_type, item.get("description", ""))
            cn_usage = get_usage(name, tool_type)
            result["_description_cn"] = cn_desc
            result["_usage_cn"] = cn_usage
            # 技能添加插件关联
            if tool_type == "skill":
                plugin_idx = _build_plugin_index()
                pname = plugin_idx.get(name)
                if pname:
                    result["plugin_name"] = pname
            # CLI 版本懒加载：扫描阶段不跑子进程，详情时才取（#35）
            if tool_type == "cli" and item.get("version") is None:
                from scanners.cli_scanner import get_version
                ver = get_version(name, timeout=5)
                if ver:
                    result["version"] = ver
            return jsonify(result)

    return jsonify({"error": "未找到该工具"}), 404


# 复数键供清单页（/skills 等），单数键供详情页（/detail/skill/...）；mcp/cli 单复数同形（#30）
_TYPE_LABELS = {"skills":"技能","mcp":"MCP 服务","cli":"命令行","hooks":"钩子","plugins":"插件","commands":"命令",
                "skill":"技能","hook":"钩子","plugin":"插件","command":"命令"}
_TYPE_ICONS = {"skills":"📦","mcp":"🔌","cli":"🖥️","hooks":"⚡","plugins":"🔧","commands":"📝",
               "skill":"📦","hook":"⚡","plugin":"🔧","command":"📝"}

# ── 工具函数 ─────────────────────────────────

def _build_plugin_index() -> dict:
    """构建技能→插件的反向索引。"""
    plugins = scan_plugins()
    idx = {}
    for p in plugins:
        pname = p.get("name", "")
        for s in p.get("skills", []):
            idx[s] = pname
    return idx


# ── 入口 ─────────────────────────────────────

# 实际地址与 PID 文件（供 launcher.bat / start_server.py 轮询读取），路径提取为模块常量便于测试注入
ADDR_FILE = Path(__file__).parent / "server_addr.txt"
PID_FILE = Path(__file__).parent / ".launcher.pid"


def run_server(host=None, port=None):
    """启动 Flask 服务：解析端口（0 或 None=自动探测）、写实际地址与 PID、阻塞运行。"""
    host = host or config.HOST
    preferred = port if port is not None else config.PORT
    if not preferred:
        preferred = config.find_free_port(host, config.PREFERRED_PORT)

    # 写实际地址与 PID 供外部（launcher.bat / start_server.py）读取
    ADDR_FILE.write_text(f"http://{host}:{preferred}\n", encoding="utf-8")
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    print("[CC-Toolbox] 启动中...")
    print(f"   浏览器打开 http://{host}:{preferred}")
    print("   按 Ctrl+C 停止服务")
    app.run(host=host, port=preferred, debug=config.DEBUG)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CC-Toolbox 本地工具箱面板")
    parser.add_argument("--host", default=None,
                        help="监听地址（默认取 config.HOST / 环境变量 CC_TOOLBOX_HOST）")
    parser.add_argument("--port", type=int, default=None,
                        help="监听端口（0 或不指定=自动探测空闲端口）")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)
