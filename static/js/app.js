/* CC-Toolbox 前端交互 */

// ── 类型元数据（全文件唯一数据源，#36 收敛）：标签/图标/徽章类名/API 路径/复数路径 ──
const TYPE_META = {
    skill:  {label:"技能",     icon:"📦", badgeClass:"type-skill",   api:"skills",  plural:"skills"},
    mcp:    {label:"MCP 服务", icon:"🔌", badgeClass:"type-mcp",     api:"mcp",     plural:"mcp"},
    cli:    {label:"命令行",   icon:"🖥️", badgeClass:"type-cli",     api:"cli",     plural:"cli"},
    hook:   {label:"钩子",     icon:"⚡", badgeClass:"type-hook",    api:"hooks",   plural:"hooks"},
    plugin: {label:"插件",     icon:"🔧", badgeClass:"type-plugin",  api:"plugins", plural:"plugins"},
    command:{label:"命令",     icon:"📝", badgeClass:"type-command", api:"commands",plural:"commands"},
};

// 复数类型 → 单数类型（由 TYPE_META.plural 派生；预览卡片 data-type / 图标用）
const SINGULAR = {};
Object.entries(TYPE_META).forEach(([single, meta]) => { SINGULAR[meta.plural] = single; });

// ── 全局搜索（双入口：侧栏 + 移动端，统一 .global-search-input 类绑定） ──
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".global-search-input").forEach(input => {
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                const q = input.value.trim();
                if (q) window.location.href = `/search?q=${encodeURIComponent(q)}`;
            }
        });
    });

    // 仪表盘加载
    if (document.getElementById("statsGrid")) loadDashboard();
    // 清单页加载
    const grid = document.getElementById("toolGrid");
    if (grid) loadList(grid);
    // 搜索页加载
    if (document.getElementById("searchResults")) loadSearch();
    // 文档页加载
    if (document.getElementById("docsContent")) loadDocs();
    // 详情页加载
    const detailContent = document.getElementById("detailContent");
    if (detailContent) {
        loadDetail(detailContent.dataset.type, detailContent.dataset.name);
    }
    // 使用统计加载
    if (document.getElementById("usageStats")) loadUsageStats();
    // 路径设置页加载
    if (document.getElementById("settingsPage")) loadSettings();
    // 更新侧栏计数
    if (document.getElementById("sidebarNav")) updateNavCounts();
});

// ── summary 拉取（模块级 Promise 缓存：侧栏计数与仪表盘共用一次请求，#34） ──
let summaryPromise = null;
function fetchSummary(force = false) {
    if (!summaryPromise || force) {
        const p = api("/api/summary").catch(e => {
            if (summaryPromise === p) summaryPromise = null;  // 失败不缓存，允许重试；若已被新请求替换则不误清
            throw e;
        });
        summaryPromise = p;
    }
    return summaryPromise;
}

// ── 更新侧栏计数 ──
async function updateNavCounts() {
    const countIds = ["navTotal", "navSkill", "navMcp", "navCli", "navHook", "navPlugin", "navCommand"];
    try {
        const summary = await fetchSummary();
        const byType = summary.by_type || {};
        document.getElementById("navTotal").textContent = summary.total || 0;
        document.getElementById("navSkill").textContent = byType.skill ?? 0;
        document.getElementById("navMcp").textContent = byType.mcp ?? 0;
        document.getElementById("navCli").textContent = byType.cli ?? 0;
        document.getElementById("navHook").textContent = byType.hook ?? 0;
        document.getElementById("navPlugin").textContent = byType.plugin ?? 0;
        document.getElementById("navCommand").textContent = byType.command ?? 0;
    } catch (e) {
        // 计数失败：显示占位并标注原因，不再永久静默（#40）
        console.warn("侧栏计数加载失败:", e);
        countIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.textContent = "-"; el.title = "加载失败"; }
        });
    }
}

// ── 数字滚动动画（rAF + easeOut cubic；from 取 dataset.count，结束时写回） ──
function countUp(el, target, duration = 800) {
    if (!el) return;
    const from = parseInt(el.dataset.count || "0", 10) || 0;
    const to = Number(target) || 0;
    const start = performance.now();
    function frame(now) {
        const t = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - t, 3);   // easeOut cubic
        el.textContent = Math.round(from + (to - from) * eased);
        if (t < 1) {
            requestAnimationFrame(frame);
        } else {
            el.textContent = to;
            el.dataset.count = String(to);
        }
    }
    requestAnimationFrame(frame);
}

// ── 仪表盘 ──
async function loadDashboard() {
    try {
        const summary = await fetchSummary();
        const byType = summary.by_type || {};
        const total = summary.total || 0;

        // Hero 指挥区：总数滚动 + 同步时间 + 类型数
        countUp(document.getElementById("heroTotal"), total);
        const syncEl = document.getElementById("syncTime");
        if (syncEl) syncEl.textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
        const typeCountEl = document.getElementById("typeCount");
        const statCards = document.querySelectorAll(".stat-card");
        if (typeCountEl) typeCountEl.textContent = String(statCards.length || Object.keys(TYPE_META).length);

        // 更新统计卡片（用 onclick 覆盖赋值，避免刷新时监听器叠加）
        statCards.forEach(card => {
            const type = card.dataset.type;
            const count = byType[type] ?? 0;
            countUp(card.querySelector(".stat-count"), count);
            // 占比进度条：total=0 时全 0，最小 4% 保证可见
            const fill = card.querySelector(".stat-bar-fill");
            if (fill) fill.style.width = total > 0 ? Math.max(4, Math.round(count / total * 100)) + "%" : "0%";
            card.onclick = () => {
                window.location.href = `/${TYPE_META[type]?.api || type}`;
            };
        });

        // 兼容旧 totalCount 节点（若仍被挂载）
        const totalEl = document.getElementById("totalCount");
        if (totalEl) totalEl.textContent = summary.total;

        // 加载各分类预览
        const types = ["skills", "mcp", "cli", "hooks", "plugins", "commands"];
        types.forEach(t => loadPreview(t));

    } catch (e) {
        document.querySelectorAll(".stat-count").forEach(el => el.textContent = "!");
    }
}

async function loadPreview(type) {
    const container = document.getElementById(`preview-${type}`);
    if (!container) return;
    try {
        const data = await api(`/api/${TYPE_META[SINGULAR[type]]?.api || type}`);
        if (!data || data.length === 0) {
            container.innerHTML = '<div class="empty-state">暂无数据</div>';
            return;
        }
        const items = data.slice(0, 5);
        const single = SINGULAR[type] || type;
        container.innerHTML = items.map(item => `
            <div class="tool-preview-item" data-action="detail" data-type="${esc(single)}" data-name="${esc(item.name)}">
                <span class="tool-preview-icon">${getTypeIcon(single)}</span>
                <div style="flex:1;min-width:0">
                    <div class="tool-preview-name">${esc(item.name)}</div>
                    <div class="tool-preview-desc">${esc(item.description || "暂无描述")}</div>
                </div>
            </div>
        `).join("");
    } catch (e) {
        container.innerHTML = '<div class="error-state">加载失败</div>';
    }
}

// ── 清单页 ──
async function loadList(grid) {
    const apiUrl = grid.dataset.api;
    const type = grid.dataset.type;
    try {
        const data = await api(apiUrl);
        if (!data || data.length === 0) {
            grid.innerHTML = '<div class="empty-state">暂无数据</div>';
            return;
        }
        renderToolCards(grid, data, type);

        // 本地筛选（用 oninput 覆盖赋值，避免刷新时监听器叠加；闭包 data 引用本次 load 数据）
        const searchInput = document.getElementById("listSearch");
        if (searchInput) {
            searchInput.oninput = () => {
                const q = searchInput.value.toLowerCase().trim();
                const filtered = data.filter(item =>
                    !q || item.name?.toLowerCase().includes(q) ||
                    item.description?.toLowerCase().includes(q)
                );
                renderToolCards(grid, filtered, type);
            };
        }
    } catch (e) {
        grid.innerHTML = '<div class="error-state">加载失败，请刷新重试</div>';
    }
}

function renderToolCards(container, items, type) {
    if (items.length === 0) {
        container.innerHTML = '<div class="empty-state">没有匹配的工具</div>';
        return;
    }
    // 清单页 dataset.type 是复数（skills/hooks/...），TYPE_META/getBadge/data-type 契约是单数 —— 统一转换
    const single = SINGULAR[type] || type;
    const badgeClass = TYPE_META[single]?.badgeClass || "";
    container.innerHTML = items.map(item => {
        const badge = getBadge(item, single);
        const meta = getMeta(item, single);
        return `
            <div class="tool-card" data-action="detail" data-type="${esc(single)}" data-name="${esc(item.name)}">
                <div class="tool-card-header">
                    <div class="tool-card-name">${esc(item.name)}</div>
                    ${badge ? `<span class="tool-card-badge ${badgeClass}">${badge}</span>` : ""}
                </div>
                <div class="tool-card-desc">${esc(item.description || "暂无描述")}</div>
                ${meta ? `<div class="tool-card-meta">${meta}</div>` : ""}
            </div>
        `;
    }).join("");
}

function getBadge(item, type) {
    if (type === "mcp") return item.scope === "project" ? "项目" : "全局";
    if (type === "cli") return esc(item.category || "");
    if (type === "hook") return item.blocking ? "阻塞" : "非阻塞";
    if (type === "plugin") return item.version ? `v${esc(item.version)}` : "";
    return "";
}

function getMeta(item, type) {
    if (type === "mcp") return item.command ? `<span class="tool-card-meta-tag">⚡ ${esc(item.command)}</span>` : "";
    if (type === "cli") {
        let parts = [];
        if (item.version) parts.push(`<span class="tool-card-meta-tag">📌 v${esc(item.version)}</span>`);
        if (item.path) parts.push(`<span class="tool-card-meta-tag">📁 ${esc(item.path)}</span>`);
        return parts.join("");
    }
    if (type === "hook") return `<span class="tool-card-meta-tag">📌 ${esc(item.event)}</span>`;
    if (type === "plugin") {
        let parts = [];
        if (item.skills?.length) parts.push(`<span class="tool-card-meta-tag">📦 ${item.skills.length} 技能</span>`);
        if (item.commands?.length) parts.push(`<span class="tool-card-meta-tag">📝 ${item.commands.length} 命令</span>`);
        return parts.join("");
    }
    return "";
}

// ── 搜索 ──
async function loadSearch() {
    const params = new URLSearchParams(window.location.search);
    let q = params.get("q") || "";

    const searchInput = document.getElementById("searchInput");
    if (searchInput) {
        searchInput.value = q;
        searchInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                const val = searchInput.value.trim();
                window.location.href = `/search?q=${encodeURIComponent(val)}`;
            }
        });
    }

    if (!q) {
        document.getElementById("searchResults").innerHTML = '<div class="empty-state">输入关键词搜索所有工具</div>';
        return;
    }

    try {
        const data = await api(`/api/search?q=${encodeURIComponent(q)}`);
        const container = document.getElementById("searchResults");
        if (data.length === 0) {
            container.innerHTML = `<div class="empty-state">没有找到与"${esc(q)}"相关的工具</div>`;
            return;
        }

        // 按类型分组
        const groups = {};
        data.forEach(item => {
            const t = item.type || "unknown";
            if (!groups[t]) groups[t] = [];
            groups[t].push(item);
        });

        let html = `<div class="search-intro">
            <p>找到 <strong>${data.length}</strong> 个与"${esc(q)}"相关的结果</p>
        </div>`;
        for (const [type, items] of Object.entries(groups)) {
            html += `<div class="search-group">`;
            html += `<div class="search-group-title">${TYPE_META[type]?.icon || "📦"} ${TYPE_META[type]?.label || esc(type)} <span class="count-badge">${items.length}</span></div>`;
            html += `<div class="tool-grid">`;
            html += items.map(item => {
                const bc = TYPE_META[type]?.badgeClass || "";
                return `
                <div class="tool-card" data-action="detail" data-type="${esc(type)}" data-name="${esc(item.name)}">
                    <div class="tool-card-header">
                        <div class="tool-card-name">${esc(item.name)}</div>
                        <span class="tool-card-badge ${bc}">${TYPE_META[type]?.label || esc(type)}</span>
                    </div>
                    <div class="tool-card-desc">${esc(item.description || "暂无描述")}</div>
                </div>
            `}).join("");
            html += `</div></div>`;
        }
        container.innerHTML = html;
    } catch (e) {
        document.getElementById("searchResults").innerHTML = '<div class="error-state">搜索失败</div>';
    }
}

// ── 全局工具文档 ──
async function loadDocs() {
    const container = document.getElementById("docsContent");
    const tsEl = document.getElementById("docsTimestamp");
    try {
        const data = await api("/api/docs");
        // AI 描述文件条数（0 显示未配置）
        const aiCount = data.ai_desc_count || 0;
        const aiLabel = aiCount > 0 ? ` · AI 描述文件：${aiCount} 条` : " · AI 描述文件：未配置";
        tsEl.textContent = `最后更新：${data.timestamp} · 共 ${data.total} 个工具${aiLabel}`;

        let html = "";
        for (const group of data.groups) {
            const typeKey = group.type;
            html += `<div class="docs-group">`;
            html += `<div class="docs-group-header" data-action="toggle-collapse">
                <span class="category-dot ${typeKey}"></span>
                <span class="docs-group-title">${group.icon} ${group.label}</span>
                <span class="docs-group-count">${group.count}</span>
                <span class="docs-toggle">▾</span>
            </div>`;

            // 怎么用提示
            html += `<div class="docs-usage">💡 ${esc(group.usage)}</div>`;

            // 表格
            html += `<div class="docs-table-wrap">`;
            html += `<table class="docs-table">
                <thead><tr>
                    <th style="width:25%">工具名</th>
                    <th style="width:45%">用途说明</th>
                    <th style="width:30%">详情</th>
                </tr></thead><tbody>`;

            for (const item of group.items) {
                const desc = item._description_cn || item.description || "暂无描述";
                let detail = getDocDetail(item, typeKey);
                html += `<tr data-action="detail" data-type="${esc(typeKey)}" data-name="${esc(item.name)}">
                    <td class="docs-name">${esc(item.name)}</td>
                    <td class="docs-desc">${esc(desc)}</td>
                    <td class="docs-detail">${detail}</td>
                </tr>`;
            }

            html += `</tbody></table></div>`;
            html += `</div>`;
        }
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = '<div class="error-state">加载失败</div>';
        tsEl.textContent = "加载失败";
    }
}

function getDocDetail(item, type) {
    if (type === "skill") return item.sub_skills?.length ? `${item.sub_skills.length} 个子技能` : "";
    if (type === "mcp") return item.scope === "project" ? "项目级配置" : "全局配置";
    if (type === "cli") return [item.version ? `v${esc(item.version)}` : "", esc(item.category || "")].filter(Boolean).join(" · ");
    if (type === "hook") return esc(item.event);
    if (type === "plugin") {
        let parts = [];
        if (item.skills?.length) parts.push(`${item.skills.length} 技能`);
        if (item.commands?.length) parts.push(`${item.commands.length} 命令`);
        return parts.join(" · ") || (item.version ? `v${esc(item.version)}` : "");
    }
    if (type === "command") return "斜杠命令";
    return "";
}

async function refreshDocs(btn) {
    const origText = btn ? btn.textContent : "";
    if (btn) {
        btn.textContent = "⏳ 更新描述中...";
        btn.disabled = true;
    }

    const tsEl = document.getElementById("docsTimestamp");
    if (tsEl) tsEl.textContent = "正在更新工具描述...";

    try {
        // 第一步：更新缺失的描述
        const upData = await apiPost("/api/update-descriptions");
        // 第二步：重新加载文档
        await loadDocs();
        // 显示更新统计
        if (upData.updated > 0) {
            if (tsEl) tsEl.textContent += ` · 新增 ${upData.updated} 条中文描述`;
        }
    } catch (e) {
        if (tsEl) tsEl.textContent = "更新失败，请重试";
        // 尝试加载已有数据
        try { await loadDocs(); } catch(e2) {}
    } finally {
        if (btn) {
            btn.textContent = origText || "🔄 更新文档";
            btn.disabled = false;
        }
    }
}

// ── 详情页（独立页面） ──
async function loadDetail(type, name) {
    const container = document.getElementById("detailContent");
    try {
        const data = await api(`/api/${type}/${encodeURIComponent(name)}`);
        container.innerHTML = buildDetailHTML(data, type);
        // 滚动到顶部
        window.scrollTo({top: 0, behavior: 'smooth'});
    } catch (e) {
        container.innerHTML = '<div class="error-state">加载失败，工具可能已被移除</div>';
    }
}

// 跳转到详情页（替代弹窗）
function goToDetail(type, name) {
    window.location.href = `/detail/${type}/${encodeURIComponent(name)}`;
}

function buildDetailHTML(item, type) {
    let html = "";

    // 类型标签
    html += `<div style="margin-bottom:16px"><span class="type-tag ${TYPE_META[type]?.badgeClass||''}">${getTypeIcon(type)} ${TYPE_META[type]?.label||esc(type)}</span></div>`;

    // 通用信息
    html += section("名称", item.name);
    // 详细描述（带段落格式）
    const desc = item._description_cn || item.description;
    if (desc) html += section("描述", `<div class="detail-desc-text">${esc(desc)}</div>`, {html:true});
    if (item.path) html += section("路径", item.path, {code:true});

    // 类型特有
    if (type === "skill") {
        if (item.plugin_name) html += section("所属插件", `<span class="detail-tag">${esc(item.plugin_name)}</span>`, {html:true});
        if (item.sub_skills?.length) {
            html += sectionTags("子技能", item.sub_skills);
        }
        if (item.source) html += section("来源", item.source, {code:true});
        html += `<div class="detail-section"><button class="action-btn" data-action="copy-cmd" data-name="${esc(item.name)}">📋 复制调用命令 /${esc(item.name)}</button></div>`;
    }
    if (type === "mcp") {
        html += section("启动命令", `${item.command} ${(item.args||[]).join(" ")}`, {code:true});
        html += section("作用范围", item.scope === "project" ? `项目级 (${item.project_path || ""})` : "全局");
        html += `<div class="detail-section"><button class="action-btn" data-action="test-mcp" data-name="${esc(item.name)}">🔄 测试连接</button><div id="mcpTestResult"></div></div>`;
    }
    if (type === "cli") {
        if (item.version) html += section("版本", `v${item.version}`);
        if (item.category) html += section("类别", item.category);
        html += `<div class="detail-section"><button class="action-btn" data-action="cli-help" data-name="${esc(item.name)}">📄 查看 --help</button><div id="cliHelpResult"></div></div>`;
    }
    if (type === "hook") {
        html += section("事件", item.event);
        html += section("脚本", item.script, {code:true});
        html += section("阻塞", item.blocking ? "是 ⏸️" : "否");
        // hook 优先用后端契约的 id 寻址（如 PreToolUse:0:0），name 兜底
        html += `<div class="detail-section"><button class="action-btn ${item.enabled ? 'success' : 'danger'}" data-action="toggle-hook" data-name="${esc(item.id || item.name)}">${item.enabled ? '✅ 已启用' : '⛔ 已禁用'}</button></div>`;
    }
    if (type === "plugin") {
        if (item.version) html += section("版本", `v${item.version}`);
        if (item.author) {
            const authorStr = typeof item.author === 'object' ? item.author.name || JSON.stringify(item.author) : item.author;
            html += section("作者", authorStr);
        }
        if (item.skills?.length) html += sectionTags("包含技能", item.skills);
        if (item.commands?.length) html += sectionTags("包含命令", item.commands);
        if (item.agents?.length) html += sectionTags("包含 Agents", item.agents);
    }
    if (type === "command") {
        if (item.content) html += section("内容", item.content, {code:true});
        html += `<div class="detail-section"><button class="action-btn" data-action="copy-cmd" data-name="${esc(item.name)}">📋 复制命令名</button></div>`;
    }

    // ── 具体用法（优先用工具级别的 _usage_cn，无则用类型通用模板） ──
    if (item._usage_cn) {
        // 工具级具体用法：全部转义（含 • 开头行，防止 desc_cache 内嵌工具名的存储型 XSS）
        const usageLines = item._usage_cn.split('\n').filter(l => l.trim());
        let usageHTML = usageLines.map(line => `<div class="usage-line">${esc(line.trim())}</div>`).join('');
        html += `<div class="detail-usage"><div class="usage-title">📖 具体用法</div>${usageHTML}</div>`;
    } else {
        // 类型通用用法（降级方案）
        const fallbackMap = {
            skill: `• <b>自动触发</b> — 对话中描述相关需求时自动使用<br>• <b>手动调用</b> — 输入 <code>/${esc(item.name)}</code> 按回车`,
            mcp: `• <b>自动调用</b> — Claude 分析需求后选择合适的 MCP 服务<br>• ${item.scope === 'project' ? '项目级配置，仅当前项目可用' : '全局配置，所有项目可用'}<br>• 可点击上方「测试连接」验证连通性`,
            cli: `• 在终端中运行 <code>${esc(item.name)} --help</code> 查看帮助<br>• 运行 <code>${esc(item.name)} --version</code> 查看版本<br>• 可点击上方「查看 --help」快速查看帮助输出`,
            hook: `• 事件 <code>${esc(item.event)}</code> 触发时自动运行<br>• ${item.blocking ? '⏸️ 阻塞模式，会等待脚本完成' : '异步执行，不影响主流程'}<br>• 可点击上方按钮切换启用/禁用`,
            plugin: `• 安装后自动生效，无需额外配置<br>• 技能调用：输入 <code>/技能名</code> 或描述需求<br>• 命令调用：输入 <code>/命令名</code> 即可执行`,
            command: `• 在对话中输入 <code>/${esc(item.name)}</code> 执行<br>• Claude 自动加载对应的预定义内容<br>• 适合高频标准化操作的快捷调用`,
        };
        const fallback = fallbackMap[type] || "";
        if (fallback) {
            html += `<div class="detail-usage"><div class="usage-title">💡 怎么用</div>${fallback}</div>`;
        }
    }

    return html;
}

function section(label, value, opts = {}) {
    const { code = false, html = false } = opts;
    const v = html ? value : esc(value);
    return `
        <div class="detail-section">
            <div class="detail-label">${esc(label)}</div>
            <div class="detail-value${code ? ' code' : ''}">${v}</div>
        </div>
    `;
}

// 标签组 section：名字列表 → 逐个转义的 detail-tag（#37，收敛 4 处同构调用）
function sectionTags(label, names) {
    return section(label, names.map(s => `<span class="detail-tag">${esc(s)}</span>`).join(" "), {html:true});
}

// ── 快速操作 ──
// 在按钮后插入/更新一个错误提示块
function showActionError(btn, msg) {
    if (!btn) return;
    let err = btn.nextElementSibling;
    if (!err || !err.classList.contains("action-result")) {
        err = document.createElement("div");
        err.className = "action-result";
        btn.insertAdjacentElement("afterend", err);
    }
    err.textContent = "❌ " + msg;
}

// 清除按钮后的错误提示块
function clearActionError(btn) {
    if (!btn) return;
    const err = btn.nextElementSibling;
    if (err && err.classList.contains("action-result")) err.remove();
}

async function testMCP(name, btn) {
    if (btn) {
        btn.disabled = true;
        btn.textContent = "测试中...";
    }
    const resultDiv = document.getElementById("mcpTestResult");
    try {
        const data = await apiPost(`/api/mcp/${encodeURIComponent(name)}/test`);
        if (resultDiv) resultDiv.innerHTML = `<div class="action-result">${data.success ? "✅ " + esc(data.output) : "❌ " + esc(data.error)}</div>`;
    } catch(e) {
        if (resultDiv) resultDiv.innerHTML = `<div class="action-result">❌ 请求失败: ${esc(e.message)}</div>`;
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = "🔄 测试连接";
        }
    }
}

async function toggleHook(id, btn) {
    if (btn) btn.disabled = true;
    try {
        const data = await apiPost(`/api/hooks/${encodeURIComponent(id)}/toggle`);
        if (data.success) {
            if (btn) {
                btn.className = `action-btn ${data.enabled ? 'success' : 'danger'}`;
                btn.textContent = data.enabled ? "✅ 已启用" : "⛔ 已禁用";
            }
            clearActionError(btn);
        } else {
            showActionError(btn, data.error || "切换失败");
        }
    } catch(e) {
        showActionError(btn, e.message || "请求失败");
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function viewCLIHelp(name, btn) {
    const resultDiv = document.getElementById("cliHelpResult");
    if (!resultDiv) return;
    resultDiv.innerHTML = "加载中...";
    try {
        const res = await fetch(`/api/cli/${encodeURIComponent(name)}/help`);
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        resultDiv.innerHTML = `<div class="action-result">${esc(data.output || data.error || "无输出")}</div>`;
    } catch(e) {
        resultDiv.innerHTML = `<div class="action-result">❌ 加载失败: ${esc(e.message)}</div>`;
    }
}

function copyCommand(name, btn) {
    // 连点防竞态：首次点击固化原始文案，后续点击不再把"已复制"当 orig
    if (btn && !btn.dataset.origText) btn.dataset.origText = btn.textContent;
    const write = (navigator.clipboard && navigator.clipboard.writeText)
        ? navigator.clipboard.writeText(`/${name}`)
        : Promise.reject(new Error("clipboard 不可用"));
    write.then(() => {
        if (!btn) return;
        btn.textContent = "✅ 已复制";
        clearActionError(btn);
        setTimeout(() => { btn.textContent = btn.dataset.origText; }, 1500);
    }).catch(() => {
        showActionError(btn, "复制失败，请手动复制");
    });
}

// ── 使用统计 ──
async function loadUsageStats() {
    const container = document.getElementById("usageStats");
    if (!container) return;
    try {
        const data = await api("/api/stats/usage");
        if (!data.top || data.top.length === 0) {
            container.innerHTML = '<div class="usage-empty">暂无统计数据（需要先使用一些工具）</div>';
            return;
        }
        let html = `<div style="font-size:12px;color:var(--text-secondary);margin-bottom:10px">
            共记录 <strong>${data.total_calls}</strong> 次工具调用
        </div><div class="usage-grid">`;
        data.top.slice(0, 24).forEach(item => {
            // 现结构无独立 rank 元素，仅给 count 追加 mono（不改不删旧 class）
            html += `<div class="usage-item">
                <span class="usage-name">${esc(item.name)}</span>
                <span class="usage-count mono">${item.count}</span>
            </div>`;
        });
        html += `</div>`;
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = '<div class="usage-empty">统计加载失败</div>';
    }
}

// ── 路径设置页 ──
async function loadSettings() {
    const page = document.getElementById("settingsPage");
    if (!page) return;
    try {
        const data = await api("/api/paths");
        ["skill_paths", "cli_paths", "extra_mcp_project_dirs"].forEach(group => {
            const listEl = page.querySelector(`.path-list[data-group="${group}"]`);
            if (!listEl) return;
            const key = {skill_paths: "skill", cli_paths: "cli", extra_mcp_project_dirs: "mcp_extra"}[group];
            const items = data.merged[key] || [];
            if (!items.length) {
                listEl.innerHTML = '<div class="empty-state">暂无路径</div>';
                return;
            }
            listEl.innerHTML = items.map(p => {
                const ok = data.exists[p];
                const isDefault = (data.defaults[key] || []).includes(p);
                return `<div class="path-row">
                    <span class="path-text">${esc(p)}</span>
                    <span class="path-badge ${ok ? "ok" : "missing"}">${ok ? "✓ 存在" : "✗ 不存在"}</span>
                    ${isDefault ? '<span class="path-badge default">默认</span>' : ""}
                    <button class="btn btn-sm" data-action="path-open" data-path="${esc(p)}">📂 打开</button>
                    ${isDefault ? "" : `<button class="btn btn-sm btn-danger" data-action="path-delete" data-group="${esc(group)}" data-path="${esc(p)}">✕ 删除</button>`}
                </div>`;
            }).join("");
        });
    } catch (e) {
        page.querySelectorAll(".path-list").forEach(el => el.innerHTML = '<div class="error-state">加载失败</div>');
    }
}

// path-add：把新路径追加到该组 config 值后整体提交（默认项不写入 config，只存自定义项）
async function pathAdd(el) {
    const group = el.dataset.group;
    const page = document.getElementById("settingsPage");
    const input = page ? page.querySelector(`input[data-group-input="${group}"]`) : null;
    const val = input ? input.value.trim() : "";
    if (!val) { alert("请输入目录绝对路径"); return; }
    try {
        // 再 GET 一次拿最新 config，避免本地状态过期覆盖他人改动
        const cur = await api("/api/paths");
        const configList = (cur.config && cur.config[group]) || [];
        if (configList.includes(val)) { alert("该路径已存在于自定义配置中"); return; }
        const res = await apiPostJson("/api/paths", {group, paths: [...configList, val]});
        if (res && res.success === false) { alert(res.error || "保存失败"); return; }
        if (input) input.value = "";
        loadSettings();
    } catch (e) {
        alert("添加失败：" + (e.message || "未知错误"));
    }
}

// path-delete：从该组 config 过滤掉目标路径后整体提交（默认项按钮不渲染，无需防删）
async function pathDelete(el) {
    const group = el.dataset.group;
    const path = el.dataset.path;
    try {
        const cur = await api("/api/paths");
        const configList = (cur.config && cur.config[group]) || [];
        const res = await apiPostJson("/api/paths", {group, paths: configList.filter(p => p !== path)});
        if (res && res.success === false) { alert(res.error || "保存失败"); return; }
        loadSettings();
    } catch (e) {
        alert("删除失败：" + (e.message || "未知错误"));
    }
}

// path-open / open-file：交给后端白名单校验（已配置路径或已知用户数据文件）
async function pathOpen(el) {
    try {
        const res = await apiPostJson("/api/paths/open", {path: el.dataset.path});
        if (res && res.success === false) alert(res.error || "打开失败");
    } catch (e) {
        alert("打开失败：" + (e.message || "未知错误"));
    }
}

// ai-desc-reset：从示例恢复 ai_descriptions.json（404/409 走 catch 弹出服务端 error）
async function aiDescReset() {
    if (!confirm("确定要从示例文件恢复 ai_descriptions.json 吗？\n（目标文件已存在时不会覆盖）")) return;
    try {
        const res = await apiPostJson("/api/paths/reset-ai-desc", {});
        if (res && res.success === false) { alert(res.error || "恢复失败"); return; }
        alert("已恢复示例文件");
        loadSettings();
    } catch (e) {
        alert("恢复失败：" + (e.message || "未知错误"));
    }
}

// ── 导出 ──
async function exportTools(format, btn) {
    const orig = btn ? btn.textContent : "";
    if (btn) {
        btn.textContent = "导出中...";
        btn.disabled = true;
    }
    try {
        const res = await fetch(`/api/export?format=${format}&refresh=1`);
        if (!res.ok) throw new Error("HTTP " + res.status);
        if (format === "json") {
            const data = await res.json();
            const blob = new Blob([JSON.stringify(data, null, 2)], {type:"application/json"});
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `cc-toolbox-export-${new Date().toISOString().slice(0,10)}.json`;
            a.click();
            URL.revokeObjectURL(url);
        } else {
            const text = await res.text();
            const blob = new Blob([text], {type:"text/markdown"});
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `cc-toolbox-export-${new Date().toISOString().slice(0,10)}.md`;
            a.click();
            URL.revokeObjectURL(url);
        }
    } catch(e) {
        alert("导出失败: " + (e.message || "未知错误"));
    } finally {
        if (btn) {
            btn.textContent = orig;
            btn.disabled = false;
        }
    }
}

// ── 刷新 ──
function refreshAll() {
    fetchSummary(true);   // 强制重拉 summary，侧栏计数与仪表盘共用（#34）
    updateNavCounts();
    loadDashboard();
    loadUsageStats();
}

function refreshList() {
    const grid = document.getElementById("toolGrid");
    if (grid) loadList(grid);
}

// ── 工具函数 ──
async function api(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error("HTTP " + res.status);  // 与 apiPost 错误文案格式统一
    return res.json();
}

// POST 请求 + res.ok 检查 + 解析 JSON（#37 统一收敛）
async function apiPost(url) {
    const res = await fetch(url, {method:"POST"});
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
}

// JSON body 的 POST：非 2xx 时尽量取出服务端 error 字段拼进 Error，便于 alert 具体原因
async function apiPostJson(url, body) {
    const res = await fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body),
    });
    if (!res.ok) {
        let msg = "HTTP " + res.status;
        try {
            const data = await res.json();
            if (data && data.error) msg = data.error;
        } catch (_) { /* 响应非 JSON，保留 HTTP 状态码文案 */ }
        throw new Error(msg);
    }
    return res.json();
}

function esc(s) {
    if (s == null) return "";
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function getTypeIcon(type) {
    return TYPE_META[type]?.icon || "📦";
}

// ── 事件委托：统一处理动态生成的 data-action 元素 ──
document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-action]");
    if (!el) return;
    const { action, type, name, format } = el.dataset;
    switch (action) {
        case "detail": goToDetail(type, name); break;
        case "toggle-hook": toggleHook(name, el); break;   // name 位为 hook 的 id
        case "test-mcp": testMCP(name, el); break;
        case "cli-help": viewCLIHelp(name, el); break;
        case "copy-cmd": copyCommand(name, el); break;
        case "export": exportTools(format, el); break;
        case "refresh-docs": refreshDocs(el); break;
        case "refresh-all": refreshAll(); break;
        case "refresh-list": refreshList(); break;
        case "refresh-usage": loadUsageStats(); break;
        // el 为分组头自身，父元素才是 docs-group（#37 内联 onclick 改委托）
        case "toggle-collapse": el.parentElement.classList.toggle("docs-collapsed"); break;
        // 路径设置页
        case "path-add": pathAdd(el); break;
        case "path-delete": pathDelete(el); break;
        case "path-open": pathOpen(el); break;
        case "open-file": pathOpen(el); break;   // 与 path-open 同走白名单打开接口
        case "ai-desc-reset": aiDescReset(); break;
        case "refresh-settings": loadSettings(); break;
        default: break;
    }
});
