/* 前端「环境部署」页冒烟测试：用最小 DOM 桩把 app.js 跑起来，
   验证 renderRuntime() 真的渲染出预期内容，且不抛异常。
   用法：node tools/ui_smoke.js [baseUrl]                                */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const BASE = process.argv[2] || 'http://127.0.0.1:8799';
const APP = path.join(__dirname, '..', 'frontend', 'app.js');

function makeEl(tag = 'div') {
  const el = {
    tagName: String(tag).toUpperCase(),
    _html: '', style: {}, dataset: {}, value: '', children: [],
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    appendChild() {}, remove() {}, focus() {}, blur() {},
    setAttribute() {}, getAttribute() { return null; },
    addEventListener() {}, removeEventListener() {},
    closest() { return null; },
    querySelector() { return makeEl(); },
    querySelectorAll() { return []; },
  };
  Object.defineProperty(el, 'innerHTML', {
    get() { return el._html; },
    set(v) { el._html = String(v); },
  });
  Object.defineProperty(el, 'textContent', {
    get() { return el._html; },
    set(v) { el._html = String(v); },
  });
  return el;
}

const root = makeEl('div');
globalThis.document = {
  querySelector: () => root,
  querySelectorAll: () => [],
  createElement: (t) => makeEl(t),
  addEventListener: () => {},
  body: makeEl('body'),
};
globalThis.location = { search: '?view=runtime' };
globalThis.window = {
  matchMedia: () => ({ matches: false }),
  location: globalThis.location,
};
globalThis.confirm = () => false;
globalThis.alert = () => {};
const realFetch = globalThis.fetch;
globalThis.fetch = (p, o) => realFetch(BASE + p, o);

const src = fs.readFileSync(APP, 'utf8') +
  '\n;globalThis.__probe = { S, renderRuntime, render, ACTIONS };';

const ctx = vm.createContext(globalThis);
vm.runInContext(src, ctx, { filename: 'app.js' });

const fail = [];
const need = (cond, msg) => { if (!cond) fail.push(msg); };

setTimeout(() => {
  const { S, renderRuntime } = globalThis.__probe || {};
  if (!S) { console.error('✗ 未能捕获前端状态'); process.exit(1); }

  need(S.view === 'runtime', 'boot 未根据 ?view=runtime 切到环境部署页');
  need(!!S.runtime, '未加载 /api/runtime/status');
  need(!!S.runtimePlan, '未加载 /api/runtime/plan');
  need(Array.isArray(S.runtimeModels) && S.runtimeModels.length > 0, '未加载模型清单');

  const html = renderRuntime();
  const checks = [
    ['一键部署本地 H3 生产环境', '缺少标题'],
    ['硬件检测', '缺少硬件检测卡'],
    ['当前安装状态', '缺少安装状态卡'],
    ['部署计划', '缺少部署计划卡'],
    ['离线包（完全不用下载）', '缺少离线包卡'],
    ['导入离线运行时', '缺少离线导入按钮'],
    ['导出离线包', '缺少离线导出按钮'],
    ['开始一键部署', '缺少开始部署按钮'],
    ['检测 H3 环境', '缺少 H3 检测按钮'],
    ['26.4', '缺少 H3 体积说明'],
    ['pbar', '缺少进度条'],
  ];
  for (const [needle, msg] of checks) need(html.includes(needle), `${msg}：未找到「${needle}」`);

  need(html.length > 4000, `渲染结果过短（${html.length} 字符），可能渲染中断`);
  need(!html.includes('undefined</b>') && !html.includes('>undefined<'), '渲染结果里有 undefined');

  // 首页横幅（deployBanner）也要能渲染
  const { render } = globalThis.__probe;
  S.view = 'home';
  render();
  const home = root._html || '';
  need(home.includes('环境部署') || home.includes('一键部署'), '首页缺少部署横幅/入口');
  need(!home.includes('>undefined<'), '首页渲染出现 undefined');

  if (fail.length) {
    console.error('✗ 前端冒烟测试失败：');
    for (const f of fail) console.error('   · ' + f);
    process.exit(1);
  }
  console.log('✓ 前端「环境部署」页渲染通过');
  console.log(`  状态：${S.runtime.status} · 档位：${S.runtimePlan.tier.tier}` +
              ` · 需下载：${S.runtimePlan.total_download_human}` +
              ` · 步骤：${S.runtimePlan.steps.length}` +
              ` · 模型选项：${S.runtimeModels.map((m) => m.key).join(',')}`);
  console.log(`  HTML 长度：${html.length}`);
  process.exit(0);
}, 2500);
