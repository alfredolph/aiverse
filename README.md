<div align="center">

<img src="assets/logo.png" width="96" alt="AIVerse"/>

# AI Studio · AI 漫剧工厂

**AIVerse —— AI 原生内容生产操作系统**

第一阶段杀手级应用：**AI 漫剧一键生产**

依据《AI 漫剧一键生产客户端 · 产品需求 + 技术架构 + 开发规范 v1.0》实现

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D4?logo=windows&logoColor=white)
![Dependencies](https://img.shields.io/badge/第三方依赖-0-brightgreen)
![License](https://img.shields.io/badge/License-MIT-blue)

</div>

---

> **AI 负责生产，人负责决策。**
>
> 不是「一键生成然后祈祷」，而是：
> 剧本 → AI 理解 → 审核 → 角色 → 审核 → 场景 → 审核 → 分镜 → 审核 → 视频 → 审核 → 配音 → 审核 → 剪辑 → 审核 → 成片。
> 每一阶段都能 **抽卡 / 局部重生成 / 返回上一阶段**。

---

## 零、先把体积说清楚（最重要的一节）

打开安装包你会看到它只有 **约 10 MB**。这不是缺东西，而是分工：

| 组成 | 大小 | 装在哪 |
|---|---|---|
| **编排大脑**（本项目） | **约 10 MB** | 安装包里，双击即用 |
| 剧本/角色/场景/分镜 Agent、审核门、抽卡、局部重生成、时间线、字幕、剪辑导出 | 同上 | 同上 |
| **一键部署器**（自动装下面这一堆） | 同上 | 同上 |
| Python 隔离环境 + PyTorch + CUDA | 约 2.5 GB | 首次部署时自动装 |
| ComfyUI 执行引擎 | 约 2.4 GB | 首次部署时自动装 |
| **MiniMax H3 权重（33B 参数，量化版）** | **26.4 GB** | 首次部署时自动下 |

**H3 是一个 33B 参数的全模态视频模型，量化权重 26.4 GB（BF16 版 50+ GB）。**
没有任何办法把它压进一个 10 MB 的 exe —— 这不是取舍问题，是物理问题。
ComfyUI Desktop、Pinokio、EZlaunch 等所有同类桌面应用，走的都是「小安装包 + 首次运行下载」这条路。

所以我们把「让用户自己去装」变成「点一下全自动装」，并且额外提供**离线包**：

| 你的情况 | 该怎么做 |
|---|---|
| 有网、有 N 卡 | 安装 → 点「⚡ 一键部署」→ 等 20~60 分钟 → 开始出片。全程只点一次 |
| 没网 / 网慢 / 要给多台机器装 | 在任意一台机器上部署好 → 点「📦 导出离线包」→ 拷 U 盘 → 其他机器「📥 导入离线包」，**零下载** |
| 完全不想碰本地算力 | 装好后不部署，直接在「设置」里接云端 Provider（OpenAI 兼容 / 官方 H3 API） |

硬件门槛（H3 官方数据）：**8 GB 显存能跑**（显存/内存交换，慢但不崩）、12 GB 舒适、24 GB 随便跑。
原生输出 768p；2K 需要走官方 API。中文口播偏弱，建议用本项目内置的 TTS 走后期配音。

---

## 一、安装与运行

### 方式 A：下载 exe（推荐）

到 [Releases](../../releases) 下载 `AIVerse.exe`，**双击即用**，无需安装 Python。

- 用户数据（`projects/`）保存在 exe 同级目录，可随 U 盘带走
- 若放在 `Program Files` 等只读位置，会自动改用 `%LOCALAPPDATA%\AIVerse\projects`
- 本地推理运行时统一放在 `%LOCALAPPDATA%\AIVerse\runtime`

### 方式 B：安装包（含开始菜单 / 卸载）

下载 `AIVerse-Setup-1.0.1.exe` 运行安装向导。默认装到
`%LOCALAPPDATA%\Programs\AI Studio`，**无需管理员权限**；卸载时不会删除你的项目数据
**也不会删除已下载的 30 GB 运行时**（重装后可直接复用）。

安装向导会勾选创建两个快捷方式：

- `AI Studio` —— 正常打开
- `一键部署本地推理环境` —— 等价于 `AIVerse.exe --setup`，直接落到「环境部署」页

### 方式 C：源码运行

```bash
git clone <repo>
cd aiverse
python run.py                 # 默认 http://127.0.0.1:8770，自动打开浏览器
python run.py 9000            # 指定端口
python run.py --no-open       # 不自动打开浏览器
python run.py --setup         # 直接进入「环境部署」页
python run.py --host 0.0.0.0  # 开放局域网（手机控制）
```

运行时**零第三方依赖**，只需 Python 3.10+ 标准库。

启动后：

| 入口 | 地址 |
|---|---|
| 桌面控制台 | `http://127.0.0.1:8770` |
| 手机控制 | `http://<本机IP>:8770`（局域网，默认不开放公网） |

首次启动会**自动生成示例项目「示例 · 药铺里的秘密」并跑满全部 8 个阶段**（约 2 秒，用的是内置离线 Provider）。
点开就能看到一条完整产线长什么样：剧本分析 → 角色 → 场景 → 分镜 → 视频 → 配音 → 剪辑 → 成片，
每一阶段的产物、审核状态、抽卡候选都在。想自己动手时，删掉它新建项目即可。

> 只会项目数为 0 时播种一次，之后不再打扰你。

---

## 一·五、一键部署本地 H3 推理环境

左侧栏「⚡ 环境部署」，或首页顶部横幅，或 `--setup` 启动，都能进这一页。

它会先读你的显卡，再生成一份**只属于你这台机器**的部署计划：

```
硬件检测 → uv 运行时管理器 → Python 3.12 隔离环境 → 创建 venv
        → PyTorch + CUDA → ComfyUI → ComfyUI 依赖 → H3 加速节点
        → 下载 H3 权重 → FFmpeg → 写工作流 + 注册 Provider
```

要点：

- **镜像可选**：国内（ModelScope / 清华源 / 上海交大 torch 源）或海外（HuggingFace）。国内线路下 26.4 GB 大约快 3~10 倍
- **断点续传**：HTTP Range 续传 + 多镜像自动回退；关掉程序再打开，已下载的部分不重来
- **续传必须校验**：`.part` 旁边会留一份 `.part.meta` 记录「来源 URL + 远端总大小」。
  对不上就丢弃重下，字节数不足就**不改名**、保留断点。
  这一段是刻意做重的：26 GB 的模型如果拼进了坏数据，会在解压或加载时才报错，
  用户已经白等几个小时。宁可多下一次，也不让用户拿到坏安装。
- **幂等**：已装好的步骤自动跳过；失败可单步重试
- **可取消**：随时中止，已下载文件保留
- **不污染系统**：所有东西都进 `runtime/`，不动注册表、不改 PATH、不装全局 Python 包
- **自动识别节点**：连上 ComfyUI 后读 `/object_info`，自动把 H3 节点类名映射进工作流；识别结果持久化，重启仍生效
- **没 N 卡也能用**：自动降级为「只装 FFmpeg」，生成走云端 Provider，导出照常出片

---

## 二、自己构建 exe


```bash
pip install pyinstaller
python build_exe.py
# -> dist/AIVerse.exe  (约 10 MB，单文件)
```

`build_exe.py` 会自动：生成图标 → 清理旧构建 → PyInstaller 打包 → 校验产物。

想要**带安装向导的 setup.exe**，再装一个 [Inno Setup](https://jrsoftware.org/isdl.php)：

```bash
iscc installer\aiverse.iss
# -> installer/Output/AIVerse-Setup-1.0.1.exe
```

安装包会额外做两件事：

1. 在 `{app}\aiverse.ini` 写入安装标记 —— 客户端读到它就把「项目数据 + 运行时」放到
   `%LOCALAPPDATA%\AIVerse`（重装/升级不丢 30 GB 模型）；绿色版没有这个文件，
   全部放在 exe 同级，可随 U 盘带走。
2. 创建「一键部署本地推理环境」快捷方式（`AIVerse.exe --setup`，直接落到环境部署页），
   并在安装完成时把体积构成讲清楚。

### 自动构建

仓库已配置 GitHub Actions（`.github/workflows/build.yml`）：
推一个 `v*` 标签就会自动在 Windows runner 上打包、跑健康检查、并把 exe 挂到 Release。

```bash
git tag v1.0.1 && git push origin v1.0.1
```

---

## 三、目录结构

```
aiverse/
├── run.py                     一键启动器（文档 §35）
├── build_exe.py               一键打包脚本
├── aiverse.spec               PyInstaller 配置
├── requirements.txt           运行时零依赖（打包时才需 pyinstaller）
├── assets/
│   ├── aiverse.ico            多尺寸应用图标
│   ├── logo.png
│   └── version_info.txt       Windows 文件属性
├── tools/
│   ├── make_icon.py           纯标准库图标生成器
│   └── gh_login.py            GitHub 设备码登录助手
├── installer/aiverse.iss      Inno Setup 安装包脚本
├── .github/workflows/build.yml 自动打包 CI
├── backend/
│   ├── app.py                 HTTP 服务 + 全部 API（文档 §39）
│   ├── core/                  配置 / SQLite / 文件系统 / 资产 / 抽卡 / 分镜 / 成本
│   ├── providers/             ★ 模型无关层（§8、§42）
│   │   ├── media.py           占位图/音、ComfyUI 出图、★ MiniMax H3 视频 Adapter
│   │   └── h3_workflows.py    ★ H3 工作流构建 + 节点自动识别
│   ├── runtime/               ★ 一键部署器
│   │   ├── catalog.py         组件清单 / 镜像源 / 模型仓库 / 显存分档
│   │   ├── planner.py         按显卡生成部署计划（步骤/体积/耗时/警告）
│   │   ├── downloader.py      断点续传 + 多镜像回退 + 模型仓库拉取
│   │   └── installer.py       后台执行 / 状态持久化 / 离线包导入导出
│   ├── agents/                ★ Agent 层：Script/Director/Character/Scene/Storyboard/Video/Voice/Editor/Quality（§45）
│   ├── workflow/engine.py     ★ 工作流引擎 + 审核门（§5.1、§37、§48）
│   ├── queue/task_queue.py    ★ 任务队列：暂停/继续/取消/重试/插队（§23、§24）
│   ├── gpu/detector.py        GPU / VRAM / CUDA / RAM / 磁盘检测与推荐（§19-22）
│   ├── media/ffmpeg.py        FFmpeg 适配 + 真实导出（§29、§30）
│   ├── services/pipeline.py   阶段编排
│   └── services/seed.py       首次运行自动播种示例项目（8 阶段跑满）
├── frontend/                  原生 SPA（无构建步骤）
│   ├── index.html
│   ├── styles.css             深色电影感主题
│   └── app.js                 含「⚡ 环境部署」页
└── projects/                  用户数据（首次运行自动生成，不入库）
```

---

## 四、已实现能力对照

| 文档章节 | 能力 | 状态 |
|---|---|---|
| §3 | 8 阶段管线 + 逐阶段审核 | ✅ |
| §4 | 新手 / 专业两种模式 | ✅ |
| §5.1 §37 | Workflow Engine + WorkflowAdapter 统一接口 | ✅ |
| §8 §42 | Provider 抽象（LLM/Image/Video/TTS），可自由新增 OpenAI 兼容 API | ✅ |
| §9 | WorkBuddy 作为普通 Provider 接入（不写死） | ✅ 架构就绪 |
| §10 | AI 导演：识别人物/地点/情节/情绪/对白/动作/道具/镜头 | ✅ |
| §11-13 | Character / Scene / Props Bible，资产化 | ✅ |
| §14 §48 | 审核机制与状态机，强制审核门 | ✅ |
| §15 §49 | 抽卡系统：候选 A/B/C/D、继续抽卡、修改要求重抽 | ✅ |
| §16 | 局部重生成：锁定人物/场景/运镜/风格，只改动作 | ✅ |
| §17 | 分镜系统 + 拖拽调序 | ✅ |
| §18 | 时间线（VIDEO / VOICE / MUSIC / SUBTITLE 多轨） | ✅ |
| §19 §21 §22 | GPU 检测与显存分级推荐、多卡提示 | ✅ |
| §20 | Local / Cloud / Hybrid 模式 | ✅ |
| §23 §24 | 任务队列：暂停/继续/取消/重试/插队/优先级 | ✅ |
| §25 | 视频质量检查，AI 不替用户决策 | ✅ |
| §26 | 16 种内置风格（Style Profile，非硬编码 Prompt） | ✅ |
| §27 §28 | 角色固定 Voice ID、TTS、SRT 字幕 | ✅ |
| §29 §30 | 自动剪辑、导出计划（MP4/H264/H265/AV1，480p–4K，4 种画幅） | ✅ |
| §31 | 批量生产计划（角色/场景跨集复用） | ✅ |
| §32 §33 | SQLite + 文件系统，大文件不入库 | ✅ |
| §34-36 | 本地服务、ComfyUI 作为底层执行引擎 | ✅ 已接通 |
| §36 §37 | MiniMax H3 Adapter：提交工作流 / 轮询 / 取回 MP4 | ✅ 真实实现 |
| §35 | 一键部署本地推理运行时（含离线包） | ✅ 新增 |
| §38 | AI Workflow Generator（让 AI 自己设计工作流） | ✅ 接口就绪 |
| §39 | REST API | ✅ 40+ 端点 |
| §40 §41 | 手机远程控制、局域网优先、默认关闭公网 | ✅ |
| §43 §44 | 成本统计 + 推荐策略 | ✅ |
| §45 §46 | 多 Agent 协作 + Project Memory 上下文管理 | ✅ |
| §47 | 版本控制（资产版本快照） | ✅ |

---

## 五、关于「生成」的说明（重要）

本项目严格区分 **架构** 与 **算力**：

- **架构全部真实可用**：管线、审核门、抽卡、队列、Provider 抽象、成本统计、时间线、字幕、导出计划、文件落盘，全部是真代码、真数据、真产物。
- **算力分三层**，按你的机器自动选择：
  1. **本地 H3（推荐）** —— 走「一键部署」装好 ComfyUI + MiniMax H3，`H3ComfyUIProvider` 会真的提交工作流、轮询 `/history`、从 `/view` 拉回生成的 MP4（H3 同时产出音频轨）
  2. **云端 Provider** —— 在「设置」里新增任意 OpenAI 兼容 API
  3. **内置离线占位 Provider** —— 没 GPU、没 Key、没 FFmpeg 也能跑通全流程：
     - 图片 → 生成真实 SVG 参考图（角色立绘 / 场景概念图 / 分镜画面）
     - 音频 → 用标准库 `wave` 合成真实 WAV（音高随角色 Voice ID 变化）
     - 视频 → 产出「分镜海报 + 镜头清单」，界面明确标注为**占位产物**
     - 导出 → 产出完整的 FFmpeg 命令、concat 清单与导出计划

**接入真实模型只需实现同样的 Provider 接口**，上层剧本/角色/场景/分镜/审核/抽卡/配音/字幕/剪辑/项目全部不需要改动（对应文档 §58 的「模型无关」原则）：

| 想要 | 怎么做 |
|---|---|
| 真实 LLM 分析剧本 | 设置 → 新增 Provider → 类型 LLM → 填 Base URL / API Key / 模型（DeepSeek、GPT、Claude 代理、本地 vLLM 均可） |
| 真实出图 | 启动本地 ComfyUI（一键部署已含），`ComfyUIImageProvider` 已实现提交/轮询/取回 |
| 真实视频（H3） | 一键部署 → 点「启动 ComfyUI」→ 点「🩺 检测 H3 环境」→ 自动识别节点并接管 |
| 真实配音 | 接入 MiniMax / Edge TTS，补全 `CloudTTSProvider.speak()` |
| 真实出片 | 一键部署已含 FFmpeg；界面「FFmpeg 未安装」会自动变为「就绪」，导出即出真实 MP4 |

所有 Provider 失败时都会**自动回退**到内置占位实现，不会中断流程。

---

## 五·五、和常见「一键启动器」的区别

市面上的一键启动器（EZlaunch、Pinokio 之类）本质是「帮你把 ComfyUI 装好，然后你自己去玩工作流」。
本项目走的是相反的方向：**把 ComfyUI 藏起来，只留下创作流程**。

| | 常见一键启动器 | AI Studio · AI 漫剧工厂 |
|---|---|---|
| 定位 | 环境启动器 | **内容生产操作系统** |
| 你要做的事 | 装环境 → 找工作流 → 自己拼节点 → 自己管素材 | 粘一段剧本 → 逐阶段点「通过」 |
| 剧本 → 分镜 | 不管，自己写 Prompt | AI 导演自动拆人物/场景/道具/情绪/对白/动作/镜头 |
| 角色一致性 | 靠你自己写 Prompt 或搭 IPAdapter | Character Bible + 固定 Voice ID + 资产版本快照 |
| 审核 | 没有 | **8 阶段强制审核门**（DRAFT→REVIEW→APPROVED→FINAL），AI 不替你做决策 |
| 抽卡 | 重跑一遍 | 候选 A/B/C/D 并存，可「按修改要求重抽」 |
| 改一处 | 整段重来 | **局部重生成**：锁定人物/场景/运镜/风格，只改动作 |
| 配音/字幕 | 另外找工具 | 角色固定音色 + SRT 字幕 + 多轨时间线 |
| 出片 | 自己拉去剪辑软件 | 自动剪辑 + 导出计划（MP4/H264/H265/AV1，480p–4K，4 种画幅） |
| 任务管理 | 无 | 队列：暂停/继续/取消/重试/**插队**/优先级 |
| 手机 | 无 | 局域网手机控制（默认不开放公网） |
| 模型锁定 | 绑死 ComfyUI | Provider + Adapter 抽象，换模型上层零改动 |
| 成本 | 无感 | 成本统计 + 推荐策略 |
| 没 GPU | 装不动 | 自动降级占位 Provider，流程照样跑通、产物照样能看 |
| 离线装机 | 只能联网 | **导出/导入离线包，零下载** |

一句话：**别人给你一套工具，这里给你一条产线。**


---

## 六、主要 API

```
GET    /api/meta                                  应用元信息 / 风格库 / GPU / Provider
GET    /api/projects                              项目列表
POST   /api/projects                              新建项目
GET    /api/projects/{id}                         项目详情（阶段/进度/成本/文件树）
GET    /api/projects/{id}/script                  剧本 + 分析结果
POST   /api/projects/{id}/stage/{key}/run         执行阶段
POST   /api/projects/{id}/stage/{key}/approve     审核通过（受审核门约束）
POST   /api/projects/{id}/stage/{key}/reject      驳回
POST   /api/projects/{id}/stage/{key}/reopen      返回修改
GET    /api/projects/{id}/candidates              抽卡候选
POST   /api/projects/{id}/gacha/draw              继续抽卡 / 按修改要求重抽
POST   /api/projects/{id}/gacha/adopt             采用某候选
GET    /api/projects/{id}/shots                   分镜列表
POST   /api/projects/{id}/shots/{no}/redraw       单镜头抽卡 / 局部重生成
POST   /api/projects/{id}/video/generate          批量生成视频（入队）
POST   /api/projects/{id}/video/regenerate        单镜头局部重生成（入队）
GET    /api/projects/{id}/quality                 全片质量体检
GET    /api/projects/{id}/timeline                时间线 + 字幕
POST   /api/projects/{id}/export                  生成导出计划
GET    /api/tasks                                 任务队列
POST   /api/tasks/{id}/cancel|retry|bump          取消 / 重试 / 插队
GET    /api/providers  POST /api/providers        Provider 管理
```

### 本地推理运行时（一键部署）

```
GET    /api/runtime/status                        部署状态 / 各组件是否就绪 / 已占磁盘
GET    /api/runtime/plan?mirror=&model=&nodes=    按显卡生成部署计划（步骤/体积/耗时/警告）
POST   /api/runtime/install                       开始一键部署（后台线程，可离开页面）
POST   /api/runtime/cancel                        取消部署（已下载文件保留）
POST   /api/runtime/retry                         重试失败的步骤
GET    /api/runtime/h3                            H3 健康检查（ComfyUI 是否在跑 / H3 节点是否就绪）
POST   /api/runtime/h3/detect-nodes               连 ComfyUI 自动识别 H3 节点类名并持久化
POST   /api/runtime/comfy/start | /stop           启动 / 停止本地 ComfyUI
POST   /api/runtime/import/verify                 只读校验：某目录是否是完整离线包
POST   /api/runtime/import                        从离线包导入运行时（零下载）
POST   /api/runtime/export                        把本机运行时导出成可拷贝的离线包
```

---

## 七、开发路线对照（文档 §56）

Phase 0 项目骨架 ✅ · Phase 1 GPU/Model/Provider ✅ · Phase 2 Workflow Engine ✅ ·
Phase 3 Project/Asset/Database ✅ · Phase 4 Script Agent ✅ · Phase 5 Character/Scene Agent ✅ ·
Phase 6 Storyboard Agent ✅ · Phase 7 H3 Adapter ✅（已接通本地 ComfyUI，含一键部署）·
Phase 8 Review/Regenerate ✅ · Phase 9 TTS/Subtitle ✅ · Phase 10 Timeline/FFmpeg ✅ ·
Phase 11 AI Workflow Generator ✅（接口）· Phase 12 多 LLM ✅ ·
Phase 13 Cloud Provider ✅（接口）· Phase 14 Mobile Remote ✅（局域网）· Phase 15 批量生产 ✅（计划）·
Phase 16 Marketplace / 商业化 ⏳（预留）

---

## 八、十大产品原则落地情况（文档 §53）

| 原则 | 落地 |
|---|---|
| 1 不让用户学习 AI 工具 | 首页只有「新建项目 → 导入剧本 → 开始」 |
| 2 不让用户学习 ComfyUI | ComfyUI 仅作为底层执行引擎，界面完全不暴露节点 |
| 3 不把 H3 当成唯一模型 | Provider + Adapter 抽象，H3 只是其中一个实现 |
| 4 AI 负责生产，人负责审核 | 每阶段强制 REVIEW 状态，Quality Agent 明确 `auto_decision: false` |
| 5 任何阶段都可以抽卡 | 角色/场景/分镜/视频全部支持候选池 |
| 6 任何阶段都可以返回 | 「返回修改」按钮 + `reopen` 接口 |
| 7 角色、场景、声音必须资产化 | Character/Scene/Props Bible + 固定 Voice ID |
| 8 本地 GPU 和云端自由切换 | Local / Cloud / Hybrid 模式 + Provider 切换 |
| 9 工作流必须可以由 AI 生成 | Director Agent `plan()` 接口 |
| 10 随模型发展升级而非过时 | 新增模型只需加一个 Adapter，上层全部复用 |

---

## 九、更新日志

### v1.0.1 —— 把「一键部署」的地基修牢

只动了一键部署链路，界面和功能没变。但这一版**建议一定要升**：

- **修**：`Downloader` 会把损坏文件当成功。测试里预置 1 MB 垃圾 `.part`，
  下载器报「100% 完成」，直到解压才 `BadZipFile` 崩掉。
  放在 26.4 GB 的 H3 权重上，就是用户白等几小时才收到一句报错。
  现在三道防线：`.part.meta` 记录来源与总大小 / 无记录的断点主动丢弃 /
  字节数对不上不改名。`unzip()` 坏包抛 `CorruptArchive`，安装器清缓存重下一次。
- **修**：`github.com:443` 单独不可达时，组件下载没有退路。现在每个组件配多个候选镜像
  （ghproxy / gh-proxy / 直连）依次回退。
- **修**：H3 节点识别漏掉「中间插词」的类名（`MiniMaxH3EmptyLatentVideo`）。
  新增关键词加权兜底，识别失败不再依赖精确类名。
- **修**：本机对连不上的本地端口会静默丢包，端口探测每次白等 1~2 秒，
  叠加前端 2 秒轮询后，示例项目要跑 105 秒。现在探测超时压到 0.2 秒 + TTL 缓存，
  **105 秒 → 2 秒**。
- **加**：`tools/test_h3_mock.py`（假 ComfyUI 端到端跑通生成链路）、
  `tools/test_downloader.py`（真实下载 + 续传逐字节比对 + 解压 + 执行 + 取消）。
  两个都进了 CI，以后这类问题不用靠运气发现。

### v1.0.0 —— 首个可安装版本

零依赖后端 + 原生 SPA、8 阶段管线与强制审核门、Provider 抽象层、
一键部署本地 MiniMax H3 运行时、离线包分发、单文件 exe + Inno Setup 安装包。

---

## License

[MIT](LICENSE)
