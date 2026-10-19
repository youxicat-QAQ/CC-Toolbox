"""中文描述缓存 — 为每个工具生成详细的用途说明和具体用法"""

import copy
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_FILE = Path(__file__).parent / "desc_cache.json"
# AI 描述文件：由用户/ AI 手工填写，作为描述的最高优先级来源（优先于一切现有链路）
AI_DESC_FILE = Path(__file__).parent / "ai_descriptions.json"

# AI 描述文件允许的工具类型（与 6 类扫描器一致）
_AI_TYPE_KEYS = ("skill", "mcp", "cli", "hook", "plugin", "command")

# 内存缓存：以 mtime_ns + size 双键校验文件是否变化，未变则零 JSON 解析
_mem = {"data": None, "mtime_ns": -1, "size": -1}
# AI 描述文件的内存缓存（模式与 _mem 完全一致，复用下面的 _lock）
_ai_mem = {"data": None, "mtime_ns": -1, "size": -1}
# 读-改-写共享锁（RLock：_load_cache/_save_cache 内部也用同一把锁，可重入）
_lock = threading.RLock()


def _has_chinese(text: str) -> bool:
    return bool(re.search(r"[一-鿿]", text))


def _load_cache() -> dict:
    with _lock:
        try:
            st = CACHE_FILE.stat()
        except OSError:
            # 文件不存在：优先用内存数据，避免外部环境误删导致清空
            return _mem["data"] if _mem["data"] is not None else {}

        if (
            _mem["data"] is not None
            and _mem["mtime_ns"] == st.st_mtime_ns
            and _mem["size"] == st.st_size
        ):
            return _mem["data"]

        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"缓存根节点应为对象，实际为 {type(data).__name__}")
        except Exception as exc:
            # 文件损坏：保留旧内存数据，绝不静默清空；
            # 同时更新 stat 标记，让同一损坏版本只解析一次（文件修好后 stat 变化会自动重读）
            logger.warning("desc_cache.json 解析失败（%s），保留内存缓存：%s", exc, CACHE_FILE)
            _mem["mtime_ns"] = st.st_mtime_ns
            _mem["size"] = st.st_size
            return _mem["data"] if _mem["data"] is not None else {}

        _mem["data"] = data
        _mem["mtime_ns"] = st.st_mtime_ns
        _mem["size"] = st.st_size
        return data


def _save_cache(cache: dict) -> None:
    with _lock:
        tmp = CACHE_FILE.with_name(CACHE_FILE.name + ".tmp")
        try:
            tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, CACHE_FILE)
        except Exception:
            # 写入/替换失败时清理临时文件，主文件保持原样，然后 re-raise
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        # 写成功后同步内存缓存与 stat 标记
        _mem["data"] = cache
        st = CACHE_FILE.stat()
        _mem["mtime_ns"] = st.st_mtime_ns
        _mem["size"] = st.st_size


def _make_key(name: str, type_key: str) -> str:
    return f"{type_key}::{name}"


def _filter_ai_data(data) -> dict:
    """过滤 AI 描述数据：只保留 6 类工具类型下的 dict 条目，剔除 _comment 等元键。"""
    if not isinstance(data, dict):
        return {}
    result = {}
    for type_key, tools in data.items():
        # 以 _ 开头的顶层键视为说明性元键（_comment / _comment_format），直接忽略
        if str(type_key).startswith("_"):
            continue
        if not isinstance(tools, dict):
            continue
        result[type_key] = {
            tname: entry for tname, entry in tools.items() if isinstance(entry, dict)
        }
    return result


def _load_ai_desc() -> dict:
    """加载 AI 描述文件（ai_descriptions.json）。

    模式与 _load_cache 完全一致：stat 双键命中则零解析；
    文件缺失 → 用内存数据（外部误删不清空）或 {}；
    文件损坏 → warning + 保留内存 + 更新 stat 标记（同一损坏版本只解析一次）。
    """
    with _lock:
        try:
            st = AI_DESC_FILE.stat()
        except OSError:
            # 文件不存在：优先用内存数据，避免外部环境误删导致清空
            return _filter_ai_data(_ai_mem["data"])

        if (
            _ai_mem["data"] is not None
            and _ai_mem["mtime_ns"] == st.st_mtime_ns
            and _ai_mem["size"] == st.st_size
        ):
            return _ai_mem["data"]

        try:
            raw = json.loads(AI_DESC_FILE.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(f"AI 描述根节点应为对象，实际为 {type(raw).__name__}")
        except Exception as exc:
            # 文件损坏：保留旧内存数据，绝不静默清空；
            # 同时更新 stat 标记，让同一损坏版本只解析一次（文件修好后 stat 变化会自动重读）
            logger.warning(
                "ai_descriptions.json 解析失败（%s），保留内存数据：%s", exc, AI_DESC_FILE
            )
            _ai_mem["mtime_ns"] = st.st_mtime_ns
            _ai_mem["size"] = st.st_size
            return _filter_ai_data(_ai_mem["data"])

        data = _filter_ai_data(raw)
        _ai_mem["data"] = data
        _ai_mem["mtime_ns"] = st.st_mtime_ns
        _ai_mem["size"] = st.st_size
        return data


def get_ai_entry(name: str, type_key: str) -> dict:
    """取 AI 描述文件中某个工具的条目；未命中或值非 dict 时返回 {}。"""
    tools = _load_ai_desc().get(type_key, {})
    if not isinstance(tools, dict):
        return {}
    entry = tools.get(name)
    return entry if isinstance(entry, dict) else {}


def count_ai_entries() -> int:
    """统计 AI 描述文件中的有效工具条目数（不含 _comment 等元键与非 6 类类型）。"""
    total = 0
    for type_key, tools in _load_ai_desc().items():
        if type_key not in _AI_TYPE_KEYS or not isinstance(tools, dict):
            continue
        total += len(tools)
    return total


def get_description(name: str, type_key: str, original_desc: str = "") -> str:
    """获取工具的中文描述。

    回退链：AI 描述文件（最高优先级）→ JSON 缓存 desc 非空 → _KNOWN_DETAILED 预定义
    → 原始描述含中文 → original。
    """
    # AI 描述为权威来源：只要 ai_descriptions.json 里填了 desc 就直接采用
    ai = get_ai_entry(name, type_key)
    if ai.get("desc"):
        return str(ai["desc"])

    cache = _load_cache()
    key = _make_key(name, type_key)
    entry = cache.get(key)
    if not isinstance(entry, dict):
        entry = {}
    if entry.get("desc"):
        return entry["desc"]
    known = _KNOWN_DETAILED.get(key)
    if known and known.get("desc"):
        return known["desc"]
    if original_desc and _has_chinese(original_desc):
        return original_desc
    return original_desc or ""


def get_usage(name: str, type_key: str) -> str:
    """获取工具的具体用法说明。

    回退链：AI 描述文件（最高优先级）→ JSON 缓存 usage 非空 → _KNOWN_DETAILED 预定义
    → 空串。
    """
    # AI 描述为权威来源：只要 ai_descriptions.json 里填了 usage 就直接采用
    ai = get_ai_entry(name, type_key)
    if ai.get("usage"):
        return str(ai["usage"])

    cache = _load_cache()
    key = _make_key(name, type_key)
    entry = cache.get(key)
    if not isinstance(entry, dict):
        entry = {}
    if entry.get("usage"):
        return entry["usage"]
    known = _KNOWN_DETAILED.get(key)
    if known and known.get("usage"):
        return known["usage"]
    return ""


# ═══════════════════════════════════════════════════════════════════
# 详细用途说明（3-5句）：这个工具干什么用的，有什么功能特点
# 具体用法（1-3条）：在哪些场景下怎么用
# ═══════════════════════════════════════════════════════════════════

_KNOWN_DETAILED = {
    # ── Skills ──
    "skill::algorithmic-art": {
        "desc": "Algorithmic Art 是基于 p5.js 的算法艺术生成技能。它能创建交互式、可探索的生成艺术画作，包含粒子系统、流场、分形结构等多种算法模式。每次生成都使用 Art Blocks 风格的可重现随机种子，确保相同种子输出完全相同的结果。生成的 HTML 画作是自包含的单文件，可在任意浏览器中打开并交互调节参数。",
        "usage": "• 在输入框中输入 /algorithmic-art 触发此技能\n• 也可直接描述需求，如「生成一张流动线条的艺术画」「做一个分形图案」\n• 技能会先创建算法哲学文档描述设计理念，再生成可交互的 HTML 画作\n• 打开生成的 HTML 后，可通过侧栏的 Seed/参数/颜色控件实时调整",
    },
    "skill::find-skills": {
        "desc": "Find Skills 是用来搜索和安装 Claude Code 技能的搜索引擎。它连接 skills.sh 生态市场，可以根据关键词搜索合适的技能，查看安装量、来源和评分，并直接安装到本地环境中。支持搜索技能、模板和工作流三类资源，是扩展 Claude Code 能力的主要入口。",
        "usage": "• 告诉它你想做什么，如「帮我找一个写 React 的技能」「搜索代码审查相关的 skill」\n• 它会先查看 skills.sh 排行榜推荐热门技能，再用关键词精确搜索\n• 确认安装后自动执行 npx skills add 命令\n• 安装后可在侧栏「技能」页面看到新增的技能",
    },
    "skill::frontend-design": {
        "desc": "Frontend Design 是高质量前端界面设计技能。它结合设计系统思维和 Tailwind CSS / shadcn/ui 等现代框架，从 PRD 需求分析到高保真原型全流程覆盖。注重色彩搭配、间距节奏、响应式布局和细节动效，能产出可直接运行的交互式 HTML 页面。包含从草图到像素级还原的完整设计工作流。",
        "usage": "• 描述你想要的前端界面，如「设计一个暗色主题的数据仪表盘」「一个移动端登录页」\n• 也可输入 /frontend-design 手动触发\n• 技能会先理解需求，然后生成完整的前端代码\n• 生成的页面可直接在浏览器中预览和交互",
    },
    "skill::code-review-excellence": {
        "desc": "代码审查卓越实践技能，系统性地指导高效代码审查工作流。它帮助审查者从架构正确性、安全性、性能、可维护性等多个维度评估代码质量，提供结构化的建设性反馈。适用于 Code Review 流程中的代码评审环节，能帮助团队提早发现 Bug 和改进代码质量。",
        "usage": "• 将待审查的代码提供给 Claude，或提供 PR/Commit 链接\n• 技能会自动从多个维度分析代码（架构、安全、性能、风格等）\n• 会给出可操作的建议和修改方案\n• 适合在提交 PR 前做自查，或在 Review 他人代码时使用",
    },
    "skill::claude-api": {
        "desc": "Claude API 开发和调试技能，覆盖 Anthropic SDK（Python/TypeScript）的完整使用。包含 API 调用、工具使用（Tool Use）、流式响应、Token 管理、错误处理和最佳实践等方面的指导。帮助开发者快速集成和优化 Claude API 应用。",
        "usage": "• 描述你要用 Claude API 做什么，如「帮我写一个调用 Claude 的 Python 脚本」\n• 也可以问具体的 API 用法，如「Tool Use 怎么用」「如何计算 token」\n• 技能会提供代码示例、配置说明和最佳实践建议",
    },
    "skill::docx": {
        "desc": "Word 文档（.docx）处理技能，支持创建、读取、编辑和操作 Word 文档。可以生成带格式（字体、颜色、表格、图片）的专业文档，支持目录生成、段落样式、页眉页脚等高级功能。基于 python-docx 库实现。",
        "usage": "• 告诉它需要生成什么文档，如「帮我生成一份项目报告 Word 文档」\n• 可以指定格式要求，如「标题用黑体 18pt，正文用宋体 12pt」\n• 也支持读取现有 .docx 文件并修改\n• 生成的文件保存在当前目录下",
    },
    "skill::pdf": {
        "desc": "PDF 文件处理技能，支持读取、合并、拆分、水印添加、加密解密等常见 PDF 操作。可以提取 PDF 中的文本和元数据，也可以将多个 PDF 合并成一个，或为 PDF 添加页码水印。基于 PyMuPDF 等库实现全面的 PDF 处理能力。",
        "usage": "• 描述你要对 PDF 做什么，如「把这两个 PDF 合并」「给这个 PDF 加水印」\n• 也支持提取 PDF 中的文字内容、分割指定页面等\n• 处理后的文件会保存到指定位置",
    },
    "skill::xlsx": {
        "desc": "Excel 文件（.xlsx）处理技能，支持读写和编辑电子表格。可以创建含公式、图表、条件格式、数据验证的专业 Excel 报表。支持大量数据的批量处理和格式化输出，适用于数据报告生成和自动化报表场景。",
        "usage": "• 告诉它要生成什么表格，如「生成一份销售数据报表，包含柱状图」\n• 支持公式、合并单元格、颜色标记、下拉列表等\n• 也支持读取现有 Excel 并修改数据\n• 生成的 .xlsx 文件可用 Excel 或 WPS 打开",
    },
    "skill::mcp-builder": {
        "desc": "MCP 服务器构建技能，指导如何构建高质量的 MCP（Model Context Protocol）服务器。涵盖 MCP 协议理解、服务器架构设计、工具定义、资源暴露、安全实践等全流程。帮助开发者将外部 API 和数据源通过 MCP 协议连接到 Claude 等 AI 应用中。",
        "usage": "• 描述你想连接什么服务，如「我想做个 GitHub MCP 服务器」\n• 技能会引导你设计 MCP 服务器的架构和工具\n• 按照指导编写和配置 MCP 服务器\n• 完成后可在 Claude Code 的 MCP 配置中添加使用",
    },
    "skill::opengstack": {
        "desc": "OpenGStack 是由 Garry Tan 打造的全栈开发工作流套件，包含 29 个命令技能。覆盖从项目初始化、代码生成、调试到部署的完整开发周期。采用角色化开发方式，包括产品经理、设计师、工程师等不同角色的协作工作流。适合全栈项目的结构化管理。",
        "usage": "• 输入 /opengstack 查看可用命令列表\n• 每个命令以 /g-xxx 形式调用，如 /g-init 初始化项目\n• 技能会引导你按照角色化工作流逐步推进\n• 适合从零开始的全栈项目开发",
    },
    "skill::skill-creator": {
        "desc": "技能创建工具，用于创建、修改和优化 Claude Code 技能。提供从构思到发布的全流程指导：技能结构设计、SKILL.md 编写、测试和评估。可以帮助理解技能的目录结构、配置文件格式和发布流程。",
        "usage": "• 描述你想创建什么技能，如「帮我创建一个翻译技能」\n• 技能会指导你完成技能目录结构和 SKILL.md 编写\n• 完成后将技能放到 ~/.claude/skills/ 目录下即可生效\n• 也可以使用 npx skills init 命令创建技能模板",
    },
    "skill::web-design": {
        "desc": "Web 视觉设计技能，从 PRD 到高保真 UI 的全流程覆盖。专注于信息架构、布局设计、色彩系统和交互细节。生成可直接运行的 HTML+CSS 代码，注重视觉层次和用户体验。适合网页原型设计和前端界面开发。",
        "usage": "• 描述你要设计的网页，如「设计一个 SaaS 产品 landing page」\n• 技能会先梳理信息架构，然后生成高保真 UI\n• 生成的 HTML 代码可直接在浏览器中预览\n• 支持响应式设计和交互原型",
    },
    "skill::web-artifacts-builder": {
        "desc": "用 React + Tailwind CSS + shadcn/ui 构建复杂网页制品的技能。专注于创建功能完整的单页应用，支持组件化开发、状态管理和 UI 框架集成。生成的代码质量高，适合需要交互逻辑的复杂页面。",
        "usage": "• 描述你要构建的网页应用，如「做一个待办事项管理面板」\n• 技能会使用现代前端技术栈构建\n• 生成的代码包含完整的组件结构和交互逻辑\n• 可直接在浏览器中运行和测试",
    },
    "skill::theme-factory": {
        "desc": "主题工厂技能，可为各类制品（网页、文档、演示文稿等）应用预设主题样式。内置 10 套精心设计的主题（赛博朋克、极简主义、自然风等），一键切换整体视觉风格。适合快速原型设计中的主题探索。",
        "usage": "• 描述你要应用主题的内容和想要的效果\n• 技能会从 10+ 套预设主题中选择匹配的样式\n• 也可以指定具体主题名称\n• 支持自定义颜色和字体等主题参数",
    },
    "skill::canvas-design": {
        "desc": "Canvas 视觉创作技能，用于创建精美的视觉艺术作品和设计图。支持 PNG 和 PDF 格式输出，可以生成海报、插图、信息图表等视觉内容。结合生成式设计技术和手动调整，产出高质量的视觉设计。",
        "usage": "• 描述你要创作什么视觉内容，如「设计一张科技感海报」\n• 技能会使用 Canvas API 进行绘制\n• 输出为 PNG 或 PDF 格式\n• 适合无需交互的静态视觉设计",
    },
    "skill::commit-format": {
        "desc": "Git 提交信息格式化技能，帮你写出符合 Conventional Commits 规范的提交信息。自动分析代码变更内容，生成规范化的 commit message，包含类型、作用域和描述的标准化格式。适合团队协作中统一提交风格。",
        "usage": "• 在 commit 前使用，技能会自动分析变更内容\n• 生成符合 Conventional Commits 规范的提交信息\n• 格式如：feat(scope): 描述信息\n• 也可在写提交信息时咨询应该用什么类型和描述",
    },
    "skill::doc-coauthoring": {
        "desc": "文档协作撰写技能，用于结构化地协作撰写技术文档、提案、设计规格等。提供文档结构化建议、内容框架设计和多轮润色优化。适合需要产出高质量文档的各种场景。",
        "usage": "• 描述你要写什么文档，如「帮我写一份技术方案文档」\n• 技能会先梳理大纲，然后分章节逐步完善\n• 支持多轮修改和润色\n• 输出为 Markdown 格式，可方便地转为其他格式",
    },
    "skill::internal-comms": {
        "desc": "内部沟通文档撰写技能，用于编写状态报告、领导层更新、公司通讯等内部文档。了解不同受众的沟通需求，调整语气和内容深度。适合团队和组织的各种正式沟通场景。",
        "usage": "• 描述你要撰写的沟通内容和目标受众\n• 技能会根据受众调整语气和详细程度\n• 适合周报、项目状态更新、管理层汇报等场景\n• 输出结构清晰的文档",
    },
    "skill::slack-gif-creator": {
        "desc": "Slack GIF 动图创建技能，生成适合 Slack 使用的动画 GIF。包含分辨率优化、文件压缩和循环设置等功能，确保生成的 GIF 符合 Slack 的文件限制和显示标准。",
        "usage": "• 描述你要创建的动图内容\n• 技能会生成符合 Slack 尺寸和大小限制的 GIF\n• 自动优化文件大小和帧率\n• 生成的 GIF 可直接拖拽到 Slack 中使用",
    },
    "skill::cpp-testing": {
        "desc": "C++ 测试技能，编写和修复 C++ 测试用例，配置 GoogleTest/CTest 测试框架。可以诊断测试失败原因，分析代码覆盖率，提供测试策略建议。适用于 C++ 项目的测试开发和调试。",
        "usage": "• 描述你要测试的 C++ 代码或要修复的测试失败\n• 技能会编写 GoogleTest 测试用例或分析失败原因\n• 支持 CMake/CTest 配置指导\n• 提供测试策略和边界值分析",
    },
    "skill::qt-cpp-review": {
        "desc": "Qt C++ 代码审查技能，专门审查 Qt 项目的代码质量和规范。检查 Qt 信号槽连接、内存管理、QObject 生命周期等 Qt 特有的问题。提供针对性改进建议。",
        "usage": "• 提供 Qt C++ 代码给 Claude 审查\n• 技能会检查信号槽连接、内存管理、最佳实践等\n• 提供具体的改进建议和代码示例\n• 适合 Qt 开发团队的代码评审环节",
    },
    "skill::qt-qml": {
        "desc": "QML 界面开发指导技能，提供 QML 语法、组件使用和最佳实践。涵盖 Qt Quick Controls、动画系统、模型视图、性能优化等方面。适合使用 Qt 进行界面开发的场景。",
        "usage": "• 描述你想要实现的 QML 界面功能\n• 技能会提供 QML 代码示例和最佳实践\n• 涵盖动画、布局、自定义组件等\n• 适合桌面和嵌入式 Qt 应用开发",
    },
    "skill::qt-ui-design": {
        "desc": "Qt 界面设计建议和最佳实践技能，提供跨平台 Qt 应用的用户界面设计指导。涵盖布局策略、控件选择、主题样式和平台适配等方面。帮助开发 Qt 界面的开发人员做出更好的设计决策。",
        "usage": "• 描述你的 Qt 应用场景和目标平台\n• 技能会提供界面设计建议和实现方案\n• 覆盖布局、样式、平台适配等内容\n• 适合 Qt 应用的用户界面设计",
    },
    "skill::brand-guidelines": {
        "desc": "品牌规范应用技能，将 Anthropic 官方品牌色彩和字体规范自动应用到各类设计稿中。确保输出的设计作品符合 Anthropic 品牌识别标准，包括 Logo 使用、色彩系统和排版规范。",
        "usage": "• 设计涉及 Anthropic 品牌素材时自动触发\n• 自动应用官方品牌色（如 #d97757）和字体（Poppins/Lora）\n• 确保设计稿的品牌一致性\n• 适用于需要遵循 Anthropic 品牌指南的设计项目",
    },
    "skill::template-skill": {
        "desc": "技能模板，是新技能创建时的参考起点。包含了 SKILL.md 的标准结构、目录组织方式和配置示例。开发者可以基于此模板快速创建符合规范的新技能。",
        "usage": "• 作为创建新技能的参考模板\n• 复制此技能的目录结构\n• 按 SKILL.md 中的注释指引填写自定义内容\n• 适合技能开发者使用",
    },
    "skill::webapp-testing": {
        "desc": "Web 应用测试技能，使用 Playwright 对本地 Web 应用进行端到端测试。支持页面截图、交互操作、断言验证和测试报告生成。适用于前端自动化测试场景。",
        "usage": "• 提供你要测试的 Web 应用的本地地址\n• 描述测试场景和预期行为\n• 技能会编写并运行 Playwright 测试\n• 返回测试结果和截图",
    },
    "skill::pptx": {
        "desc": "PowerPoint 演示文稿创建和编辑技能，支持生成含图表、表格、图片和动画的专业 PPT 文档。可以设置幻灯片母版、主题配色和切换动画，生成结构化的演示文档。",
        "usage": "• 描述你要创建的演示文稿内容和用途\n• 技能会生成结构化的 PPT 文档\n• 支持图表、表格、图片等元素\n• 生成的 .pptx 文件可用 PowerPoint 或 WPS 打开",
    },

    # ── MCP Servers ──
    "mcp::mcp-video": {
        "desc": "视频编辑 MCP 服务，提供从裁剪合并到特效添加的完整视频处理能力。支持视频裁剪、多片段拼接、文字字幕叠加、音频处理、转场特效、画中画布局、视频缩放旋转等 60+ 操作。基于 FFmpeg 实现专业级视频处理，适用于内容创作、视频后期和自动化工作流。",
        "usage": "• Claude 在需要处理视频时会自动调用此 MCP 服务\n• 可直接说「把这段视频裁剪前 30 秒」「给视频加字幕」\n• 支持常见的视频格式转换（MP4/WebM/MOV/GIF）\n• 所有文件处理都在本地完成，无需上传到云端",
    },
    "mcp::filesystem": {
        "desc": "文件系统 MCP 服务，提供安全的本地文件读写和管理能力。可以读取文件内容、写入文件、创建目录、遍历文件列表等。操作受限于允许的目录范围，确保安全隔离。Claude Code 用于读写代码文件、查看配置、管理项目文件。",
        "usage": "• Claude 在处理文件操作时自动调用\n• 可读取项目中的各类文件（代码、配置、文档等）\n• 支持写入和修改文件内容\n• 操作受安全策略限制，只能访问允许的目录",
    },
    "mcp::playwright": {
        "desc": "浏览器自动化 MCP 服务，通过 Playwright 驱动无头浏览器执行页面操作。支持网页截图生成、页面内容抓取、表单填写和提交、链接点击等交互操作。适用于 Web 自动化测试、页面数据采集和端到端验证场景。",
        "usage": "• Claude 需要查看网页内容或截图时自动调用\n• 也支持自动填写表单、点击按钮等交互\n• 可在浏览器中执行 JavaScript 获取页面数据\n• 适用于网页测试、屏幕截图、内容抓取等",
    },
    "mcp::github": {
        "desc": "GitHub API 集成 MCP 服务，连接 GitHub 平台进行仓库管理操作。支持仓库和 Issue 管理、Pull Request 操作、代码审查、文件管理和搜索功能。开发者可以通过对话直接管理 GitHub 项目和协作流程。",
        "usage": "• 可以直接说「帮我创建一个 Issue」「查看这个 PR 的变更」\n• 支持创建和管理仓库、Issue、PR、讨论\n• 可以搜索代码和 Issue\n• 需要配置 GitHub Token 认证",
    },
    "mcp::memory": {
        "desc": "持久化记忆 MCP 服务，提供跨会话的信息存储和检索能力。可以记住用户的偏好设置、项目上下文、关键决策等信息，在后续对话中自动回忆。让 Claude 能在不同会话间保持上下文连续性。",
        "usage": "• Claude 会自动使用该服务记录重要信息\n• 可以主动说「记住这个配置」让 Claude 存储\n• 在后续会话中自动调取相关信息\n• 用于保持长期上下文和偏好设置",
    },
    "mcp::fetch": {
        "desc": "网页内容获取 MCP 服务，用于获取和解析网页内容。可以抓取 URL 的文本内容，转换为 Markdown 格式以供阅读。适用于网页信息查询、在线文档获取和内容收集场景。",
        "usage": "• Claude 需要读取网页内容时自动调用\n• 也可以主动要求「打开这个网页看看」\n• 支持 HTTP/HTTPS 协议的 URL\n• 获取的网页内容会被转为文字以方便阅读",
    },
    "mcp::sqlite": {
        "desc": "SQLite 数据库操作 MCP 服务，提供轻量级数据库的查询和管理能力。支持 SQL 查询执行、表结构查看、数据增删改查和数据库文件管理。适用于本地数据存储和分析场景。",
        "usage": "• Claude 需要查询 SQLite 数据时自动调用\n• 执行 SELECT/INSERT/UPDATE/DELETE 等 SQL 命令\n• 支持查看表结构和数据库元数据\n• 适用于本地数据管理和分析",
    },
    "mcp::redis": {
        "desc": "Redis 缓存操作 MCP 服务，连接 Redis 服务器进行键值存储管理。支持 String、Hash、List、Set、Sorted Set 等数据类型的读写操作，以及缓存策略和过期管理。",
        "usage": "• Claude 需要操作 Redis 时自动调用\n• 支持所有常用 Redis 数据类型和命令\n• 可查看键值、设置过期时间、管理缓存\n• 需要 Redis 连接配置",
    },
    "mcp::postgres": {
        "desc": "PostgreSQL 数据库操作 MCP 服务，连接 PostgreSQL 数据库进行查询和管理。支持 SQL 执行、表结构查看、数据导入导出和数据库管理。适用于生产环境的关系型数据库操作场景。",
        "usage": "• Claude 需要操作 PostgreSQL 时自动调用\n• 执行 SQL 查询、DDL 和 DML 操作\n• 查看数据库 schema 和表结构\n• 需要配置数据库连接信息",
    },
    "mcp::puppeteer": {
        "desc": "浏览器自动化 MCP 服务，通过 Puppeteer 控制无头 Chrome 浏览器。提供网页截图、PDF 生成、页面内容抓取和交互操作等功能。适用于需要完整浏览器渲染的网页处理场景。",
        "usage": "• Claude 需要处理需要 JavaScript 渲染的页面时自动调用\n• 支持截图、PDF 导出、内容抓取\n• 可执行页面交互操作\n• 适用于 SPA 页面和需要登录的网页",
    },

    # ── CLI Tools ──
    "cli::python": {
        "desc": "Python 解释器，用于运行和开发 Python 程序。支持 Python 3.12 版本，可以执行 .py 脚本文件、运行交互式解释器、安装和管理 Python 包。是数据科学、Web 开发和自动化脚本的核心工具。",
        "usage": "• 在终端中运行 python xxx.py 执行脚本\n• 运行 python --version 查看版本\n• 运行 python -m pip install <包名> 安装第三方包\n• 直接输入 python 进入交互式编程环境",
    },
    "cli::node": {
        "desc": "Node.js 运行时环境，用于执行 JavaScript 代码。支持运行 .js 文件、开发 Web 服务器、构建前端项目和处理自动化任务。是 JavaScript 生态的核心运行时，支持 CommonJS 和 ES Module 两种模块系统。",
        "usage": "• 在终端中运行 node xxx.js 执行脚本\n• 运行 node --version 查看 Node.js 版本\n• 用于运行前端构建工具和开发服务器\n• 支持所有 npm 包生态",
    },
    "cli::npm": {
        "desc": "Node.js 包管理器，是 JavaScript 生态的包管理工具。用于安装、更新和管理项目依赖，发布 npm 包，运行项目脚本。配合 package.json 管理项目依赖关系和版本锁定。",
        "usage": "• npm install <包名> 安装依赖\n• npm install -g <包名> 全局安装\n• npm run <脚本名> 运行 package.json 中定义的脚本\n• npm update 更新所有依赖",
    },
    "cli::npx": {
        "desc": "Node.js 包执行器，可以临时运行 npm 包而无需全局安装。自动从 npm 仓库下载并执行指定的包，执行完毕后清理。适合运行一次性工具、脚手架和 CLI 工具。",
        "usage": "• npx <包名> 临时运行一个包\n• npx create-react-app my-app 创建新项目\n• npx skills add xxx 安装技能\n• 运行完毕后自动清理，不留残留",
    },
    "cli::git": {
        "desc": "分布式版本控制系统，管理代码的变更历史。支持代码提交、分支管理、远程仓库同步、代码合并和冲突解决。是软件开发团队协作的基石工具。",
        "usage": "• git status 查看工作区状态\n• git add . 暂存变更\n• git commit -m '描述' 提交代码\n• git push 推送到远程\n• git pull 拉取最新代码",
    },
    "cli::pip": {
        "desc": "Python 包管理器，管理 Python 第三方库。可以安装、卸载和升级 Python 包，管理依赖关系和版本。是 Python 生态系统中最常用的包管理工具。",
        "usage": "• pip install <包名> 安装 Python 包\n• pip install -r requirements.txt 批量安装依赖\n• pip list 查看已安装的包\n• pip uninstall <包名> 卸载包",
    },
    "cli::code": {
        "desc": "VS Code 编辑器命令行工具（code CLI），可以从终端快速打开 VS Code 编辑器和项目。支持打开文件、文件夹、跳转到指定行，以及安装和管理扩展。",
        "usage": "• code . 在当前目录打开 VS Code\n• code xxx.py 用 VS Code 打开文件\n• code --install-extension <扩展名> 安装扩展\n• code --list-extensions 查看已安装扩展",
    },

    # ── Plugins ──
    "plugin::superpowers": {
        "desc": "超级技能包插件，包含 14 个高质量的开发技能。覆盖 TDD（测试驱动开发）、调试、代码审查、写作计划、分支管理、模型上下文协议（MCP）构建等全流程开发场景。每个技能都经过精心设计，遵循统一的技能规范和交互模式。",
        "usage": "• 安装后自动生效，各技能出现在「技能」列表中\n• 包含的子技能可通过 /技能名 调用\n• 涵盖测试、调试、审查、文档撰写等开发环节\n• 适合追求高效开发工作流的开发者",
    },
    "plugin::frontend-design": {
        "desc": "前端设计插件，为 Claude Code 提供专业的前端 UI/UX 设计能力。包含从视觉设计到前端代码实现的全套技能，可以创建高质量的用户界面和交互原型。适用于需要快速原型设计和前端开发的各种场景。",
        "usage": "• 安装后自动生效，相关技能出现在「技能」列表中\n• 设计前端界面时自动调用\n• 生成可直接运行的 HTML 代码\n• 适合 Web 开发者和 UI/UX 设计师",
    },
}


def update_descriptions(all_tools: list) -> dict:
    """扫描工具列表，为缺少描述和用法的工具生成内容。"""
    with _lock:  # 读-改-写整体加锁，并发 POST 不互相覆盖
        # 拷贝后再就地修改：_load_cache 可能返回 _mem["data"] 活对象，
        # 若 _save_cache 失败（如 os.replace 抛 OSError），内存不会被改脏产生幽灵数据
        cache = copy.deepcopy(_load_cache())
        updated = 0
        skipped = 0

        # AI 描述为权威来源，强制覆盖：先合并 ai_descriptions.json，
        # 放在「扫描结果补缺」循环之前，使后续 skip 条件（desc+usage 都有值则跳过）
        # 天然尊重 AI 写入；AI 条目即使不在当前扫描结果中也写入缓存（允许预填未安装工具）
        ai_data = _load_ai_desc()
        for type_key, tools in ai_data.items():
            if type_key not in _AI_TYPE_KEYS:
                continue
            if not isinstance(tools, dict):
                continue
            for tname, entry in tools.items():
                if not isinstance(entry, dict):
                    continue
                desc = str(entry.get("desc") or "").strip()
                usage = str(entry.get("usage") or "").strip()
                if not desc and not usage:
                    continue
                key = _make_key(tname, type_key)
                prev = cache.get(key)
                if not isinstance(prev, dict):
                    prev = {}
                # AI 只填了其中一个字段时，另一字段保留缓存旧值（缺失则留空，交给补缺循环）
                cache[key] = {
                    "desc": desc or prev.get("desc", ""),
                    "usage": usage or prev.get("usage", ""),
                    "source": "ai_desc",
                    "updated": time.time(),
                }
                updated += 1

        # 回退同步：AI 文件里已删除的条目，清除缓存中对应 source=ai_desc 的记录，
        # 让描述回退原链——否则该条 desc+usage 齐全会被下面补缺循环 skip，旧 AI 文案永久残留。
        # ai_data 已经过 _filter_ai_data（只留 dict 条目），值非 dict 的工具名不在 ai_keys：
        # get_ai_entry 对其本就返回 {}（AI 已不再权威），按条目失效一并回退，不保留失效文案。
        ai_keys = {
            _make_key(tname, ttype)
            for ttype, tools in ai_data.items()
            if ttype in _AI_TYPE_KEYS and isinstance(tools, dict)
            for tname in tools
        }
        for key in [k for k, v in cache.items()
                    if isinstance(v, dict) and v.get("source") == "ai_desc"
                    and k not in ai_keys]:
            del cache[key]
            updated += 1

        for tool in all_tools:
            ttype = tool.get("_type", "")
            name = tool.get("name", "")
            if not name or not ttype:
                continue

            key = _make_key(name, ttype)
            existing = cache.get(key)
            if not isinstance(existing, dict):
                existing = {}

            # 如果已有完整条目（desc + usage）则跳过
            if existing.get("desc") and existing.get("usage"):
                skipped += 1
                continue

            # AI 描述为权威：source=ai_desc 的条目已有值不再被后续补缺覆盖，只补空缺字段
            ai_owned = existing.get("source") == "ai_desc"

            # 先查已知详细数据
            known = _KNOWN_DETAILED.get(key)

            if known:
                if ai_owned:
                    existing["desc"] = existing.get("desc") or known["desc"]
                    existing["usage"] = existing.get("usage") or known["usage"]
                else:
                    existing["desc"] = known["desc"]
                    existing["usage"] = known["usage"]
                existing["updated"] = time.time()
                cache[key] = existing
                updated += 1
                continue

            # 原始描述含中文则直接用
            orig_desc = tool.get("description", "") or ""
            if orig_desc and _has_chinese(orig_desc):
                existing["desc"] = orig_desc if not ai_owned else (existing.get("desc") or orig_desc)
                existing["usage"] = existing.get("usage") or _auto_usage(name, ttype, tool)
                existing["updated"] = time.time()
                cache[key] = existing
                updated += 1
                continue

            # 模板自动生成
            if not existing.get("desc"):
                existing["desc"] = _auto_desc(name, ttype, tool)
            if not existing.get("usage"):
                existing["usage"] = _auto_usage(name, ttype, tool)
            existing["updated"] = time.time()
            cache[key] = existing
            updated += 1

        # 无任何更新时不序列化、不落盘（避免白写整份缓存文件）
        if updated:
            _save_cache(cache)
        return {"updated": updated, "skipped": skipped, "total": len(all_tools)}


def _auto_desc(name: str, ttype: str, tool: dict) -> str:
    """自动为未识别的工具生成中文用途说明。"""
    if ttype == "skill":
        path = tool.get("path", "")
        src = tool.get("source", "")
        sub = tool.get("sub_skills", [])
        parts = [f"{name} 是一款 Claude Code 技能"]
        if src:
            parts.append(f"来自 {src}")
        if sub:
            parts.append(f"包含 {len(sub)} 个子技能：{'、'.join(sub[:5])}")
            if len(sub) > 5:
                parts[-1] += " 等"
        parts.append(f"在对话中描述相关需求时会自动触发，也可在输入框中输入 /{name} 手动调用")
        return "，" .join(parts) + "。"
    if ttype == "mcp":
        cmd = tool.get("command", "")
        desc = f"{name} 是一个 MCP 服务"
        if cmd:
            desc += f"，通过 {cmd} 命令启动"
        desc += "。在对话中 Claude 会根据需要自动调用此服务来处理相关请求。"
        return desc
    if ttype == "cli":
        path = tool.get("path", "")
        cat = tool.get("category", "")
        parts = [f"{name} 是一个命令行工具"]
        if cat:
            parts.append(f"类别：{cat}")
        parts.append(f"在终端中直接运行")
        parts.append(f"{name} --help 查看完整用法")
        return "，".join(parts) + "。"
    if ttype == "hook":
        evt = tool.get("event", "")
        return f"{name} 是一个 Claude Code 钩子脚本，在「{evt}」事件触发时自动运行。无需手动操作，配置后自动生效。可通过 CC-Toolbox 的详情页切换启用/禁用状态。"
    if ttype == "plugin":
        skills = tool.get("skills", [])
        cmds = tool.get("commands", [])
        parts = [f"{name} 是一个 Claude Code 插件"]
        if skills:
            parts.append(f"包含 {len(skills)} 个技能：{'、'.join(skills[:5])}")
        if cmds:
            parts.append(f"包含 {len(cmds)} 个命令：{'、'.join(cmd.replace('/', '') for cmd in cmds[:5])}")
        parts.append("安装后自动生效，其中的技能和命令可直接在对话中使用")
        return "，".join(parts) + "。"
    if ttype == "command":
        return f"{name} 是一个斜杠命令，在对话中输入 /{name} 即可执行对应的操作。适合高频重复任务的快捷调用。"
    return f"{name} 是 {'、'.join(tool.get('tags', []))} 相关工具" if tool.get("tags") else f"{name}"


def _auto_usage(name: str, ttype: str, tool: dict) -> str:
    """自动生成具体用法说明。"""
    if ttype == "skill":
        lines = [f"• 在输入框中输入 /{name} 手动触发此技能"]
        sub = tool.get("sub_skills", [])
        if sub:
            lines.append(f"• 包含 {len(sub)} 个子技能，可执行更具体的任务")
        lines.append("• 也可在对话中直接描述相关需求，Claude 会判断是否自动使用")
        return "\n".join(lines)
    if ttype == "mcp":
        return f"• 在对话中提及需要 {name} 处理的任务时，Claude 会自动调用\n• 如需测试连通性，可在工具箱的技能详情页点击「测试连接」"
    if ttype == "cli":
        return f"• 在终端中运行 {name} --help 查看完整的命令参数和用法\n• 运行 {name} --version 查看当前版本号\n• 根据具体场景附加参数运行"
    if ttype == "hook":
        evt = tool.get("event", "")
        blocking = tool.get("blocking", False)
        mode = "阻塞模式，会等待脚本执行完成" if blocking else "非阻塞模式，异步执行不影响主流程"
        return f"• 配置后当「{evt}」事件触发时自动运行\n• {mode}\n• 可通过工具箱详情页切换启用/禁用"
    if ttype == "plugin":
        skills = tool.get("skills", [])
        cmds = tool.get("commands", [])
        lines = ["• 安装后自动生效，无需额外配置"]
        if skills:
            lines.append(f"• 技能调用：在对话中输入 /技能名 或直接描述需求自动触发")
        if cmds:
            lines.append(f"• 命令调用：在对话中输入 /命令名 即可执行")
        return "\n".join(lines)
    if ttype == "command":
        return f"• 在对话中输入 /{name} 即可执行此命令\n• Claude 会自动加载并执行对应的预定义内容\n• 适合高频、标准化的操作"
    return ""
