# CC-Toolbox 开源版

本地 Claude Code 工具箱面板——统一展示你安装的 Skills / MCP / CLI / Hooks / Plugins / Commands，说明每个工具是干什么的、怎么用，支持测试连接、Hook 开关、路径自定义、AI 填写工具描述、一键导出。

界面采用深空数据大屏主题：深色底 + 高亮数据卡片 + 数字滚动动画，纯 Flask + Jinja2 + 原生 JS，无构建步骤。

## 功能

- **全景仪表盘**：工具总数 + 6 类数量（数字滚动 / 占比条）+ 分类预览 + 常用工具排行
- **6 类工具清单与详情**：中文描述 / 用法、全局搜索（支持中文）
- **快速操作**：MCP 测试连接（stdio 型发 JSON-RPC initialize 握手、url 型 HEAD 探测）、Hook 启用禁用（首次自动备份 `settings.json.cc-toolbox.bak` + 原子写 + 失败回滚）、CLI 查看 `--help`、复制调用命令
- **路径设置页**：自定义 Skill / CLI 扫描目录与 MCP 额外项目目录（增删改查 + 在资源管理器中打开）
- **AI 工具描述**：`ai_descriptions.json` 由 AI 按示例填写，作为最高优先级描述来源
- **配置导出** JSON / Markdown；使用统计（结构化 `tool_use` 提取，读最新 20 个会话）
- **端口自动探测**，可与写死 8765 的旧版 / 其他服务共存同时运行
- **安全防护**：POST 写接口拒绝跨站请求（Origin/Referer 校验）、安全响应头（X-Frame-Options 等）、路径打开白名单、Hook 写入原子替换 + 备份回滚；畸形配置文件（null/非字符串等）自动降级不崩

## 环境要求

- Python 3.9+（Windows 优先；macOS / Linux 可用 `python app.py` 方式，启动后用 `xdg-open` / `open` 打开路径）
- 无需网络即可运行（安装依赖时需要）

## 快速开始（用户）

### 方式一：桌面图标启动（推荐，Windows）

1. **首次**：双击 `一键安装并创建桌面图标.bat` —— 自动创建 venv、安装依赖（清华 PyPI 镜像，失败回退官方源）、在桌面生成 **CC-Toolbox** 图标
2. **日常**：双击桌面 **CC-Toolbox** 图标 —— 立即弹出**启动等待窗口**（跑马灯 + 已等待秒数，首次约 10~20 秒），服务就绪后自动关窗并打开浏览器；**再次双击 = 停止服务**（弹窗提示状态）

### 方式二：命令行风格（Windows）

双击 `launcher.bat` —— 首次同样自动装依赖；启动过程在窗口内显示状态，服务以最小化窗口保活；再次双击 = 停止。

### 方式三：手动

```bash
python -m venv venv
# Windows: venv\Scripts\activate    macOS/Linux: source venv/bin/activate
pip install -r requirements.txt     # 国内可加 -i https://pypi.tuna.tsinghua.edu.cn/simple
python app.py
```

启动日志与 `server_addr.txt` 会给出实际访问地址（默认从 8765 自动探测空闲端口）。

也可运行 `python start_server.py`：后台子进程启动，轮询 `server_addr.txt` 后自动打开浏览器，日志写入 `server.log`。

## 给 AI Agent 的自动部署指令

按以下步骤操作即可完成部署（复制 / 克隆本项目到目标机器后）：

1. 将本项目复制 / 克隆到目标机器任意目录（路径可含中文，避免特殊符号）
2. 检查 `python3` / `python` 是否存在且版本 ≥ 3.9；在项目目录执行 `python -m venv venv`
3. 用 venv 的 pip 安装 `requirements.txt`（优先清华镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple`，失败用默认源）
4. 可选配置：
   - 读取用户的 skill / CLI 工具安装目录，写入 `paths_config.json`（格式见下文「配置文件」）
   - 询问用户是否需要定制工具描述；如需要，参照 `ai_descriptions.example.json` 将条目写入 `ai_descriptions.json`（`desc` 写 1-3 句功能总结，不要太长）
5. 启动：`python app.py`（Windows 也可双击 `launcher.bat`）；等待项目目录出现 `server_addr.txt`（最多 20 秒），读取其中 URL，验证 `GET /api/summary` 返回 200
6. 可选测试：`python -m pytest tests/ -q` 应全部通过（当前 106 个用例）
7. 向用户报告访问 URL 与已配置的路径 / 描述数量

## 主运行流程（给用户与 AI Agent 的系统心智模型）

理解这条链路有助于排障与二次开发：

```
双击桌面图标（或 launcher.bat）
   ↓
launch_w.pyw（前台接待员，pythonw 无窗口运行）
   ├─ 立即弹出等待窗口（跑马灯 + 已等待秒数）🆕
   ├─ 后台启动 venv\Scripts\python.exe app.py（真服务，输出写 server.log）
   ├─ 轮询 server_addr.txt（服务启动后写入实际地址）
   └─ 就绪 → 自动关等待窗 → 打开浏览器 → MessageBox 报告地址
        （25 秒未就绪 → 等待窗显示超时排查指引）
   ↓
Flask 服务（app.py）
   ├─ 探测空闲端口（8765 起，被占自动 +1；可用 CC_TOOLBOX_PORT 指定）
   ├─ 写 server_addr.txt（实际 URL）与 .launcher.pid（进程号）
   └─ 扫描本机数据源：~/.claude/ 各配置、paths_config.json 自定义目录
   ↓
浏览器页面（深空数据大屏）
   └─ 页面 JS 通过 /api/* 向服务要数据并渲染
        （列表数据带 120 秒缓存，页面「刷新」按钮强制重扫）
```

停止：再次双击图标 → `launch_w.pyw` 读 `.launcher.pid` 确认进程存活 → taskkill 停止 → 弹窗提示。

**为什么首次启动要十几秒**：Python 解释器加载 + Flask 初始化 + 全盘扫描工具目录（系统 PATH 就有上百个目录）+ 首次无缓存。等待窗口的作用就是把这段"黑盒时间"可视化。二次启动因描述缓存已存在会明显更快。

## 启动组件速查（launcher.bat 与 venv 是什么）

| 组件 | 一句话说明 |
|---|---|
| **桌面图标** → `launch_w.pyw` | 日常主入口：无黑窗、有等待窗口、双击切换启停 |
| **launcher.bat** | 命令行风格备用入口：黑窗口显示每步详细输出，适合排障；首次会自动建 venv 装依赖，之后每次**不会**再联网下载（发现 venv 与依赖已存在即跳过安装） |
| **venv/** | 项目专属的隔离 Python 环境：内置一份完整 Python 解释器副本 + pip + Flask 等依赖。体积大（几十~百余 MB）属正常；不联网、不上传；可整个删除，双击 launcher.bat 会自动重建。隔离的意义是不污染系统 Python，且整目录拷贝到新机器删掉 venv 重建即可 |
| **一键安装并创建桌面图标.bat** | 仅首次使用：建 venv → 装依赖（清华镜像，失败回退官方源）→ 生成桌面快捷方式 |

## 端口与多开

- 默认监听 `127.0.0.1`，端口从 8765 起自动探测空闲（探测范围 8765-8865，共 101 个）
- 环境变量：`CC_TOOLBOX_HOST` / `CC_TOOLBOX_PORT`（指定端口；`0` 或不设置 = 自动探测）
- 命令行：`python app.py --host 0.0.0.0 --port 9000`
- 与写死 8765 的旧版共存：先启动旧版（占 8765），本版自动落到 8766+；或显式 `CC_TOOLBOX_PORT=9000`

## 配置文件

均为项目目录下的 JSON。损坏或缺失时自动回退空配置，不影响启动。

### paths_config.json — 自定义扫描路径

```json
{
  "skill_paths": ["D:\\my\\skills"],
  "cli_paths": ["D:\\my\\cli"],
  "extra_mcp_project_dirs": ["E:\\some-project"]
}
```

也可在网页「路径设置」页可视化管理（含在资源管理器中打开）。

### ai_descriptions.json — AI 工具描述（最高优先级）

格式见 `ai_descriptions.example.json`：顶层按类型（`skill` / `mcp` / `cli` / `hook` / `plugin` / `command`），次层工具名，值为 `{desc, usage 可选}`。填好后即在读取时直接生效；在文档页点「更新描述」会把这些条目强制合并进 `desc_cache.json` 缓存。

## 测试

```bash
python -m pytest tests/ -q
```

当前 106 个用例，覆盖：扫描器与坏数据防御（24）、安全 CSRF（15）、Hook（15）、无窗口启动器（9）、描述缓存（9）、API 与搜索（9）、路径配置（8）、AI 描述（8）、导出（4）、启动（3）、隔离与冒烟（2）。

## 目录结构

```
cc-toolbox开源版/
├── app.py                     # Flask 主入口：页面路由 + /api/* 接口 + run_server（写 server_addr.txt / .launcher.pid）
├── config.py                  # 扫描路径默认值、CC_TOOLBOX_HOST/PORT、find_free_port、缓存 TTL
├── paths_config.py            # paths_config.json 读写（三键：skill_paths / cli_paths / extra_mcp_project_dirs）
├── desc_cache.py              # 中文描述缓存引擎 + AI 描述（ai_descriptions.json 最高优先级）
├── start_server.py            # 后台启动助手（子进程 + 轮询地址 + 开浏览器）
├── launcher.bat               # Windows 命令行风格启动/停止（自动 venv + 依赖 + 开浏览器）
├── 一键安装并创建桌面图标.bat  # 首次安装 + 生成桌面 CC-Toolbox 图标（推荐入口）
├── launch_w.pyw               # 无窗口启动器（桌面图标目标：等待窗口 + 双击切换启停 + 弹窗反馈）
├── create_shortcut.ps1        # 创建桌面快捷方式（指向 pythonw + launch_w.pyw + 新图标）
├── create_shortcut.ps1        # 生成桌面快捷方式（可选）
├── generate_icon.py           # 维护者重新生成图标（需 Pillow；运行时不需要）
├── requirements.txt           # flask>=3.0、pytest
├── requirements-dev.txt       # 开发依赖
├── ai_descriptions.example.json  # AI 描述示例（随仓库分发）
├── paths_config.json          # 自定义扫描路径（本机生成，不入库）
├── ai_descriptions.json       # AI 工具描述（本机生成，不入库）
├── desc_cache.json            # 描述缓存（本机生成，不入库）
├── server_addr.txt            # 实际访问地址（运行时生成）
├── .launcher.pid              # 服务进程 PID（运行时生成）
├── scanners/                  # 6 类工具扫描器 + stats_scanner（使用统计）
│   ├── skill_scanner.py  mcp_scanner.py  cli_scanner.py
│   ├── hook_scanner.py   plugin_scanner.py  command_scanner.py
│   └── stats_scanner.py
├── templates/                 # Jinja2 模板：base/dashboard/list/detail/docs/search/settings/error
├── static/                    # css/style.css（深空主题）、js/app.js、图标（app_icon.ico 为快捷方式图标）
└── tests/                     # pytest 用例（72 个）
```

## FAQ

- **双击 launcher.bat 每次都会下载东西吗** → 不会。只有首次（或 venv 被删除）才联网装依赖，之后直接跳过安装启动服务
- **venv 文件夹为什么那么大** → 它是项目专属的隔离 Python 环境：含完整解释器副本 + pip + Flask 及依赖，几十~百余 MB 属正常；可删除，launcher.bat 会自动重建（详见「启动组件速查」）
- **双击图标后浏览器很久才打开** → 首次启动需扫描工具目录约 10~20 秒，现在有等待窗口显示进度；二次启动明显更快。超时 25 秒会提示查 server.log
- **桌面图标显示的还是旧图标** → Windows 按文件路径缓存图标。处理：重新运行 `powershell -ExecutionPolicy Bypass -File create_shortcut.ps1` 重建快捷方式（其 IconLocation 指向 `static\app_icon.ico`，换名文件可绕开缓存）；仍无效则桌面按 F5 刷新，或任务管理器重启 Windows 资源管理器
- **端口被占 / 想换端口** → 见「端口与多开」
- **工具描述不准** → 让 AI 填 `ai_descriptions.json`；文档页「更新描述」可合并进缓存
- **paths / ai 文件删了会崩吗** → 不会，自动回退空配置 / 原描述链
- **换电脑** → 整目录拷走即可（venv 可删重建）；`paths_config.json` 是本机路径，需按需调整
- **改图标** → 维护者：`pip install pillow` 后 `python generate_icon.py`（运行时不需要 Pillow）；或直接替换 `static/app_icon.ico` / `favicon.ico` / `icon.png`（ico 换文件名可绕 Windows 图标缓存）
- **数据隐私** → 完全本地运行，不发送任何数据；`desc_cache.json` 等用户数据不入库

## License

TODO：选择开源许可证
