/* =====================================================================
   AIVerse · AI 漫剧工厂 —— 前端 SPA
   文档 §3 核心体验 / §15 抽卡 / §16 局部重生成 / §18 时间线 / §23 队列
   ===================================================================== */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fileUrl = (pid, rel) => `/files/${pid}/${String(rel || '').split('/').map(encodeURIComponent).join('/')}`;
const fmtDur = (s) => { s = Number(s) || 0; const m = Math.floor(s / 60); return m ? `${m}分${Math.round(s % 60)}秒` : `${s.toFixed(1)}秒`; };

/* ---------------------------------------------------------------- API */
const api = {
  async req(method, path, body) {
    const opt = { method, headers: { 'Content-Type': 'application/json' } };
    if (body !== undefined) opt.body = JSON.stringify(body);
    const r = await fetch(path, opt);
    let data = {};
    try { data = await r.json(); } catch (e) { data = {}; }
    if (!r.ok) throw new Error(data.error || `${r.status} ${r.statusText}`);
    return data;
  },
  get: (p) => api.req('GET', p),
  post: (p, b = {}) => api.req('POST', p, b),
  patch: (p, b = {}) => api.req('PATCH', p, b),
  del: (p) => api.req('DELETE', p),
};

/* ---------------------------------------------------------------- State */
const S = {
  meta: null,
  projects: [],
  pid: null,
  detail: null,
  stage: 'script',
  script: '',
  shots: [],
  drawerOpen: false,
  tasks: [],
  stats: {},
  busy: false,
  timer: null,
  view: 'home',        // home | workspace | runtime
  runtime: null,       // 环境部署状态
  runtimePlan: null,
};

/* ---------------------------------------------------------------- Toast */
function toast(msg, kind = '', ms = 3200) {
  const d = document.createElement('div');
  d.className = 'toast ' + kind;
  d.innerHTML = esc(msg);
  $('#toast-root').appendChild(d);
  setTimeout(() => { d.style.opacity = '0'; d.style.transition = 'opacity .3s'; setTimeout(() => d.remove(), 320); }, ms);
}

/* ---------------------------------------------------------------- Modal */
function modal(html, { narrow = false, onOpen } = {}) {
  const root = $('#modal-root');
  root.innerHTML = `<div class="mask" data-act="mask-close"><div class="modal ${narrow ? 'narrow' : ''}" data-stop>${html}</div></div>`;
  if (onOpen) onOpen(root.querySelector('.modal'));
}
function closeModal() { $('#modal-root').innerHTML = ''; }

/* ================================================================ BOOT */
async function boot() {
  try {
    S.meta = await api.get('/api/meta');
  } catch (e) {
    $('#app').innerHTML = `<div class="boot"><div class="boot-logo">AIVerse</div>
      <div class="boot-text">后端未连接：${esc(e.message)}<br/>请通过 <b>python run.py</b> 启动本地服务后刷新。</div></div>`;
    return;
  }
  // 安装包首次运行 / 桌面「一键部署」快捷方式：直接落在环境部署页
  const q = new URLSearchParams(location.search);
  if (q.get('view') === 'runtime') S.view = 'runtime';
  await loadProjects();
  render();
  if (S.view === 'runtime') await loadRuntime();
}

async function loadProjects() {
  const r = await api.get('/api/projects');
  S.projects = r.projects || [];
}

async function loadDetail() {
  if (!S.pid) return;
  S.detail = await api.get(`/api/projects/${S.pid}`);
  const sc = await api.get(`/api/projects/${S.pid}/script`);
  S.script = sc.script || '';
  S.shots = (await api.get(`/api/projects/${S.pid}/shots`)).shots || [];
}

/* ================================================================ RENDER */
function render() {
  if (S.view === 'runtime') return renderRuntime();
  if (!S.pid) return renderHome();
  return renderWorkspace();
}

/* ---------------------------------------------------------------- Home */
function renderHome() {
  const cards = S.projects.length
    ? `<div class="grid g2">${S.projects.map(projCard).join('')}</div>`
    : `<div class="empty"><div class="big">🎬</div>
        <div>还没有项目。导入一个剧本，AI 开始逐阶段制作。</div></div>`;

  $('#app').innerHTML = `
  <div class="shell">
    <aside class="side">
      <div class="brand">
        <div class="brand-row">
          <div class="brand-mark">AI</div>
          <div>
            <div class="brand-name">AI Studio</div>
            <div class="brand-sub">AIVerse</div>
          </div>
        </div>
      </div>
      <div class="stages">
        <div class="stages-title">产品理念</div>
        <div class="hint" style="margin:4px 8px">
          <b>AI 负责生产，人负责决策。</b><br/>
          剧本 → 角色 → 场景 → 分镜 → 视频 → 配音 → 剪辑 → 成片。<br/>
          每个阶段都能 <b>抽卡 / 局部重生成 / 返回上一阶段</b>。
        </div>
        <div class="stages-title" style="margin-top:14px">能力概览</div>
        ${capRow('模型无关', 'H3 / Wan / Flux / 任意 OpenAI 兼容', '✓')}
        ${capRow('工作流引擎', '8 阶段管线 + 审核门', '✓')}
        ${capRow('抽卡系统', '候选 A/B/C/D，锁定重抽', '✓')}
        ${capRow('任务队列', '暂停 / 继续 / 重试 / 插队', '✓')}
        ${capRow('成本统计', '本地算力 + 云端费用', '✓')}
      </div>
      <div class="side-foot">
        <button class="btn sm primary" data-act="open-runtime">⚡ 环境部署</button>
        <button class="btn sm ghost" data-act="open-settings">⚙ 设置</button>
      </div>
    </aside>
    <div class="main">
      <div class="topbar">
        <div class="crumb">AI 漫剧工厂</div>
        <div class="spacer"></div>
        ${gpuBadge()}${ffmpegBadge()}
        <button class="btn primary" data-act="new-project">＋ 新建项目</button>
      </div>
      <div class="work">
        <div class="head">
          <div>
            <h1>我的项目</h1>
            <p>共 ${S.projects.length} 个项目 · 数据全部保存在本地 projects/ 目录</p>
          </div>
        </div>
        ${deployBanner()}
        ${cards}
      </div>
    </div>
  </div>`;
}

function capRow(t, d, mark) {
  return `<div class="stage" style="cursor:default">
    <div class="dot" style="background:rgba(47,191,122,.16);border-color:rgba(47,191,122,.5);color:#8ff0c0">${mark}</div>
    <div class="stage-txt"><div class="stage-name">${esc(t)}</div><div class="stage-desc">${esc(d)}</div></div>
  </div>`;
}

function projCard(p) {
  const prog = p.progress || { percent: 0, done: 0, total: 8 };
  const c = p.counts || {};
  return `<div class="card" style="cursor:pointer" data-act="open-project" data-pid="${p.id}">
    <div class="card-h">
      <h3>${esc(p.name)}</h3>
      <span class="chip grey">${esc(p.style_name || '')}</span>
      <span class="chip grey">${esc(p.aspect || '')}</span>
      <span class="chip grey">${esc(p.resolution || '')}</span>
      <div class="spacer" style="flex:1"></div>
      <button class="btn xs danger" data-act="del-project" data-pid="${p.id}">删除</button>
    </div>
    <div class="proj-bar"><i style="width:${prog.percent}%"></i></div>
    <div class="proj-meta" style="margin-top:9px">
      进度 ${prog.done}/${prog.total} 阶段 · 角色 ${c.character || 0} · 场景 ${c.scene || 0} ·
      道具 ${c.prop || 0} · 镜头 ${c.shots || 0}
    </div>
  </div>`;
}

function gpuBadge() {
  const g = S.meta.gpu, top = g.gpus[0];
  const cls = top.vram_gb >= 8 ? 'ok' : (top.vram_gb > 0 ? 'warn' : 'bad');
  return `<span class="badge ${cls}" data-act="open-settings" title="${esc(g.tips.join(' / '))}">
    GPU <b>${esc(top.name)}</b> ${top.vram_gb}GB · ${esc(g.mode)}</span>`;
}
function ffmpegBadge() {
  const f = S.meta.ffmpeg;
  return `<span class="badge ${f.available ? 'ok' : 'warn'}" title="${esc(f.hint)}">FFmpeg <b>${f.available ? '就绪' : '未安装'}</b></span>`;
}

function deployBanner() {
  const r = S.runtime;
  if (!r) return '';
  const inst = r.installed || {};
  const ready = inst.h3_weights && inst.comfyui && inst.torch;
  const gpu = ((S.meta && S.meta.gpu && S.meta.gpu.gpus) || [])[0] || {};
  if (ready) {
    return `<div class="card" style="margin-bottom:14px;border-color:rgba(47,191,122,.35)">
      <div class="card-h"><h3>本地推理环境已就绪</h3>
        <span class="chip ok">H3 可本地出片</span>
        <div class="spacer" style="flex:1"></div>
        <button class="btn sm ghost" data-act="open-runtime">查看部署详情</button></div>
      <div class="hint">显卡 ${esc(gpu.name || '未知')} · 运行时占用 ${r.disk_used_gb || 0} GB ·
        ComfyUI ${inst.comfy_running ? '运行中' : '未运行（生成时自动拉起）'}</div>
    </div>`;
  }
  const running = r.running || r.status === 'running';
  const done = Object.values(r.steps || {}).filter((s) => s.status === 'done').length;
  const total = Object.keys(r.steps || {}).length;
  return `<div class="card" style="margin-bottom:14px;border-color:rgba(79,140,255,.35)">
    <div class="card-h"><h3>${running ? '正在部署本地推理环境' : '还没有本地推理环境'}</h3>
      ${running ? `<span class="chip warn">${done}/${total} 步完成</span>` : ''}
      <div class="spacer" style="flex:1"></div>
      <button class="btn sm primary" data-act="open-runtime">${running ? '查看进度' : '⚡ 一键部署'}</button></div>
    <div class="hint">
      本客户端只负责编排，所以本体很小。真正出片的 <b>MiniMax H3</b> 是 33B 参数模型，
      精简版权重 <b>39 GB</b> 起，加上 PyTorch/CUDA 与 ComfyUI 依赖约 2.3 GB —— 这部分不可能塞进安装包。
      点「一键部署」，程序会自动装好全部依赖与权重（含 FFmpeg），之后就能用你的显卡本地出片。
      不方便联网的话，也可以用<b>离线包导入</b>，零下载复制。
    </div>
  </div>`;
}

/* ---------------------------------------------------------------- 环境部署 */
function renderRuntime() {
  const r = S.runtime || {};
  const inst = r.installed || {};
  const plan = S.runtimePlan || (r.plan || null);
  const steps = plan ? plan.steps : [];
  const stateSteps = r.steps || {};
  const running = r.running || r.status === 'running';

  const check = (ok, label, extra = '') =>
    `<div class="dep-item ${ok ? 'ok' : ''}">
       <span class="dep-dot">${ok ? '✓' : '○'}</span>
       <div><div class="dep-name">${esc(label)}</div>
       ${extra ? `<div class="dep-sub">${esc(extra)}</div>` : ''}</div>
     </div>`;

  const h3 = S.h3 || null;

  return `
  <div class="shell">
    <aside class="side">
      <div class="brand">
        <div class="brand-row">
          <div class="brand-mark">AI</div>
          <div><div class="brand-name">AI Studio</div><div class="brand-sub">AIVerse</div></div>
        </div>
      </div>
      <div class="proj">
        <div class="proj-name">环境部署</div>
        <div class="proj-meta">本地推理运行时（H3）</div>
      </div>
      <div class="stages">
        <div class="stages-title">说明</div>
        <div class="hint" style="margin:4px 8px">
          AIVerse 本体只有 <b>9.4 MB</b>，因为它只负责「编排」——
          剧本、角色、分镜、审核、抽卡、剪辑。
          <br/><br/>
          真正出片的算力在 <b>MiniMax H3</b>：33B 参数、精简版 <b>39 GB</b> 权重，
          再加 PyTorch/CUDA 与 ComfyUI 依赖约 2.3 GB。这些不可能塞进一个 9 MB 的 exe，
          全球所有 AI 桌面应用（含 ComfyUI Desktop / Pinokio / EZlaunch）都是首次运行下载。
          <br/><br/>
          所以这里的做法是：<b>装一次，点一下，剩下的全自动</b>。
        </div>
      </div>
      <div class="side-foot">
        <button class="btn sm ghost" data-act="back-home">← 项目列表</button>
        <button class="btn sm ghost" data-act="open-settings">⚙ 设置</button>
      </div>
    </aside>

    <div class="main">
      <div class="topbar">
        <div class="crumb">环境部署 <span class="sep">/</span> <span class="cur">本地 H3 推理运行时</span></div>
        <div class="spacer"></div>
        <span class="badge ${inst.h3_weights ? 'ok' : 'warn'}">H3 权重 <b>${inst.h3_weights ? '就绪' : '未就绪'}</b></span>
        <span class="badge ${inst.comfy_running ? 'ok' : ''}">ComfyUI <b>${inst.comfy_running ? '运行中' : '未运行'}</b></span>
        <button class="btn sm ghost" data-act="refresh-runtime">刷新</button>
      </div>

      <div class="work">
        <div class="head">
          <div>
            <h1>一键部署本地 H3 生产环境</h1>
            <p>自动完成 Python / PyTorch+CUDA / ComfyUI / H3 权重 / FFmpeg 的全部安装，装完即可本地出片</p>
          </div>
          <div class="head-actions">
            ${running
              ? `<button class="btn danger" data-act="runtime-cancel">■ 取消部署</button>`
              : `<button class="btn primary" data-act="runtime-install">⚡ 开始一键部署</button>`}
            <button class="btn" data-act="h3-check">🩺 检测 H3 环境</button>
            <button class="btn ghost" data-act="comfy-start">▶ 启动 ComfyUI</button>
          </div>
        </div>

        ${r.status === 'failed' ? `<div class="card" style="border-color:rgba(255,93,108,.45)">
          <div class="card-h"><h3 style="color:#ffa9b3">部署失败</h3>
            <div class="spacer" style="flex:1"></div>
            <button class="btn sm" data-act="runtime-retry">↻ 重试</button></div>
          <div class="mono">${esc(r.error || '')}</div></div>` : ''}

        <div class="grid g2">
          <div class="card">
            <div class="card-h"><h3>硬件检测</h3>
              <span class="chip ${plan && plan.can_local ? 'ok' : 'warn'}">
                ${plan ? esc(plan.tier.tier) : '—'} 档</span></div>
            ${plan ? `
            <table><tbody>
              <tr><td>显卡</td><td><b>${esc(plan.gpu.name)}</b> · ${plan.gpu.vram_gb} GB</td></tr>
              <tr><td>驱动</td><td>${esc(plan.gpu.driver || '—')}</td></tr>
              <tr><td>内存 / 磁盘可用</td><td>${plan.system.ram_gb} GB / ${plan.system.disk_free_gb} GB</td></tr>
              <tr><td>推荐模型</td><td><b>${esc(plan.model_name)}</b></td></tr>
              <tr><td>部署建议</td><td>${esc(plan.tier.note)}</td></tr>
            </tbody></table>` : '<div class="hint">正在读取硬件信息…</div>'}
          </div>

          <div class="card">
            <div class="card-h"><h3>当前安装状态</h3></div>
            <div class="dep-grid">
              ${check(inst.uv, 'uv 运行时管理器')}
              ${check(inst.python, 'Python 隔离环境')}
              ${check(inst.torch, 'PyTorch + CUDA')}
              ${check(inst.comfyui, 'ComfyUI 执行引擎')}
              ${check(inst.ffmpeg, 'FFmpeg')}
              ${check(inst.h3_weights, 'MiniMax H3 权重', inst.h3_weights ? '' : '约 39 GB 起')}
            </div>
            <div class="hint" style="margin-top:12px">
              运行时目录：<span class="mono">${esc(r.runtime_dir || '')}</span>
              ${r.disk_used_gb ? ` · 已占用 <b>${r.disk_used_gb} GB</b>` : ''}
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-h"><h3>部署计划</h3>
            <span class="sub">按你的显卡自动生成</span>
            <div class="spacer" style="flex:1"></div>
            <select class="inp" style="width:auto" id="rt-mirror" data-act="plan-change">
              <option value="cn" ${plan && plan.mirror === 'cn' ? 'selected' : ''}>国内加速（ModelScope / 清华源）</option>
              <option value="global" ${plan && plan.mirror === 'global' ? 'selected' : ''}>海外直连（HuggingFace）</option>
            </select>
            <select class="inp" style="width:auto" id="rt-model" data-act="plan-change">
              ${(S.runtimeModels || []).map((m) => `<option value="${m.key}" ${plan && plan.model === m.key ? 'selected' : ''}>${esc(m.name)} · ${m.size_gb}GB</option>`).join('') || '<option>—</option>'}
            </select>
          </div>

          ${plan ? `
          <div class="stats" style="margin-bottom:14px">
            ${stat(plan.total_download_human, '需下载总量')}
            ${stat(plan.estimated_minutes + ' 分钟', '预计下载耗时')}
            ${stat(steps.length, '部署步骤')}
            ${stat(plan.can_local ? '本地出片' : '仅云端', '部署后能力')}
          </div>
          ${plan.warnings.map((w) => `<div class="hint" style="margin-bottom:8px">⚠ ${esc(w)}</div>`).join('')}
          ${(r.optional_failed || []).length ? `<div class="hint" style="margin-bottom:8px">
            ⚠ 有可选步骤失败，但**不影响出片**（表格里那几行会标 failed）：
            ${(r.optional_failed || []).map((w) => esc(w)).join('；')}
            <br/>可选步骤主要是 KJNodes 这类加速节点。想要的话可以单独重试那一步。
          </div>` : ''}
          <table><thead><tr><th style="width:26px"></th><th>步骤</th><th style="width:96px">体积</th>
            <th style="width:230px">进度</th><th style="width:74px">状态</th></tr></thead><tbody>
            ${steps.map((s) => {
              const st = stateSteps[s.key] || {};
              const status = st.status || (s.optional ? 'optional' : 'pending');
              const pct = status === 'done' ? 100 : (st.percent || 0);
              const chip = { done: 'ok', running: 'warn', failed: 'bad', pending: 'grey',
                             skipped: 'grey', optional: 'grey' }[status] || 'grey';
              return `<tr>
                <td>${status === 'done' ? '✓' : (status === 'running' ? '<span class="loading"></span>' : '○')}</td>
                <td><b>${esc(s.name)}</b>${s.optional ? ' <span class="chip grey">可选</span>' : ''}
                  <div class="dep-sub">${esc(st.message || s.desc)}</div></td>
                <td>${esc(s.size_human)}</td>
                <td><div class="pbar"><i style="width:${pct}%"></i></div>
                  <div class="dep-sub">${st.speed_mbps ? st.speed_mbps + ' MB/s' : ''} ${pct ? pct.toFixed(1) + '%' : ''}</div></td>
                <td><span class="chip ${chip}">${esc(status)}</span></td>
              </tr>`;
            }).join('')}
          </tbody></table>` : '<div class="hint">正在生成部署计划…</div>'}
        </div>

        <div class="card">
          <div class="card-h"><h3>离线包（完全不用下载）</h3>
            <span class="sub">一台机器装好 → 拷 U 盘 → 其他机器直接导入</span></div>
          <div class="hint" style="margin-bottom:12px">
            如果这台机器不方便长时间联网，或者你要给多台机器装，可以走这条路：
            先在任意一台机器上完成一次部署（或直接下载我们发布的离线包），
            之后所有机器都<b>只复制文件、零下载</b>。
          </div>
          <div class="grid g2">
            <div class="field">
              <label>导入：把离线包路径粘进来</label>
              <input class="inp" id="rt-offline-src" placeholder="D:\AIVerse-Runtime 或 \\NAS\share\AIVerse-Runtime" />
              <div style="margin-top:8px;display:flex;gap:8px">
                <button class="btn primary sm" data-act="offline-import">📥 导入离线运行时</button>
                <button class="btn sm ghost" data-act="offline-verify">校验目录</button>
              </div>
            </div>
            <div class="field">
              <label>导出：把本机运行时打包给别人</label>
              <input class="inp" id="rt-offline-dest" placeholder="E:\  （导出到该目录下的 AIVerse-Runtime）" />
              <div style="margin-top:8px">
                <button class="btn sm" data-act="offline-export">📦 导出离线包</button>
              </div>
            </div>
          </div>
        </div>

        ${h3 ? `<div class="card">
          <div class="card-h"><h3>H3 环境检测</h3>
            <span class="chip ${h3.ok ? 'ok' : 'bad'}">${h3.ok ? '就绪' : '未就绪'}</span></div>
          <div class="hint">${esc(h3.detail || '')}</div>
          ${h3.core_node ? `<div style="margin-top:9px">
            出片节点：<b>${esc(h3.core_node)}</b>
            · 参考图驱动：<b>${h3.reference_capable
              ? esc(h3.ref_core_node || '可用') : '不可用（仅首尾帧）'}</b>
            ${h3.comfyui_version ? `· ComfyUI <b>${esc(h3.comfyui_version)}</b>` : ''}</div>` : ''}
          ${h3.acceleration ? `<div style="margin-top:9px">
            加速节点：SageAttention <b>${h3.acceleration.sage_attention ? '已装' : '未装'}</b> ·
            EasyCache <b>${h3.acceleration.easy_cache ? '已装' : '未装'}</b></div>` : ''}
          ${h3.related_nodes && h3.related_nodes.length ? `<div style="margin-top:9px">
            检测到 H3 相关节点：${h3.related_nodes.map((n) => `<span class="chip" style="margin:2px">${esc(n)}</span>`).join('')}
            <button class="btn xs ghost" style="margin-left:6px" data-act="h3-detect-nodes">自动识别并写入节点映射</button></div>` : ''}
        </div>` : ''}

        <div class="card">
          <div class="card-h"><h3>部署日志</h3>
            <div class="spacer" style="flex:1"></div>
            <span class="sub">${(r.log || []).length} 行</span></div>
          <pre class="mono" style="max-height:280px;overflow:auto;background:#0c1220;border:1px solid var(--line);border-radius:9px;padding:12px">${esc((r.log || []).slice(-80).join('\n') || '（暂无日志）')}</pre>
        </div>
      </div>
    </div>
  </div>`;
}

/* ---------------------------------------------------------------- Workspace */
function renderWorkspace() {
  const d = S.detail;
  const p = d.project;
  const stages = d.stages || [];
  const cur = stages.find((s) => s.key === S.stage) || stages[0];

  $('#app').innerHTML = `
  <div class="shell">
    <aside class="side" id="side">
      <div class="brand">
        <div class="brand-row">
          <div class="brand-mark">AI</div>
          <div style="min-width:0">
            <div class="brand-name">AI Studio</div>
            <div class="brand-sub">AIVerse</div>
          </div>
        </div>
      </div>
      <div class="proj">
        <div class="proj-name">${esc(p.name)}</div>
        <div class="proj-meta">${esc(p.style_name || '')} · ${esc(p.aspect)} · ${esc(p.resolution)} · ${p.mode === 'pro' ? '专业模式' : '新手模式'}</div>
        <div class="proj-bar"><i style="width:${d.progress.percent}%"></i></div>
      </div>
      <div class="stages">
        <div class="stages-title">制作流程</div>
        ${stages.map(stageItem).join('')}
      </div>
      <div class="side-foot">
        <button class="btn sm ghost" data-act="open-runtime">⚡ 环境部署</button>
        <button class="btn sm ghost" data-act="back-home">← 项目列表</button>
      </div>
    </aside>

    <div class="main">
      <div class="topbar">
        <button class="btn sm ghost" data-act="toggle-side" style="display:none">☰</button>
        <div class="crumb">${esc(p.name)} <span class="sep">/</span> <span class="cur">${esc(cur.name)}</span></div>
        <div class="spacer"></div>
        ${costBadge()}
        ${gpuBadge()}${ffmpegBadge()}
      </div>
      <div class="work" id="work">${stageView(cur)}</div>
    </div>
  </div>
  ${queueDrawer()}`;

  const mob = window.matchMedia('(max-width:900px)').matches;
  if (mob) { const b = $('[data-act="toggle-side"]'); if (b) b.style.display = ''; }
}

function stageItem(s) {
  const locked = s.status === 'DRAFT' && s.idx > 0 &&
    (S.detail.stages[s.idx - 1].status !== 'APPROVED' && S.detail.stages[s.idx - 1].status !== 'FINAL');
  const mark = (s.status === 'APPROVED' || s.status === 'FINAL') ? '✓'
    : (s.status === 'REVIEW' ? '!' : (s.idx + 1));
  return `<div class="stage ${S.stage === s.key ? 'active' : ''} ${locked ? 'locked' : ''}"
      data-act="go-stage" data-key="${s.key}" data-status="${s.status}">
    <div class="dot">${mark}</div>
    <div class="stage-txt">
      <div class="stage-name">${esc(s.name)}</div>
      <div class="stage-desc">${esc(statusLabel(s.status))}${locked ? ' · 需先通过上一阶段' : ''}</div>
    </div>
  </div>`;
}

function statusLabel(st) {
  return { DRAFT: '未开始', GENERATING: '生成中', REVIEW: '待审核', APPROVED: '已通过',
    REJECTED: '已驳回', REGENERATING: '重新生成', FINAL: '已完成' }[st] || st;
}

function costBadge() {
  const c = S.detail.costs || {};
  return `<span class="badge" title="本地算力 + 云端费用">成本 <b>¥${(c.total_amount || 0).toFixed(2)}</b>
    · 本地 ${esc(c.local_human || '0小时0分钟')}</span>`;
}

/* ---------------------------------------------------------------- Queue */
function queueDrawer() {
  const running = S.tasks.filter((t) => t.status === 'generating').length;
  const waiting = S.tasks.filter((t) => t.status === 'waiting').length;
  return `<div class="drawer ${S.drawerOpen ? '' : 'collapsed'}" id="drawer">
    <div class="drawer-h" data-act="toggle-drawer">
      <b>任务队列</b>
      <span class="chip ${running ? 'warn' : 'grey'}">进行中 ${running}</span>
      <span class="chip grey">等待 ${waiting}</span>
      <div class="spacer" style="flex:1"></div>
      <button class="btn xs ghost" data-act="pause-queue">暂停</button>
      <button class="btn xs ghost" data-act="resume-queue">继续</button>
      <span style="color:var(--txt3)">${S.drawerOpen ? '▾' : '▴'}</span>
    </div>
    <div class="drawer-b">${S.tasks.length ? S.tasks.map(taskRow).join('') : '<div class="empty" style="padding:22px">暂无任务</div>'}</div>
  </div>`;
}

function taskRow(t) {
  const cls = { done: 'ok', failed: 'bad', generating: 'warn', waiting: 'grey', cancelled: 'grey' }[t.status] || 'grey';
  const pct = Math.round((t.progress || 0) * 100);
  return `<div class="task">
    <div>
      <div>${esc(t.title)} <span class="chip ${cls}">${esc(t.status)}</span></div>
      ${t.error ? `<div class="mono" style="color:var(--bad)">${esc(String(t.error).slice(0, 160))}</div>` : ''}
      <div class="pbar" style="margin-top:5px"><i style="width:${t.status === 'done' ? 100 : pct}%"></i></div>
    </div>
    <div class="mono" style="color:var(--txt3)">${t.status === 'done' ? '100%' : pct + '%'}</div>
    <div class="tasks-actions">
      ${t.status === 'generating' || t.status === 'waiting'
        ? `<button class="btn xs ghost" data-act="task-cancel" data-tid="${t.id}">取消</button>
           <button class="btn xs ghost" data-act="task-bump" data-tid="${t.id}">插队</button>` : ''}
      ${t.status === 'failed' ? `<button class="btn xs ghost" data-act="task-retry" data-tid="${t.id}">重试</button>` : ''}
    </div>
  </div>`;
}

/* ================================================================ STAGE VIEWS */
function stageView(s) {
  const key = s.key;
  if (key === 'script') return viewScript(s);
  if (key === 'characters') return viewCharacters(s);
  if (key === 'scenes') return viewScenes(s);
  if (key === 'storyboard') return viewStoryboard(s);
  if (key === 'video') return viewVideo(s);
  if (key === 'voice') return viewVoice(s);
  if (key === 'edit') return viewEdit(s);
  if (key === 'final') return viewFinal(s);
  return '';
}

function stageHead(s, extra = '') {
  return `<div class="head">
    <div><h1>${esc(s.name)}</h1><p>${esc(s.desc)}</p></div>
    <div class="head-actions">${extra}${stageActions(s)}</div>
  </div>`;
}

function stageActions(s) {
  const st = s.status;
  const a = [];
  if (st === 'DRAFT') a.push(`<button class="btn primary" data-act="run-stage" data-key="${s.key}">▶ 开始生成</button>`);
  if (st === 'REVIEW') {
    a.push(`<button class="btn" data-act="run-stage" data-key="${s.key}">↻ 重新生成</button>`);
    a.push(`<button class="btn ok" data-act="approve-stage" data-key="${s.key}">✓ 审核通过</button>`);
    a.push(`<button class="btn danger" data-act="reject-stage" data-key="${s.key}">✕ 驳回</button>`);
  }
  if (st === 'APPROVED' || st === 'FINAL') {
    a.push(`<button class="btn ghost" data-act="reopen-stage" data-key="${s.key}">↺ 返回修改</button>`);
  }
  if (st === 'REJECTED') a.push(`<button class="btn primary" data-act="run-stage" data-key="${s.key}">▶ 重新生成</button>`);
  return a.join('');
}

function emptyBox(text) { return `<div class="empty"><div class="big">○</div><div>${esc(text)}</div></div>`; }

/* ---- 1 剧本分析 ---- */
function viewScript(s) {
  const a = (s.payload && s.payload.stats) ? s.payload : null;
  return stageHead(s) + `
  <div class="card">
    <div class="card-h"><h3>剧本</h3><span class="sub">支持导入 / 直接输入 / 小说片段</span>
      <div class="spacer" style="flex:1"></div>
      <button class="btn sm ghost" data-act="import-file">📄 导入文件</button>
      <input type="file" id="file-in" accept=".txt,.md" style="display:none"/>
    </div>
    <textarea class="script" id="script-box" placeholder="【场景 夜】&#10;&#10;李明推开木门，冷风灌进来。&#10;&#10;掌柜：这么晚了，还买药？&#10;&#10;李明：我要一味药，三年前你欠我的。">${esc(S.script)}</textarea>
    <div class="row" style="margin-top:12px">
      <button class="btn primary" data-act="save-script">保存剧本</button>
      <button class="btn violet" data-act="run-stage" data-key="script">🧠 AI 分析剧本</button>
    </div>
  </div>
  ${a ? `
  <div class="card">
    <div class="card-h"><h3>AI 分析结果</h3>
      <span class="chip grey">引擎：${esc(a.engine === 'llm' ? 'LLM Provider' : '内置启发式')}</span></div>
    <div class="stats">
      ${stat(a.stats.characters, '主要人物')}${stat(a.stats.scenes, '场景')}
      ${stat(a.stats.props, '道具')}${stat(a.stats.shots, '镜头')}
      ${stat(fmtDur(a.stats.duration), '预计时长')}
    </div>
    <div class="hint" style="margin-top:14px"><b>一句话梗概：</b>${esc(a.logline || '—')}</div>
    <div class="grid g3" style="margin-top:14px">
      <div><div class="stages-title">人物</div>${(a.characters || []).map((c) => `<span class="chip" style="margin:3px 4px 0 0">${esc(c.name)}</span>`).join('') || '—'}</div>
      <div><div class="stages-title">场景</div>${(a.scenes || []).map((c) => `<span class="chip" style="margin:3px 4px 0 0">${esc(c.name)}</span>`).join('') || '—'}</div>
      <div><div class="stages-title">道具</div>${(a.props || []).map((c) => `<span class="chip" style="margin:3px 4px 0 0">${esc(c.name)}</span>`).join('') || '—'}</div>
    </div>
  </div>` : ''}`;
}
function stat(v, l) { return `<div class="stat"><b>${esc(v)}</b><span>${esc(l)}</span></div>`; }

/* ---- 2 角色 / 3 场景 ---- */
async function loadCands(stage, group) {
  const r = await api.get(`/api/projects/${S.pid}/candidates?stage=${stage}&group=${encodeURIComponent(group)}`);
  return r.candidates || [];
}

function viewCharacters(s) {
  const a = scriptAnalysis();
  const names = (a.characters || []).map((c) => c.name);
  if (!names.length) return stageHead(s) + emptyBox('请先在「剧本分析」中完成分析');
  return stageHead(s, `<button class="btn sm" data-act="approve-all" data-key="characters">✓ 全部通过</button>`) + `
  <div class="hint">角色一旦定稿即成为 <b>Character Bible</b>，后续所有镜头自动调用，保证跨镜头一致性。点击卡片进入抽卡。</div>
  <div class="grid g3" style="margin-top:14px" id="char-grid">${names.map((n) => charCardLoading(n)).join('')}</div>`;
}

function charCardLoading(n) {
  return `<div class="asset"><div class="asset-img" style="display:grid;place-items:center;color:var(--txt3)">载入中…</div>
    <div class="asset-body"><div class="asset-name">${esc(n)}</div></div></div>`;
}

async function hydrateCharCards(container, kind) {
  const list = (await api.get(`/api/projects/${S.pid}/entities?kind=${kind}`)).entities || [];
  const map = {}; list.forEach((e) => { map[e.name] = e; });
  const a = scriptAnalysis();
  const names = kind === 'character' ? (a.characters || []).map((c) => c.name) : (a.scenes || []).map((c) => c.name);
  const group = kind === 'character' ? 'characters' : 'scenes';
  const cards = [];
  for (const n of names) {
    const e = map[n];
    const cands = await loadCands(group, (kind === 'character' ? 'char:' : 'scene:') + n);
    const chosen = cands.find((c) => c.chosen) || cands[cands.length - 1];
    const p = (e && e.payload) || (chosen && chosen.payload) || {};
    const img = p.ref ? `<img src="${fileUrl(S.pid, p.ref)}" alt=""/>` : `<div style="display:grid;place-items:center;height:100%;color:var(--txt3)">待抽卡</div>`;
    cards.push(`<div class="asset">
      <div class="asset-img wide">${img}</div>
      <div class="asset-body">
        <div class="asset-name">${esc(n)}
          ${e && e.status === 'APPROVED' ? '<span class="chip ok">已定稿</span>' : `<span class="chip warn">候选 ${cands.length}</span>`}
        </div>
        <div class="asset-desc">${esc(kind === 'character'
          ? [p.gender, p.age ? p.age + '岁' : '', p.personality, p.clothing].filter(Boolean).join(' · ') || '尚未生成设定'
          : [p.location, p.time, p.weather].filter(Boolean).join(' · ') || '尚未生成设定')}</div>
        <div class="asset-actions">
          <button class="btn xs primary" data-act="open-gacha" data-stage="${group}" data-group="${kind === 'character' ? 'char:' : 'scene:'}${esc(n)}">🎴 抽卡</button>
          ${p.ref ? `<a class="btn xs ghost" href="${fileUrl(S.pid, p.ref)}" target="_blank">查看</a>` : ''}
        </div>
      </div></div>`);
  }
  container.innerHTML = cards.join('') || emptyBox('暂无资产');
}

function viewScenes(s) {
  const a = scriptAnalysis();
  const props = a.props || [];
  return stageHead(s, `<button class="btn sm" data-act="approve-all" data-key="scenes">✓ 全部通过</button>`) + `
  <div class="hint">场景与道具同样资产化，确保跨镜头一致。场景点击抽卡；道具随场景阶段一并定稿。</div>
  <div class="card" style="margin-top:14px">
    <div class="card-h"><h3>场景</h3><span class="sub">Scene Bible</span></div>
    <div class="grid g3" id="scene-grid">${(a.scenes || []).map((x) => charCardLoading(x.name)).join('')}</div>
  </div>
  <div class="card">
    <div class="card-h"><h3>道具</h3><span class="sub">Props Bible</span></div>
    ${props.length ? `<div class="grid g4">${props.map((p) => `<div class="asset" style="padding:12px">
        <div class="asset-name">${esc(p.name)}</div>
        <div class="asset-desc">${esc(p.desc || '关键道具')}</div></div>`).join('')}</div>`
      : emptyBox('剧本中未识别到道具')}
  </div>`;
}

function scriptAnalysis() {
  const st = (S.detail.stages || []).find((x) => x.key === 'script');
  return (st && st.payload) || {};
}

/* ---- 4 分镜 ---- */
function viewStoryboard(s) {
  if (!S.shots.length) return stageHead(s) + emptyBox('请先完成前面阶段，然后生成分镜');
  return stageHead(s, `<button class="btn sm" data-act="approve-all" data-key="storyboard">✓ 全部通过</button>`) + `
  <div class="hint">共 <b>${S.shots.length}</b> 个镜头 · 总时长 <b>${fmtDur(S.shots.reduce((a, x) => a + (x.payload.duration || 0), 0))}</b>。
    可对单镜头抽卡重绘，或只改动作 / 运镜 / 景别，其余维度锁定。</div>
  <div class="grid" style="margin-top:14px;gap:11px">${S.shots.map(shotCard).join('')}</div>`;
}

function shotCard(sh) {
  const p = sh.payload || {};
  return `<div class="shot">
    <div>
      <div class="shot-img">${p.panel ? `<img src="${fileUrl(S.pid, p.panel)}" alt=""/>` : ''}</div>
      <div class="shot-actions">
        <button class="btn xs" data-act="open-shot" data-no="${p.no}">🎴 抽卡</button>
        <button class="btn xs ghost" data-act="move-shot" data-no="${p.no}" data-dir="-1">↑</button>
        <button class="btn xs ghost" data-act="move-shot" data-no="${p.no}" data-dir="1">↓</button>
      </div>
    </div>
    <div>
      <div style="display:flex;align-items:center;gap:9px">
        <span class="shot-no">S${String(p.no).padStart(3, '0')}</span>
        <span class="chip ${sh.status === 'APPROVED' ? 'ok' : 'grey'}">${esc(statusLabel(sh.status))}</span>
        <span class="chip grey">${esc(p.duration)}s</span>
      </div>
      <div class="shot-tags">
        <span class="chip">${esc(p.shot_type)}</span>
        <span class="chip">${esc(p.camera)}</span>
        <span class="chip">${esc(p.emotion)}</span>
        ${p.character ? `<span class="chip ok">${esc(p.character)}</span>` : ''}
        ${p.scene ? `<span class="chip grey">${esc(p.scene)}</span>` : ''}
      </div>
      <div class="shot-line"><b>动作：</b>${esc(p.action || '—')}</div>
      ${p.dialogue ? `<div class="shot-line"><b>台词：</b>「${esc(p.dialogue)}」</div>` : ''}
    </div></div>`;
}

/* ---- 5 视频 ---- */
function viewVideo(s) {
  const done = S.shots.filter((x) => x.payload.video).length;
  return stageHead(s, `
    <button class="btn primary" data-act="gen-video">▶ 批量生成视频</button>
    <button class="btn sm" data-act="approve-all" data-key="video">✓ 全部通过</button>`) + `
  <div class="hint">
    视频生成走 <b>任务队列</b>，可暂停 / 继续 / 取消 / 插队（右下角队列面板）。
    当前 Provider：<b>${esc(S.meta.providers.find((p) => p.type === 'video' && !p.builtin)?.name || '内置占位视频 Provider')}</b>。
    未接通真实 H3 / 云端 Provider 时产出的是「分镜海报 + 镜头清单」，接通后即输出真实 MP4。
  </div>
  <div class="stats" style="margin-top:14px">
    ${stat(done, '已生成镜头')}${stat(S.shots.length - done, '待生成')}${stat(S.shots.length, '总镜头')}
  </div>
  <div class="grid" style="margin-top:14px;gap:11px">${S.shots.map(videoCard).join('')}</div>`;
}

function videoCard(sh) {
  const p = sh.payload || {};
  const v = p.video || {};
  const q = p.quality || {};
  const poster = v.poster || p.panel;
  return `<div class="shot">
    <div>
      <div class="shot-img">${poster ? `<img src="${fileUrl(S.pid, poster)}" alt=""/>` : ''}</div>
      <div class="shot-actions">
        <button class="btn xs primary" data-act="regen-video" data-no="${p.no}">🎴 重抽</button>
        <button class="btn xs ghost" data-act="open-video-cand" data-no="${p.no}">候选</button>
      </div>
    </div>
    <div>
      <div style="display:flex;align-items:center;gap:9px;flex-wrap:wrap">
        <span class="shot-no">S${String(p.no).padStart(3, '0')}</span>
        <span class="chip ${v.status === 'placeholder' ? 'warn' : 'ok'}">${v.status === 'placeholder' ? '占位产物' : '已渲染'}</span>
        ${q.score ? `<span class="chip ${q.score >= 85 ? 'ok' : (q.score >= 70 ? 'warn' : 'bad')}">质量 ${q.score}</span>` : ''}
      </div>
      <div class="shot-line"><b>动作：</b>${esc(p.action || '—')}</div>
      ${q.suggestions ? `<div class="shot-line" style="color:var(--txt3)">质检建议：${esc(q.suggestions.join('；'))}</div>` : ''}
      ${q.anomaly ? `<div class="shot-line" style="color:var(--bad)">⚠ ${esc(q.anomaly_type)}</div>` : ''}
    </div></div>`;
}

/* ---- 6 配音 ---- */
function viewVoice(s) {
  const voices = S.meta.voices || [];
  const a = scriptAnalysis();
  const names = (a.characters || []).map((c) => c.name);
  return stageHead(s, `<button class="btn primary" data-act="run-stage" data-key="voice">▶ 生成配音</button>`) + `
  <div class="card">
    <div class="card-h"><h3>角色音色</h3><span class="sub">每个角色固定 Voice ID，跨集复用</span></div>
    <div class="grid g3">${names.map((n) => `<div class="field">
        <label>${esc(n)}</label>
        <select class="inp" data-act="set-voice" data-char="${esc(n)}">
          ${voices.map((v) => `<option value="${v.id}">${esc(v.name)}</option>`).join('')}
        </select></div>`).join('') || '<div class="hint">请先完成角色设计</div>'}</div>
  </div>
  <div class="card">
    <div class="card-h"><h3>音频时间线</h3><span class="sub">对白 / 旁白 / 环境音 / BGM</span></div>
    <div id="audio-list">${audioList()}</div>
  </div>`;
}

function audioList() {
  const rows = S.shots.filter((x) => x.payload.dialogue);
  if (!rows.length) return '<div class="hint">尚无对白。生成配音后在此试听。</div>';
  return `<table><thead><tr><th>镜头</th><th>角色</th><th>台词</th><th style="width:210px">试听</th></tr></thead><tbody>
    ${rows.map((x) => {
      const p = x.payload;
      const rel = `audio/dialogue/S${String(p.no).padStart(3, '0')}.wav`;
      return `<tr><td>S${String(p.no).padStart(3, '0')}</td><td>${esc(p.character || '旁白')}</td>
        <td>${esc(p.dialogue)}</td>
        <td>${p.audio ? `<audio controls src="${fileUrl(S.pid, rel)}"></audio>` : '<span class="chip grey">未生成</span>'}</td></tr>`;
    }).join('')}</tbody></table>`;
}

/* ---- 7 剪辑 ---- */
function viewEdit(s) {
  const tl = s.payload || {};
  const t = S._timeline || {};
  const total = t.total || tl.total || 0;
  return stageHead(s, `<button class="btn primary" data-act="run-stage" data-key="edit">▶ 自动剪辑</button>`) + `
  <div class="hint">AI 根据剧情节奏 / 对白 / 镜头长度 / BGM / 情绪生成初版时间线，可随时返回修改。</div>
  <div class="card" style="margin-top:14px">
    <div class="card-h"><h3>时间线</h3><span class="sub">总时长 ${esc(fmtDur(total))} · ${esc(t.fps || 24)}fps</span></div>
    <div class="tl">${tlRows(t, total)}</div>
  </div>
  <div class="card">
    <div class="card-h"><h3>字幕</h3><span class="sub">SRT · 漫剧字幕样式</span></div>
    <pre class="mono" style="max-height:260px;overflow:auto;background:#0c1220;border:1px solid var(--line);border-radius:9px;padding:13px">${esc(S._subtitle || '尚未生成字幕')}</pre>
  </div>`;
}

function tlRows(t, total) {
  if (!total) return '<div class="hint">尚未生成时间线</div>';
  const pct = (v) => (v / total) * 100;
  const vid = (t.video_track || []).map((c) =>
    `<div class="tl-clip v" style="width:${pct(c.duration)}%" title="S${c.shot} ${esc(c.shot_type)}">S${c.shot}</div>`).join('');
  const voi = (t.voice_track || []).filter((c) => c.dialogue).map((c) =>
    `<div class="tl-clip a" style="width:${pct(c.duration)}%" title="${esc(c.dialogue)}">${esc(c.character || '旁白')}</div>`).join('');
  const mus = (t.music_track || []).map((c) =>
    `<div class="tl-clip m" style="width:${pct(c.duration)}%">${esc(c.name || 'BGM')}</div>`).join('');
  const sub = (t.subtitle_track || []).map((c) =>
    `<div class="tl-clip c" style="width:${pct(c.end - c.start)}%" title="${esc(c.text)}">${esc(c.text.slice(0, 8))}</div>`).join('');
  return [['VIDEO', vid], ['VOICE', voi], ['MUSIC', mus], ['SUBTITLE', sub]]
    .map(([l, c]) => `<div class="tl-row"><div class="tl-label">${l}</div><div class="tl-track">${c || ''}</div></div>`).join('');
}

/* ---- 8 成片 ---- */
function viewFinal(s) {
  const plan = s.payload && s.payload.output ? s.payload : (S._plan || null);
  const c = S.detail.costs || {};
  const m = S.meta;
  return stageHead(s, `<button class="btn primary" data-act="gen-final">📦 生成导出计划</button>`) + `
  <div class="card">
    <div class="card-h"><h3>导出参数</h3><span class="sub">容器 / 分辨率 / 画幅</span></div>
    <div class="row">
      <div class="field"><label>容器</label><select class="inp" id="ex-container">
        ${m.containers.map((x) => `<option ${x === (plan?.container || 'MP4') ? 'selected' : ''}>${x}</option>`).join('')}</select></div>
      <div class="field"><label>分辨率</label><select class="inp" id="ex-res">
        ${m.resolutions.map((x) => `<option ${x === (plan?.resolution || S.detail.project.resolution) ? 'selected' : ''}>${x}</option>`).join('')}</select></div>
      <div class="field"><label>画幅</label><select class="inp" id="ex-aspect">
        ${m.aspects.map((x) => `<option ${x === (plan?.aspect || S.detail.project.aspect) ? 'selected' : ''}>${x}</option>`).join('')}</select></div>
      <div class="field"><label>帧率</label><select class="inp" id="ex-fps">
        ${[24, 25, 30, 60].map((x) => `<option ${x === (plan?.fps || 24) ? 'selected' : ''}>${x}</option>`).join('')}</select></div>
    </div>
  </div>
  ${plan ? `<div class="card">
    <div class="card-h"><h3>导出计划</h3>
      <span class="chip ${plan.ffmpeg?.available ? 'ok' : 'warn'}">FFmpeg ${plan.ffmpeg?.available ? '就绪' : '未安装'}</span></div>
    <div class="stats">
      ${stat(plan.container, '容器')}${stat(plan.output_size, '输出尺寸')}${stat(plan.shots, '镜头数')}${stat(plan.video_files, '已渲染片段')}
    </div>
    <div class="hint" style="margin-top:13px"><b>输出：</b>${esc(plan.output)}<br/><b>说明：</b>${esc(plan.note)}</div>
    <div class="mono" style="margin-top:11px;background:#0c1220;border:1px solid var(--line);border-radius:9px;padding:12px;overflow:auto">${esc(plan.command)}</div>
  </div>` : ''}
  <div class="card">
    <div class="card-h"><h3>成本统计</h3><span class="sub">文档 §43</span></div>
    <div class="stats">
      ${stat('¥' + (c.total_amount || 0).toFixed(2), '云端费用')}
      ${stat(c.local_human || '0小时0分钟', '本地算力')}
      ${stat(c.tokens || 0, 'API Token')}
    </div>
  </div>
  <div class="card">
    <div class="card-h"><h3>项目资产</h3><span class="sub">${(S.detail.files || []).length} 个文件</span>
      <div class="spacer" style="flex:1"></div>
      <button class="btn xs ghost" data-act="refresh-files">刷新</button></div>
    <div class="filelist">${(S.detail.files || []).map((f) => `<span>${esc(f)}</span>`).join('')}</div>
  </div>`;
}

/* ================================================================ MODALS */
async function openGacha(stage, group) {
  const label = group.split(':')[1] || group;
  const draw = async (hint = '', lock = []) => {
    const r = await api.post(`/api/projects/${S.pid}/gacha/draw`, { stage, group, n: stage === 'characters' ? 3 : 2, hint, lock });
    return r.candidates || [];
  };
  let cands = await loadCands(stage, group);
  if (!cands.length) cands = await draw();

  const renderBody = () => {
    const lockFields = stage === 'characters'
      ? ['gender', 'age', 'personality', 'appearance', 'clothing', 'voice']
      : ['location', 'time', 'weather'];
    const chosen = cands.find((c) => c.chosen) || cands[cands.length - 1];
    return `<div class="lock-row" style="margin-bottom:13px">
        <span style="font-size:12px;color:var(--txt2)">锁定字段：</span>
        ${lockFields.map((f) => `<span class="chip grey lock" data-lock="${f}">${f}</span>`).join('')}
      </div>
      <div class="gacha">${cands.map((c) => candCard(c, stage, group)).join('')}</div>
      <div class="field" style="margin-top:16px">
        <label>修改要求（例如「脸成熟一点，衣服不要变」）</label>
        <textarea class="inp" id="gacha-hint" rows="2" placeholder="用自然语言描述你的修改意图…"></textarea>
      </div>
      <div class="hint">当前选中：<b>方案 ${esc(chosen?.label || '—')}</b>。采用后该角色即定稿进入 Character Bible。</div>`;
  };

  modal(`<div class="modal-h"><h2>🎴 抽卡 · ${esc(label)}</h2>
      <span class="sub">${stage === 'characters' ? '角色设计' : '场景设计'} · 候选 A/B/C/D</span>
      <button class="close" data-act="close-modal">✕</button></div>
    <div class="modal-b" id="gacha-body">${renderBody()}</div>
    <div class="modal-f">
      <button class="btn" data-act="gacha-draw" data-stage="${stage}" data-group="${esc(group)}">🎲 继续抽卡</button>
      <button class="btn violet" data-act="gacha-redraw" data-stage="${stage}" data-group="${esc(group)}">✎ 按修改要求重抽</button>
      <button class="btn ok" data-act="gacha-adopt" data-stage="${stage}" data-group="${esc(group)}" data-cid="${(cands.find((c) => c.chosen) || cands[cands.length - 1] || {}).id || ''}">✓ 采用当前方案</button>
    </div>`);

  // 绑定锁定 chip
  $$('.lock').forEach((el) => el.addEventListener('click', () => el.classList.toggle('on')));

  const refresh = async (hint = '') => {
    const lock = $$('.lock.on').map((e) => e.dataset.lock);
    cands = await draw(hint, lock);
    $('#gacha-body').innerHTML = renderBody();
    $$('.lock').forEach((el) => el.addEventListener('click', () => el.classList.toggle('on')));
  };
  window._gachaRefresh = refresh;
}

function candCard(c, stage, group) {
  const p = c.payload || {};
  const desc = stage === 'characters'
    ? [p.gender, p.age ? p.age + '岁' : '', p.personality, p.appearance, p.clothing].filter(Boolean).join(' · ')
    : [p.location, p.time, p.weather].filter(Boolean).join(' · ');
  return `<div class="cand ${c.chosen ? 'chosen' : ''} ${stage === 'scenes' ? 'wide' : ''}"
      data-act="gacha-pick" data-cid="${c.id}" data-stage="${stage}" data-group="${esc(group)}">
    <div class="cand-label">${esc(c.label)}</div>
    ${p.ref ? `<img src="${fileUrl(S.pid, p.ref)}" alt=""/>` : ''}
    <div class="cand-info"><b>方案 ${esc(c.label)}${c.chosen ? ' · 已采用' : ''}</b>${esc(desc)}</div>
  </div>`;
}

async function openShot(no) {
  const sh = S.shots.find((x) => x.payload.no === no);
  if (!sh) return;
  const p = sh.payload;
  const cands = await loadCands('storyboard', `shot:${String(no).padStart(3, '0')}`);
  modal(`<div class="modal-h"><h2>🎴 分镜抽卡 · S${String(no).padStart(3, '0')}</h2>
      <span class="sub">可只改动作 / 运镜 / 景别 / 情绪，其余维度锁定</span>
      <button class="close" data-act="close-modal">✕</button></div>
    <div class="modal-b">
      <div class="gacha">${cands.map((c) => candCard(c, 'storyboard', `shot:${String(no).padStart(3, '0')}`)).join('')}</div>
      <div class="lock-row" style="margin-top:16px">
        <span style="font-size:12px;color:var(--txt2)">锁定（保持不变）：</span>
        ${['character', 'scene', 'camera', 'style'].map((f) => `<span class="chip grey lock on" data-lock="${f}">${f}</span>`).join('')}
      </div>
      <div class="lock-row" style="margin-top:9px">
        <span style="font-size:12px;color:var(--txt2)">只改：</span>
        ${['action', 'camera', 'shot_type', 'emotion'].map((f) => `<span class="chip grey lock" data-change="${f}">${f}</span>`).join('')}
      </div>
      <div class="field" style="margin-top:14px">
        <label>修改要求</label>
        <textarea class="inp" id="shot-hint" rows="2" placeholder="例如：动作改成推门而入，情绪更紧张"></textarea>
      </div>
      <div class="hint">当前：<b>${esc(p.shot_type)}</b> · ${esc(p.camera)} · ${esc(p.emotion)} · ${esc(p.duration)}s<br/>
        动作：${esc(p.action || '—')}</div>
    </div>
    <div class="modal-f">
      <button class="btn violet" data-act="shot-redraw" data-no="${no}">🎲 重新抽卡</button>
      <button class="btn ghost" data-act="close-modal">关闭</button>
    </div>`);
  $$('.lock').forEach((el) => el.addEventListener('click', () => el.classList.toggle('on')));
}

async function openVideoCand(no) {
  const cands = await loadCands('video', `shot:${String(no).padStart(3, '0')}`);
  modal(`<div class="modal-h"><h2>视频候选 · S${String(no).padStart(3, '0')}</h2>
      <span class="sub">共 ${cands.length} 个候选</span>
      <button class="close" data-act="close-modal">✕</button></div>
    <div class="modal-b"><div class="gacha">${cands.map((c) => {
      const p = c.payload || {}, v = p.video || {}, q = p.quality || {};
      return `<div class="cand ${c.chosen ? 'chosen' : ''} wide" data-act="video-pick" data-cid="${c.id}" data-no="${no}">
        <div class="cand-label">${esc(c.label)}</div>
        ${v.poster ? `<img src="${fileUrl(S.pid, v.poster)}" alt=""/>` : ''}
        <div class="cand-info"><b>候选 ${esc(c.label)}${c.chosen ? ' · 当前' : ''}</b>
          质量 ${esc(q.score || '—')} · ${esc(p.camera || '')} · ${esc(p.duration || '')}s</div></div>`;
    }).join('')}</div></div>
    <div class="modal-f"><button class="btn ghost" data-act="close-modal">关闭</button></div>`);
}

function openSettings() {
  const g = S.meta.gpu, f = S.meta.ffmpeg;
  const provs = S.meta.providers || [];
  modal(`<div class="modal-h"><h2>⚙ 设置</h2><span class="sub">硬件 / Provider / 导出环境</span>
      <button class="close" data-act="close-modal">✕</button></div>
    <div class="modal-b">
      <div class="card">
        <div class="card-h"><h3>硬件检测</h3><span class="chip ${g.mode === 'Local' ? 'ok' : 'warn'}">${esc(g.mode)} 模式</span></div>
        <table><tbody>
          <tr><td>GPU</td><td>${esc(g.gpus[0].name)} · ${g.gpus[0].vram_gb}GB</td></tr>
          <tr><td>CUDA</td><td>${g.cuda ? '可用' : '不可用'}</td></tr>
          <tr><td>CPU</td><td>${esc(g.system.cpu || '—')} · ${g.system.cpu_cores} 核</td></tr>
          <tr><td>内存</td><td>${g.system.ram_gb} GB</td></tr>
          <tr><td>磁盘可用</td><td>${g.system.disk_free_gb} GB</td></tr>
          <tr><td>推荐配置</td><td><b>${esc(g.recommend.precision)}</b> · ${esc(g.recommend.resolution)} ·
            CPU Offload ${g.recommend.offload ? '开启' : '关闭'} · Batch ${g.recommend.batch}</td></tr>
          <tr><td>FFmpeg</td><td>${f.available ? esc(f.version) : esc(f.hint)}</td></tr>
        </tbody></table>
        ${g.tips.map((t) => `<div class="hint" style="margin-top:9px">${esc(t)}</div>`).join('')}
      </div>
      <div class="card">
        <div class="card-h"><h3>Provider</h3><span class="sub">模型无关 · 任意 OpenAI 兼容 API 接入</span>
          <div class="spacer" style="flex:1"></div>
          <button class="btn xs primary" data-act="add-provider">＋ 新增</button></div>
        <table><thead><tr><th>名称</th><th>类型</th><th>地址</th><th>状态</th><th></th></tr></thead><tbody>
          ${provs.map((p) => `<tr>
            <td>${esc(p.name)}${p.builtin ? ' <span class="chip grey">内置</span>' : ''}</td>
            <td>${esc(p.type)}</td><td class="mono">${esc(p.base_url || '—')}</td>
            <td>${p.has_key ? '<span class="chip ok">已配置 Key</span>' : '<span class="chip grey">无需 Key</span>'}</td>
            <td>${p.builtin ? '' : `<button class="btn xs danger" data-act="del-provider" data-id="${p.id}">删除</button>`}</td>
          </tr>`).join('')}
        </tbody></table>
      </div>
    </div>
    <div class="modal-f"><button class="btn ghost" data-act="close-modal">关闭</button></div>`);
}

function openNewProject() {
  const m = S.meta;
  modal(`<div class="modal-h"><h2>新建项目</h2><span class="sub">导入剧本，AI 逐阶段制作</span>
      <button class="close" data-act="close-modal">✕</button></div>
    <div class="modal-b">
      <div class="field"><label>项目名称</label><input class="inp" id="np-name" placeholder="例如：药铺里的秘密" value="药铺里的秘密"/></div>
      <div class="row">
        <div class="field"><label>风格（${m.styles.length} 种内置）</label>
          <select class="inp" id="np-style">${m.styles.map((s) => `<option value="${s.key}">${esc(s.name)}</option>`).join('')}</select></div>
        <div class="field"><label>画幅</label><select class="inp" id="np-aspect">
          ${m.aspects.map((a) => `<option ${a === '9:16' ? 'selected' : ''}>${a}</option>`).join('')}</select></div>
        <div class="field"><label>分辨率</label><select class="inp" id="np-res">
          ${m.resolutions.map((a) => `<option ${a === '1080p' ? 'selected' : ''}>${a}</option>`).join('')}</select></div>
        <div class="field"><label>模式</label><select class="inp" id="np-mode">
          <option value="novice">新手模式（推荐）</option><option value="pro">专业模式</option></select></div>
      </div>
      <div class="field"><label>剧本 / 小说片段</label>
        <textarea class="inp" id="np-script" rows="9" placeholder="【场景 夜】&#10;&#10;李明推开木门，冷风灌进来。&#10;&#10;掌柜：这么晚了，还买药？&#10;&#10;李明：我要一味药，三年前你欠我的。"></textarea></div>
      <div class="hint">也可以先留空创建，进入项目后再导入剧本。支持 txt / md 文件。</div>
    </div>
    <div class="modal-f"><button class="btn ghost" data-act="close-modal">取消</button>
      <button class="btn primary" data-act="create-project">创建并开始</button></div>`, { narrow: true });
}

/* ================================================================ ACTIONS */
const ACTIONS = {
  async 'new-project'() { openNewProject(); },
  async 'create-project'() {
    const body = {
      name: $('#np-name').value.trim() || '未命名项目',
      style: $('#np-style').value,
      aspect: $('#np-aspect').value,
      resolution: $('#np-res').value,
      mode: $('#np-mode').value,
      script: $('#np-script').value,
    };
    const r = await api.post('/api/projects', body);
    closeModal();
    await loadProjects();
    S.pid = r.project.id; S.stage = 'script';
    await loadDetail();
    if (body.script.trim()) {
      toast('项目已创建，正在分析剧本…');
      await api.post(`/api/projects/${S.pid}/stage/script/run`, { script: body.script });
      await loadDetail();
    } else {
      toast('项目已创建', 'ok');
    }
    render();
  },
  async 'open-project'(el) {
    S.pid = el.dataset.pid; S.stage = 'script';
    await loadDetail(); render(); poll();
  },
  async 'del-project'(el) {
    if (!confirm('确认删除该项目及全部本地资产？')) return;
    await api.del(`/api/projects/${el.dataset.pid}`);
    await loadProjects(); render(); toast('已删除', 'ok');
  },
  async 'back-home'() { S.pid = null; S.detail = null; await loadProjects(); render(); },
  'toggle-side'() { $('#side').classList.toggle('open'); },

  async 'go-stage'(el) {
    if (el.classList.contains('locked')) return toast('需先通过上一阶段', 'warn');
    S.stage = el.dataset.key;
    await refreshStage();
  },
  async 'run-stage'(el) {
    const key = el.dataset.key;
    if (key === 'script') await ACTIONS['save-script']();
    toast('正在生成…');
    try {
      const r = await api.post(`/api/projects/${S.pid}/stage/${key}/run`, {});
      if (r.ok === false) toast(r.error || '生成失败', 'bad');
      else toast('生成完成', 'ok');
    } catch (e) { toast('失败：' + e.message, 'bad', 5000); }
    await loadDetail(); await refreshStage();
  },
  async 'approve-stage'(el) {
    const r = await api.post(`/api/projects/${S.pid}/stage/${el.dataset.key}/approve`);
    if (r.ok === false) toast(r.error || '无法通过', 'warn');
    else toast('已通过，进入下一阶段', 'ok');
    await loadDetail(); await refreshStage();
  },
  async 'reject-stage'(el) {
    const reason = prompt('驳回原因（可选）') || '';
    await api.post(`/api/projects/${S.pid}/stage/${el.dataset.key}/reject`, { reason });
    await loadDetail(); await refreshStage(); toast('已驳回', 'warn');
  },
  async 'reopen-stage'(el) {
    await api.post(`/api/projects/${S.pid}/stage/${el.dataset.key}/reopen`);
    await loadDetail(); await refreshStage(); toast('已返回修改状态');
  },
  async 'approve-all'(el) {
    await api.post(`/api/projects/${S.pid}/stage/${el.dataset.key}/approve_all`);
    await loadDetail(); await refreshStage(); toast('已全部通过', 'ok');
  },
  async 'save-script'() {
    const box = $('#script-box');
    if (!box) return;
    S.script = box.value;
    await api.post(`/api/projects/${S.pid}/script`, { script: S.script });
  },
  async 'import-file'() {
    const inp = $('#file-in');
    inp.onchange = async () => {
      const f = inp.files[0]; if (!f) return;
      const text = await f.text();
      $('#script-box').value = text; S.script = text;
      await api.post(`/api/projects/${S.pid}/script`, { script: text });
      toast('剧本已导入', 'ok');
    };
    inp.click();
  },

  // ---- 抽卡 ----
  async 'open-gacha'(el) { await openGacha(el.dataset.stage, el.dataset.group); },
  async 'gacha-draw'(el) { await window._gachaRefresh(''); toast('已补充新候选', 'ok'); },
  async 'gacha-redraw'(el) {
    const hint = ($('#gacha-hint') || {}).value || '';
    await window._gachaRefresh(hint); toast('已按修改要求重抽', 'ok');
  },
  async 'gacha-pick'(el) {
    const r = await api.post(`/api/projects/${S.pid}/gacha/adopt`,
      { stage: el.dataset.stage, group: el.dataset.group, candidate_id: el.dataset.cid });
    if (r.ok === false) return toast(r.error, 'bad');
    await openGacha(el.dataset.stage, el.dataset.group);
    await loadDetail();
    toast(`已采用方案 ${r.design?.name ? '' : ''}`, 'ok');
  },
  async 'gacha-adopt'(el) {
    if (!el.dataset.cid) return toast('暂无候选', 'warn');
    const r = await api.post(`/api/projects/${S.pid}/gacha/adopt`,
      { stage: el.dataset.stage, group: el.dataset.group, candidate_id: el.dataset.cid });
    if (r.ok === false) return toast(r.error, 'bad');
    closeModal(); await loadDetail(); await refreshStage();
    toast('已采用该方案并定稿', 'ok');
  },

  // ---- 分镜 ----
  async 'open-shot'(el) { await openShot(Number(el.dataset.no)); },
  async 'shot-redraw'(el) {
    const no = Number(el.dataset.no);
    const lock = $$('.lock.on[data-lock]').map((x) => x.dataset.lock);
    const change = $$('.lock.on[data-change]').map((x) => x.dataset.change);
    const hint = ($('#shot-hint') || {}).value || '';
    await api.post(`/api/projects/${S.pid}/shots/${no}/redraw`, { hint, lock, change });
    toast('已生成新候选', 'ok');
    await openShot(no);
    await loadDetail(); await refreshStage();
  },
  async 'move-shot'(el) {
    const no = Number(el.dataset.no), dir = Number(el.dataset.dir);
    const order = S.shots.map((x) => x.payload.no);
    const i = order.indexOf(no), j = i + dir;
    if (j < 0 || j >= order.length) return;
    [order[i], order[j]] = [order[j], order[i]];
    await api.post(`/api/projects/${S.pid}/shots/reorder`, { order });
    await refreshStage();
  },

  // ---- 视频 ----
  async 'gen-video'() {
    const r = await api.post(`/api/projects/${S.pid}/video/generate`, {});
    toast('已加入任务队列（' + (r.task_id || '') + '）', 'ok');
    S.drawerOpen = true; poll();
  },
  async 'regen-video'(el) {
    const no = Number(el.dataset.no);
    const r = await api.post(`/api/projects/${S.pid}/video/regenerate`,
      { no, lock: ['character', 'scene', 'camera', 'style'], change: ['action'] });
    toast(`S${String(no).padStart(3, '0')} 已加入队列（局部重生成）`, 'ok');
    S.drawerOpen = true; poll();
  },
  async 'open-video-cand'(el) { await openVideoCand(Number(el.dataset.no)); },
  async 'video-pick'(el) {
    await api.post(`/api/projects/${S.pid}/shots/${el.dataset.no}/adopt`,
      { candidate_id: el.dataset.cid, kind: 'video' });
    closeModal(); await loadDetail(); await refreshStage(); toast('已采用该候选', 'ok');
  },

  // ---- 音色 ----
  async 'set-voice'(el) {
    const kind = 'character';
    const list = (await api.get(`/api/projects/${S.pid}/entities?kind=${kind}`)).entities || [];
    const e = list.find((x) => x.name === el.dataset.char);
    if (!e) return toast('请先生成角色设计', 'warn');
    await api.patch(`/api/projects/${S.pid}/entities/${e.id}`, { patch: { voice: el.value } });
    toast(`${el.dataset.char} 音色已设为 ${el.value}`, 'ok');
  },

  // ---- 导出 ----
  async 'gen-final'() {
    const body = {
      container: $('#ex-container').value, resolution: $('#ex-res').value,
      aspect: $('#ex-aspect').value, fps: Number($('#ex-fps').value),
    };
    const r = await api.post(`/api/projects/${S.pid}/export`, body);
    S._plan = r.plan;
    await api.post(`/api/projects/${S.pid}/stage/final/run`, body);
    await loadDetail(); await refreshStage();
    toast('导出计划已生成', 'ok');
  },
  async 'refresh-files'() { await loadDetail(); await refreshStage(); },

  // ---- 队列 ----
  'toggle-drawer'() { S.drawerOpen = !S.drawerOpen; const d = $('#drawer'); if (d) d.classList.toggle('collapsed'); },
  async 'pause-queue'() { await api.post('/api/queue/pause'); toast('队列已暂停', 'warn'); },
  async 'resume-queue'() { await api.post('/api/queue/resume'); toast('队列已继续', 'ok'); },
  async 'task-cancel'(el) { await api.post(`/api/tasks/${el.dataset.tid}/cancel`); poll(); },
  async 'task-retry'(el) { await api.post(`/api/tasks/${el.dataset.tid}/retry`); poll(); },
  async 'task-bump'(el) { await api.post(`/api/tasks/${el.dataset.tid}/bump`, { priority: 0 }); poll(); },

  // ---- 设置 ----
  'open-settings'() { openSettings(); },
  async 'add-provider'() {
    modal(`<div class="modal-h"><h2>新增 Provider</h2><span class="sub">支持任意 OpenAI 兼容 API</span>
        <button class="close" data-act="close-modal">✕</button></div>
      <div class="modal-b">
        <div class="row">
          <div class="field"><label>名称</label><input class="inp" id="pv-name" placeholder="DeepSeek / GPT / 本地 vLLM"/></div>
          <div class="field"><label>类型</label><select class="inp" id="pv-type">
            <option value="llm">LLM（剧本/导演推理）</option>
            <option value="image">Image（角色/场景出图）</option>
            <option value="video">Video（H3 / 云端视频）</option>
            <option value="tts">TTS（语音合成）</option></select></div>
        </div>
        <div class="field"><label>Base URL</label><input class="inp" id="pv-url" placeholder="https://api.deepseek.com/v1"/></div>
        <div class="field"><label>API Key</label><input class="inp" id="pv-key" type="password" placeholder="sk-..."/></div>
        <div class="field"><label>模型（逗号分隔）</label><input class="inp" id="pv-models" placeholder="deepseek-chat"/></div>
        <div class="hint">Key 仅保存在本机 SQLite，不上传任何服务器。LLM 接入后，剧本分析将由该模型完成。</div>
      </div>
      <div class="modal-f"><button class="btn ghost" data-act="close-modal">取消</button>
        <button class="btn primary" data-act="save-provider">保存</button></div>`, { narrow: true });
  },
  async 'save-provider'() {
    await api.post('/api/providers', {
      name: $('#pv-name').value.trim() || '新 Provider',
      type: $('#pv-type').value, base_url: $('#pv-url').value.trim(),
      api_key: $('#pv-key').value.trim(),
      models: $('#pv-models').value.split(',').map((x) => x.trim()).filter(Boolean),
    });
    S.meta = await api.get('/api/meta');
    closeModal(); openSettings(); toast('Provider 已保存', 'ok');
  },
  async 'del-provider'(el) {
    await api.del(`/api/providers/${el.dataset.id}`);
    S.meta = await api.get('/api/meta'); openSettings(); toast('已删除', 'ok');
  },

  // ---- 环境部署 ----
  async 'open-runtime'() {
    S.view = 'runtime';
    render();
    await loadRuntime();
  },
  async 'refresh-runtime'() { await loadRuntime(); toast('已刷新', 'ok'); },
  async 'runtime-install'() {
    const plan = S.runtimePlan;
    if (!confirm(`即将下载约 ${plan ? plan.total_download_human : '未知'} 的运行时与模型权重。\n\n` +
      `目标目录：${S.runtime?.runtime_dir || ''}\n` +
      `预计耗时：约 ${plan ? plan.estimated_minutes : '?'} 分钟（取决于网速）\n\n` +
      `过程中可随时取消，已下载部分会保留，下次可续传。\n确认开始？`)) return;
    const r = await api.post('/api/runtime/install', {
      mirror: S.runtimePlan?.mirror || 'cn',
      model: S.runtimePlan?.model || null,
      nodes: true,
    });
    if (r.ok === false) return toast(r.error, 'bad');
    toast('部署已开始，可离开此页面，后台会继续', 'ok');
    S.drawerOpen = false;
    pollRuntime();
  },
  async 'runtime-cancel'() {
    await api.post('/api/runtime/cancel');
    toast('已发送取消指令', 'warn');
    setTimeout(loadRuntime, 800);
  },
  async 'runtime-retry'() {
    const r = await api.post('/api/runtime/retry');
    if (r.ok === false) return toast(r.error, 'bad');
    toast('已重新开始', 'ok');
    pollRuntime();
  },
  async 'plan-change'() {
    const mirror = ($('#rt-mirror') || {}).value || 'cn';
    const model = ($('#rt-model') || {}).value || '';
    const r = await api.get(`/api/runtime/plan?mirror=${mirror}&model=${encodeURIComponent(model)}`);
    S.runtimePlan = r.plan;
    S.runtimeModels = Object.entries(r.models).map(([k, v]) => ({ key: k, ...v }));
    render();
  },
  async 'h3-check'() {
    const r = await api.get('/api/runtime/h3');
    S.h3 = r;
    toast(r.ok ? 'H3 环境就绪' : (r.detail || 'H3 未就绪'), r.ok ? 'ok' : 'warn', 5000);
    render();
  },
  async 'h3-detect-nodes'() {
    const r = await api.post('/api/runtime/h3/detect-nodes', {});
    if (r.ok === false) return toast(r.error, 'bad');
    toast('已写入节点映射', 'ok');
    S.h3 = await api.get('/api/runtime/h3');
    render();
  },
  async 'comfy-start'() {
    const r = await api.post('/api/runtime/comfy/start', {});
    if (r.ok === false) return toast(r.error, 'bad');
    toast(r.message, 'ok');
    setTimeout(async () => { S.h3 = await api.get('/api/runtime/h3'); render(); }, 20000);
  },
  async 'offline-import'() {
    const el = $('#rt-offline-src');
    const src = (el && el.value || '').trim();
    if (!src) return toast('请先填写离线包路径', 'warn');
    if (!confirm(`将从以下目录复制运行时（不联网）：\n${src}\n\n` +
      `目标：${S.runtime?.runtime_dir || ''}\n` +
      `约 30 GB，耗时取决于硬盘速度。确认开始？`)) return;
    const r = await api.post('/api/runtime/import', { source: src });
    if (r.ok === false) return toast(r.error, 'bad', 8000);
    toast('开始导入，可离开此页面', 'ok');
    pollRuntime();
  },
  async 'offline-verify'() {
    const el = $('#rt-offline-src');
    const src = (el && el.value || '').trim();
    if (!src) return toast('请先填写离线包路径', 'warn');
    const r = await api.post('/api/runtime/import/verify', { source: src });
    if (r.ok === false) return toast(r.error, 'bad', 8000);
    toast(`校验通过：${r.found.join(' / ')} · ${r.size_gb} GB`, 'ok', 6000);
  },
  async 'offline-export'() {
    const el = $('#rt-offline-dest');
    const dest = (el && el.value || '').trim();
    if (!dest) return toast('请先填写导出目录', 'warn');
    toast('正在导出，大文件复制请耐心等待…', 'warn', 6000);
    const r = await api.post('/api/runtime/export', { dest });
    if (r.ok === false) return toast(r.error, 'bad', 8000);
    toast(`导出完成：${r.path}（${r.size_gb} GB）`, 'ok', 8000);
    await loadRuntime();
  },

  'close-modal'() { closeModal(); },
  'mask-close'(el, ev) { if (ev.target === el) closeModal(); },
};

/* ---------------------------------------------------------------- helpers */
async function refreshStage() {
  await loadDetail();
  if (S.stage === 'edit') {
    const t = await api.get(`/api/projects/${S.pid}/timeline`);
    S._timeline = t.timeline || {}; S._subtitle = t.subtitle || '';
  }
  renderWorkspace();
  if (S.stage === 'characters') {
    const g = $('#char-grid'); if (g) await hydrateCharCards(g, 'character');
  }
  if (S.stage === 'scenes') {
    const g = $('#scene-grid'); if (g) await hydrateCharCards(g, 'scene');
  }
}

/* ---------------------------------------------------------------- runtime loaders */
async function loadRuntime() {
  try {
    const [status, planRes] = await Promise.all([
      api.get('/api/runtime/status'),
      api.get('/api/runtime/plan?mirror=cn'),
    ]);
    S.runtime = status;
    if (!S.runtimePlan) S.runtimePlan = planRes.plan;
    S.runtimeModels = Object.entries(planRes.models).map(([k, v]) => ({ key: k, ...v }));
    if (S.view === 'runtime') render();
    if (status.running) pollRuntime();
  } catch (e) {
    toast('读取部署状态失败：' + e.message, 'bad');
  }
}

let _rtTimer = null;
function pollRuntime() {
  if (_rtTimer) return;
  _rtTimer = setInterval(async () => {
    try {
      const st = await api.get('/api/runtime/status');
      S.runtime = st;
      if (S.view === 'runtime') render();
      if (!st.running && st.status !== 'running') {
        clearInterval(_rtTimer); _rtTimer = null;
        if (st.status === 'done') toast('本地推理环境部署完成，可以开始出片了', 'ok', 6000);
        if (st.status === 'failed') toast('部署失败：' + (st.error || ''), 'bad', 9000);
      }
    } catch (e) { /* ignore */ }
  }, 2000);
}

let _pollTimer = null;
async function poll() {
  if (_pollTimer) return;
  _pollTimer = setInterval(async () => {
    if (!S.pid) return;
    try {
      const r = await api.get(`/api/tasks?project_id=${S.pid}`);
      S.tasks = r.tasks || [];
      const d = $('#drawer');
      if (d) {
        d.outerHTML = queueDrawer();
      }
      const busy = S.tasks.some((t) => t.status === 'generating');
      if (busy && (S.stage === 'video')) {
        S.shots = (await api.get(`/api/projects/${S.pid}/shots`)).shots || [];
      }
    } catch (e) { /* ignore */ }
  }, 1500);
}

/* ---------------------------------------------------------------- events */
document.addEventListener('click', async (ev) => {
  const el = ev.target.closest('[data-act]');
  if (!el) return;
  // 下拉框交给 change 事件处理：点击时原生下拉不该被 preventDefault 打断，
  // 而且点击瞬间读到的还是旧值。
  if (el.tagName === 'SELECT') return;
  if (el.closest('[data-stop]') && el.dataset.act === 'mask-close') return;
  const fn = ACTIONS[el.dataset.act];
  if (!fn) return;
  ev.preventDefault();
  ev.stopPropagation();
  try { await fn(el, ev); }
  catch (e) { toast('操作失败：' + e.message, 'bad', 5000); }
}, true);

document.addEventListener('change', async (ev) => {
  const el = ev.target.closest && ev.target.closest('select[data-act]');
  if (!el) return;
  const fn = ACTIONS[el.dataset.act];
  if (!fn) return;
  try { await fn(el, ev); }
  catch (e) { toast('操作失败：' + e.message, 'bad', 5000); }
}, true);

document.addEventListener('input', (ev) => {
  if (ev.target.id === 'script-box') S.script = ev.target.value;
});

boot();
