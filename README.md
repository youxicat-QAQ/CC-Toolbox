# 🧰 CC-Toolbox — Claude Code 可视化工具箱管理面板

> **把你散落各处的 Claude Code 工具，装进一块深空数据大屏。**
> 一个本地运行的可视化面板，统一展示、解释、管理你安装的所有 **Skills / MCP / CLI / Hooks / Plugins / Commands**——装了什么、是干什么的、怎么用，一屏尽收；支持 **AI 一键部署**，丢给你的 AI Agent 就能自动装好。

`Claude Code` · `MCP 工具管理` · `Skills 可视化` · `本地面板` · `AI 一键部署` · `深空数据大屏`

---

## ✨ 为什么值得用

| 痛点 | CC-Toolbox 的答案 |
|---|---|
| 工具装了一堆，散落在 `~/.claude/`、PATH、各种配置文件里，根本记不清有什么 | **一块面板全展示**：6 大类工具自动扫描，仪表盘总数 + 分类数量 + 使用排行 |
| MCP / Skill 名字一堆，不知道哪个是干嘛的、怎么调用 | **中文描述 + 用法说明**：内置预定义映射，还支持 **AI 按示例填写专属描述**（最高优先级），想不准都难 |
| 想验证 MCP 通不通、临时关掉某个 Hook，得手改配置文件 | **一键操作**：MCP 测试连接（JSON-RPC 握手）、Hook 启用/禁用（自动备份 + 原子写 + 失败回滚，改不坏） |
| 想把环境配置分享给朋友 / AI | **一键导出** JSON / Markdown |
| 部署麻烦、换电脑要重配 | **真正可移植**：零硬编码路径；**丢给 AI Agent 七步自动部署**；双击图标即用 |

**还有这些细节**：深空数据大屏 UI（玻璃拟态卡片 + 数字滚动动画 + 响应式）、端口自动探测可与旧服务双开、107 个自动化测试、CSRF 安全防护、畸形配置自动降级不崩、完全本地运行零上传。

---

## 🎯 它能做什么

- 📊 **全景仪表盘**：工具总数（滚动大数字）+ 6 类数量与占比条 + 分类预览 + 常用工具排行（从真实会话记录统计）
- 📦 **6 类工具管理**：Skills / MCP 服务 / CLI 命令行 / Hooks 钩子 / Plugins 插件 / Commands 斜杠命令——清单、筛选、详情、全局中文搜索
- ⚡ **快速操作**：MCP 连接测试、Hook 一键开关（安全写入）、CLI 查看 `--help`、复制调用命令
- 🗂 **路径设置页**：可视化管理自定义扫描目录 + MCP 额外项目目录，一键在资源管理器中打开
- 🤖 **AI 工具描述**：让 AI 按 `example` 示例为每个工具写 1-3 句中文说明，写入即生效
- 📤 **配置导出**：JSON / Markdown 一键导出全部工具清单
- 🔒 **安全与健壮性**：POST 接口 CSRF 校验、安全响应头、Hook 写入自动备份回滚、坏配置自动过滤

---

## 🚀 快速开始

### 方式一：桌面图标（推荐，Windows）

1. 双击 **`一键安装并创建桌面图标.bat`** —— 自动创建 Python 虚拟环境、安装依赖（国内镜像，失败自动回退官方源）、生成桌面 **CC-Toolbox** 图标
2. 以后双击桌面图标 —— 无黑窗静默启动（有等待进度窗口），自动打开浏览器；**再点一次 = 停止**

### 方式二：命令行

```bash
python -m venv venv
# Windows: venv\Scripts\activate    macOS/Linux: source venv/bin/activate
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
python app.py
```

启动日志与 `server_addr.txt` 会给出实际访问地址（默认从 **8765 自动探测空闲端口**，可与写死 8765 的服务双开）。

### 方式三：🤖 丢给你的 AI Agent 一键部署

把本仓库给你的 Claude Code / 其他 AI Agent，说一句“按 README 部署”，它会照做：

```text
1. 将本项目复制/克隆到目标机器任意目录（路径可含中文）
2. 确认 python ≥ 3.9 存在；在项目目录执行 python -m venv venv
3. 用 venv 的 pip 安装 requirements.txt（优先清华镜像，失败用默认源）
4. 可选：读取用户的 skill/CLI 安装目录写入 config/paths_config.json；
   可选：参照 config/ai_descriptions.example.json 为工具填写中文描述到 config/ai_descriptions.json
5. 启动 python app.py；等待 server_addr.txt 出现（≤20 秒），读取 URL 验证 GET /api/summary 返回 200
6. 可选：python -m pytest tests/ -q（当前 107 个用例应全部通过）
7. 向用户报告访问 URL 与已配置的路径/描述数量
```

---

## 🧠 主运行流程（用户与 AI 的系统心智模型）

```
双击桌面图标（或 launcher.bat）
   ↓
launch_w.pyw（无窗口接待员）
   ├─ 弹出等待窗口（跑马灯 + 已等待秒数）
   ├─ 后台启动 venv\Scripts\python.exe app.py
   ├─ 轮询 server_addr.txt（服务写入实际地址后）
   └─ 就绪 → 关窗 → 打开浏览器 → 弹窗报告地址
   ↓
Flask 服务：探测空闲端口 → 扫描 ~/.claude/ 与自定义目录 → 提供 /api/*
   ↓
浏览器深空数据大屏：页面 JS 调 /api/* 渲染（120 秒缓存，「刷新」强制重扫）
```

**首次启动约 10~20 秒**（全盘扫描工具目录）——等待窗口把这段时间可视化；二次启动明显更快。

### 启动组件速查

| 组件 | 说明 |
|---|---|
| 桌面图标 → `launch_w.pyw` | 日常主入口：无黑窗、等待窗口、双击切换启停 |
| `launcher.bat` | 排障备用：黑窗口显示每步输出；首次自动装依赖，之后**不联网**直接启动 |
| `venv/` | 项目专属隔离 Python 环境（完整解释器副本 + 依赖，体积大属正常）；可删，自动重建 |

---

## ⚙️ 配置文件（均在 `config/` 目录，损坏自动回退不影响启动）

### `config/paths_config.json` — 自定义扫描路径

```json
{
  "skill_paths": ["D:\\my\\skills"],
  "cli_paths": ["D:\\my\\cli"],
  "extra_mcp_project_dirs": ["E:\\some-project"]
}
```

也可在网页「路径设置」页可视化管理。

### `config/ai_descriptions.json` — AI 工具描述（最高优先级）

格式见 `config/ai_descriptions.example.json`：按类型分组，每个工具 `{desc: "1-3 句功能总结", usage: "可选用法"}`。保存即生效；文档页「更新描述」会合并进缓存，**删除条目后自动回退**。

### 端口与多开

- 环境变量 `CC_TOOLBOX_HOST` / `CC_TOOLBOX_PORT`（0=自动探测 8765-8865）；命令行 `python app.py --port 9000`
- 与固定 8765 的服务共存：先开旧服务，本面板自动落到 8766+

---

## 🧪 质量保障

```bash
python -m pytest tests/ -q   # 107 个用例
```

覆盖：扫描器与坏数据防御（24）、安全 CSRF（15）、Hook（15）、无窗口启动器（9）、描述缓存（9）、API 与搜索（9）、路径配置（8）、AI 描述（8）、导出（4）、启动（3）、隔离与冒烟（2）。
手工测试清单见 [`docs/测试文档.md`](docs/测试文档.md)（含新旧对比 38 项可勾选用例）。

---

## 📁 目录结构

```
cc-toolbox/
├── 一键安装并创建桌面图标.bat  # 首次安装入口（推荐从这里开始）
├── launcher.bat / launch_w.pyw # 启动器（命令行版 / 无窗口版）
├── app.py / config.py / paths_config.py / desc_cache.py   # 核心程序
├── scanners/    # 6 类工具扫描器 + 使用统计
├── templates/ + static/        # 深空数据大屏前端
├── config/      # ★ 用户数据（路径配置 / AI 描述 / 描述缓存）
├── docs/        # 测试文档 / 图标素材
└── tests/       # pytest 用例（107）
```

---

## ❓ FAQ

- **双击 launcher.bat 会下载东西吗？** 只有首次（或 venv 被删）才装依赖，之后直接启动
- **venv 为什么很大？** 完整 Python 副本 + 依赖，几十~百余 MB 正常；可删可重建
- **描述不准怎么办？** 让 AI 填 `config/ai_descriptions.json`，保存即生效
- **桌面图标不刷新？** 桌面 F5；仍不行则重启资源管理器（详见 docs/测试文档.md）
- **数据安全吗？** 完全本地运行、不发送任何数据；Hook 写入前自动备份 `settings.json.cc-toolbox.bak`

---

## 🗺 路线图想法

- [ ] 使用趋势图（时间序列）
- [ ] 实时文件监听自动刷新
- [ ] 工具一键安装/卸载
- [ ] 多语言界面（English）

欢迎提 Issue / PR 共建。

## 📄 License

MIT（TODO：正式添加 LICENSE 文件）

---

<p align="center">
  <b>Star 本项目 ⭐ 如果它帮你理清了 Claude Code 的工具箱</b><br>
  <sub>本地 · 开源 · 可移植 · 为 Claude Code 重度用户而生</sub>
</p>
