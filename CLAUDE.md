# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

CC-Toolbox 开源版 — 本地 Claude Code 工具箱管理面板。Flask 3.x 单进程应用，管理 Claude Code 的 Skills、MCP 服务、CLI 工具、Hooks、Plugins、Commands 共 6 类工具。路径与端口均可移植（不写死本机路径 / 端口）。

## 常用命令

```bash
# 启动服务器（自动探测空闲端口，实际地址见启动日志与 server_addr.txt）
python app.py

# 或指定 host/port
python app.py --host 127.0.0.1 --port 9000

# 或双击 launcher.bat（一键启动/停止 + 首次自动 venv/依赖 + 自动打开浏览器）
# 或 python start_server.py（后台启动 + 打开浏览器，日志写入 server.log）

# 测试
python -m pytest tests/ -q
```

Debug 模式默认关闭。测试在 `tests/`（72 个用例）；无 lint 配置。依赖装进项目本地 `venv/`（`python -m venv venv` + `pip install -r requirements.txt`）。

## 项目架构

```
cc-toolbox开源版/
├── app.py                  # Flask 主入口 — 页面路由 + /api/* 接口 + run_server（argparse --host/--port）
├── config.py               # 配置：扫描路径默认值、CC_TOOLBOX_HOST/PORT、find_free_port、缓存 TTL
├── paths_config.py         # paths_config.json 读写（自定义扫描路径三键）
├── desc_cache.py           # 中文描述缓存引擎（AI 描述 + JSON 缓存 + 预定义映射）
├── start_server.py         # 独立后台启动助手（轮询 server_addr.txt 后开浏览器）
├── launcher.bat            # Windows 一键启动/停止（.launcher.pid 判活）
├── generate_icon.py        # 维护者重生成图标（需 Pillow；运行时不需要）
├── ai_descriptions.example.json  # AI 描述示例（随仓库分发；ai_descriptions.json 为本机文件）
│
├── scanners/               # 数据扫描器（每个工具类型一个独立模块）
│   ├── __init__.py          # 统一导出 scan_* 函数
│   ├── skill_scanner.py     # 扫描 SKILL.md → 名称/描述/子技能
│   ├── mcp_scanner.py       # 读取 ~/.claude.json projects + 额外项目目录 → MCP 服务
│   ├── cli_scanner.py       # 扫描配置目录 + 系统 PATH 的 CLI 工具
│   ├── hook_scanner.py      # 解析 ~/.claude/settings.json 中的 Hook 配置（官方 dict 格式 + sidecar 禁用）
│   ├── plugin_scanner.py    # 读取 installed_plugins.json + cache/ 目录
│   ├── command_scanner.py   # 扫描 commands 目录下的 .md 文件
│   └── stats_scanner.py     # 解析 JSONL 会话文件 → 工具调用统计
│
├── templates/              # Jinja2 模板
│   ├── base.html            # 侧边栏（所有页面继承）
│   ├── dashboard.html       # 仪表盘：统计卡片 + 分类预览 + 使用排行
│   ├── list.html            # 分类清单页（6 类共用）
│   ├── detail.html          # 工具详情页
│   ├── docs.html            # 全局工具文档页
│   ├── search.html          # 搜索页
│   ├── settings.html        # 路径设置页（自定义扫描路径 + 用户数据文件）
│   └── error.html           # 404/错误页
│
├── static/
│   ├── css/style.css        # 全部样式（深空数据大屏主题，响应式）
│   ├── js/app.js            # 全部前端逻辑（渲染、交互、导出、设置页）
│   └── icon.png / icon-64.png / favicon.ico
│
├── desc_cache.json          # 中文描述持久化缓存（自动生成，不入库）
├── paths_config.json        # 自定义扫描路径（本机文件，不入库）
├── ai_descriptions.json     # AI 工具描述（本机文件，不入库）
├── server_addr.txt          # 实际访问地址（run_server 生成，供 launcher 读取）
├── .launcher.pid            # 服务进程 PID（run_server 生成）
└── server.log               # start_server.py 的日志文件
```

## 关键设计

### 数据扫描器模式
每个扫描器遵循统一模式：
- `scan_all()` — 实际扫描逻辑
- `get_*(force_refresh=False)` — 带缓存的获取接口（120s TTL）
- 模块级 `_cache` / `_cache_time` 变量

### 扫描路径
- **Skills**: `~/.claude/skills/`（config.SKILL_PATHS 默认）+ `paths_config.json` 的 `skill_paths` 自定义（paths_config.get_merged_skill_paths 合并去重）
- **CLI**: 默认空（config.CLI_PATHS）+ `cli_paths` 自定义 + 系统 PATH 补充；每个目录下还会扫 `node_modules/.bin` 与 `bin` 子目录
- **MCP**: `~/.claude.json` 的 `projects` 键解析项目路径 ∪ `extra_mcp_project_dirs` 自定义目录，逐项目读 `.mcp.json`
- **Plugins**: `~/.claude/plugins/installed_plugins.json` + `~/.claude/plugins/cache/`
- **Hooks**: 解析 `~/.claude/settings.json` 的 hooks 字典（官方格式 {事件: [{matcher, hooks:[...]}]}），禁用项存应用目录 `hook_disabled.json`。首次切换前自动备份 `settings.json.cc-toolbox.bak`，写入均为原子替换（tmp + os.replace），sidecar 写失败会回滚 settings
- **Commands**: `~/.claude/commands/` 下所有 .md 文件

### 中文描述（desc_cache.py）
- 回退链：**AI 描述文件（最高优先级）→ JSON 缓存 desc 非空 → _KNOWN_DETAILED 预定义 → 原始描述含中文 → 原始描述**
- `ai_descriptions.json`（与示例文件同格式）由 AI/用户填写，读取时直接生效；`POST /api/update-descriptions` 会把这些条目**强制合并**进缓存（source=ai_desc，即使工具当前未安装也可预填）
- 通过 `_description_cn` / `_usage_cn` 字段传递到前端
- `count_ai_entries()` 统计有效条目数（剔除 _comment 等元键）

### 路径配置（paths_config.py）
- 三键结构：`skill_paths` / `cli_paths` / `extra_mcp_project_dirs`，文件固定为项目目录下 `paths_config.json`
- 缺失/损坏自动按空配置处理；读时不做内存缓存（每次读盘，保证扫描/API 看到最新值）；写为原子替换 + RLock
- API：`GET /api/paths`、`POST /api/paths`（按组更新）、`POST /api/paths/open`（白名单内路径在资源管理器打开）、`POST /api/paths/reset-ai-desc`（ai_descriptions.json 不存在时从示例复制）
- 网页入口：`/settings` 路径设置页

### 启动配置
- 环境变量 `CC_TOOLBOX_HOST`（默认 127.0.0.1）、`CC_TOOLBOX_PORT`（0/未设 = 自动探测）；命令行 `--host` / `--port` 优先
- `config.find_free_port(host, preferred)` 从 preferred（默认 PREFERRED_PORT=8765）起探测 101 个端口
- `run_server()` 写 `server_addr.txt`（实际 URL）与 `.launcher.pid`（PID），供 launcher.bat / start_server.py 轮询

### API 端点到前端映射
```
GET  /api/skills|mcp|cli|hooks|plugins|commands → loadList() / loadPreview()
GET  /api/<type>/<name>    → loadDetail() 单工具详情
GET  /api/docs             → loadDocs() 文档页
GET  /api/search           → 搜索页
GET  /api/stats/usage      → loadUsageStats() 使用排行
POST /api/update-descriptions → refreshDocs()
GET  /api/export?format=json|markdown → exportTools()
GET  /api/paths / POST /api/paths     → 设置页
```

卡片点击统一走 `goToDetail(type, name)` 跳转到 `/detail/<type>/<name>` 详情页。

### 前端渲染
- `buildDetailHTML(item, type)` — 核心渲染函数，处理所有 6 种类型的详情展示
- 类型元数据统一收敛在 app.js 顶部 `TYPE_META`（标签/图标/徽章类名/API 路径/复数）：skill=📦 mcp=🔌 cli=🖥️ hook=⚡ plugin=🔧 command=📝
- 详情展示为独立页面 `/detail/<type>/<name>`
- 搜索跨所有 6 类工具，按类型分组展示

### 交互式操作
- 测试 MCP 连接：`POST /api/mcp/<name>/test`（stdio 型发 JSON-RPC initialize 握手；url 型 HEAD 探测）
- 切换 Hook：`POST /api/hooks/<name>/toggle`
- 查看 CLI --help：`GET /api/cli/<name>/help`
- 复制命令：前端 `navigator.clipboard.writeText()`

## 重要注意事项

- **路由顺序敏感**：通用路由 `/api/<tool_type>/<path:name>` 必须放在具体操作路由（如 `/api/mcp/<name>/test`、`/api/paths` 等）之后（见 app.py 中的注释）
- 修改模板/静态文件后需要重启 Flask 服务
- 所有扫描器都有 120s 内存缓存，`?refresh=1` 参数强制刷新
- 统计扫描只读按 mtime 最新的 20 个 JSONL 会话文件，排除 subagents/workflows 子目录
- `paths_config.json` / `ai_descriptions.json` / `desc_cache.json` 均为本机数据文件，删除后自动回退空配置/原链，不影响启动
