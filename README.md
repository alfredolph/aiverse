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

## 一、安装与运行

### 方式 A：下载 exe（推荐）

到 [Releases](../../releases) 下载 `AIVerse.exe`，**双击即用**，无需安装 Python。

- 用户数据（`projects/`）保存在 exe 同级目录，可随 U 盘带走
- 若放在 `Program Files` 等只读位置，会自动改用 `%LOCALAPPDATA%\AIVerse\projects`

### 方式 B：安装包（含开始菜单 / 卸载）

下载 `AIVerse-Setup-1.0.0.exe` 运行安装向导。默认装到
`%LOCALAPPDATA%\Programs\AI Studio`，**无需管理员权限**；卸载时不会删除你的项目数据。

### 方式 C：源码运行

```bash
git clone <repo>
cd aiverse
python run.py                 # 默认 http://127.0.0.1:8770，自动打开浏览器
python run.py 9000            # 指定端口
python run.py --no-open       # 不自动打开浏览器
python run.py --host 0.0.0.0  # 开放局域网（手机控制）
```

运行时**零第三方依赖**，只需 Python 3.10+ 标准库。

启动后：

| 入口 | 地址 |
|---|---|
| 桌面控制台 | `http://127.0.0.1:8770` |
| 手机控制 | `http://<本机IP>:8770`（局域网，默认不开放公网） |

首次启动会自动生成演示项目「药铺里的秘密」（2 角色 / 2 场景 / 4 道具 / 8 镜头 / 4 条对白），点开即可体验全流程。

---

## 二、自己构建 exe

```bash
pip install pyinstaller
python build_exe.py
# -> dist/AIVerse.exe  (约 9.4 MB，单文件)
```

`build_exe.py` 会自动：生成图标 → 清理旧构建 → PyInstaller 打包 → 校验产物。

想要**带安装向导的 setup.exe**，再装一个 [Inno Setup](https://jrsoftware.org/isdl.php)：

```bash
iscc installer\aiverse.iss
# -> installer/Output/AIVerse-Setup-1.0.0.exe
```

### 自动构建

仓库已配置 GitHub Actions（`.github/workflows/build.yml`）：
推一个 `v*` 标签就会自动在 Windows runner 上打包、跑健康检查、并把 exe 挂到 Release。

```bash
git tag v1.0.0 && git push origin v1.0.0
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
│   ├── agents/                ★ Agent 层：Script/Director/Character/Scene/Storyboard/Video/Voice/Editor/Quality（§45）
│   ├── workflow/engine.py     ★ 工作流引擎 + 审核门（§5.1、§37、§48）
│   ├── queue/task_queue.py    ★ 任务队列：暂停/继续/取消/重试/插队（§23、§24）
│   ├── gpu/detector.py        GPU / VRAM / CUDA / RAM / 磁盘检测与推荐（§19-22）
│   ├── media/ffmpeg.py        FFmpeg 适配 + 导出计划（§29、§30）
│   └── services/pipeline.py   阶段编排
├── frontend/                  原生 SPA（无构建步骤）
│   ├── index.html
│   ├── styles.css             深色电影感主题
│   └── app.js
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
| §34-36 | 本地服务、ComfyUI 作为底层执行引擎 | ✅ 接口就绪 |
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
- **算力默认使用内置离线 Provider**，因此在没有 GPU、没有 API Key、没有 FFmpeg 的机器上也能跑通全流程：
  - 图片 → 生成真实 SVG 参考图（角色立绘 / 场景概念图 / 分镜画面）
  - 音频 → 用标准库 `wave` 合成真实 WAV（音高随角色 Voice ID 变化）
  - 视频 → 产出「分镜海报 + 镜头清单」，界面明确标注为**占位产物**
  - 导出 → 产出完整的 FFmpeg 命令、concat 清单与导出计划

**接入真实模型只需实现同样的 Provider 接口**，上层剧本/角色/场景/分镜/审核/抽卡/配音/字幕/剪辑/项目全部不需要改动（对应文档 §58 的「模型无关」原则）：

| 想要 | 怎么做 |
|---|---|
| 真实 LLM 分析剧本 | 设置 → 新增 Provider → 类型 LLM → 填 Base URL / API Key / 模型（DeepSeek、GPT、Claude 代理、本地 vLLM 均可） |
| 真实出图 | 启动本地 ComfyUI，补全 `providers/media.py` 的 `ComfyUIImageProvider.generate()` |
| 真实视频（H3） | 启动 ComfyUI 并加载 H3 Ref2V 工作流，补全 `H3ComfyUIProvider.generate()` |
| 真实配音 | 接入 MiniMax / Edge TTS，补全 `CloudTTSProvider.speak()` |
| 真实出片 | 安装 FFmpeg 并加入 PATH，界面「FFmpeg 未安装」会自动变为「就绪」，导出即出真实 MP4 |

所有 Provider 失败时都会**自动回退**到内置占位实现，不会中断流程。

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

---

## 七、开发路线对照（文档 §56）

Phase 0 项目骨架 ✅ · Phase 1 GPU/Model/Provider ✅ · Phase 2 Workflow Engine ✅ ·
Phase 3 Project/Asset/Database ✅ · Phase 4 Script Agent ✅ · Phase 5 Character/Scene Agent ✅ ·
Phase 6 Storyboard Agent ✅ · Phase 7 H3 Adapter ✅（接口就绪，待接本地 ComfyUI）·
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

## License

[MIT](LICENSE)
