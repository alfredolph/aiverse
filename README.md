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
| Python 隔离环境 + PyTorch + CUDA | 约 1 GB | 首次部署时自动装 |
| ComfyUI 执行引擎 + 运行依赖 | 约 1.3 GB | 首次部署时自动装 |
| FFmpeg（导出用） | 约 92 MB | 首次部署时自动装 |
| **MiniMax H3 权重（33B 参数）** | **39.1 / 60.5 / 92.7 GB 三档** | 首次部署时自动下 |

**H3 是一个 33B 参数的全模态视频模型，ComfyUI 官方单文件版最小的档位就是 39.1 GB
（全能版 60.5 GB，全精度 BF16 版 92.7 GB）。** 这些数字是对着 HuggingFace 上
`Comfy-Org/MiniMax-H3` 的真实文件字节数加出来的，不是估的。
没有任何办法把它压进一个 10 MB 的 exe —— 这不是取舍问题，是物理问题。
ComfyUI Desktop、Pinokio、EZlaunch 等所有同类桌面应用，走的都是「小安装包 + 首次运行下载」这条路。

所以我们把「让用户自己去装」变成「点一下全自动装」，并且额外提供**离线包**：

| 你的情况 | 该怎么做 |
|---|---|
| 有网、有 N 卡 | 安装 → 点「⚡ 一键部署」→ 选档位 → 等 1~3 小时 → 开始出片。全程只点一次 |
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

下载 `AIVerse-Setup-1.0.4.exe` 运行安装向导。默认装到
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
        → PyTorch + CUDA → ComfyUI 源码包 → ComfyUI 依赖
        → H3 加速节点（KJNodes，可选）→ 下载 H3 权重 → FFmpeg → 写工作流 + 注册 Provider
```

每一步都是真动作，没有占位进度条：

| 步骤 | 实际执行的东西 |
|---|---|
| uv / FFmpeg / ComfyUI / KJNodes | 从 GitHub 下 zip（国内走 ghproxy 镜像）→ 校验字节数 → 解压到 `runtime/` 下对应位置 |
| Python / venv / 依赖 | `uv python install 3.12`、`uv venv`、`uv pip install -r requirements.txt` |
| PyTorch | `uv pip install torch torchvision torchaudio --index-url <镜像>` |
| H3 权重 | 调 `modelscope.snapshot_download` / `huggingface_hub.snapshot_download`，**按文件白名单**下载 |

**权重下载是"按文件"的，不是整仓库。** 这一点是踩过坑才改的：早先代码里有个 `subdir`
参数收下了却从没用过，用户选「精简版 39 GB」实际会把整个原始仓库（354 GB）拖下来 ——
进度条一路走，用户以为一切正常。现在每一步都带明确的文件清单，下完还会核对体积，
不够 90% 就直接报错并保留断点。

权重来源是 **`Comfy-Org/MiniMax-H3`**（ComfyUI 官方为它重新打包的单文件版，
HF 与 ModelScope 同名同结构），目录结构与 ComfyUI 的 `models/` 一一对应，
所以直接下进 `runtime/comfyui/models/`，ComfyUI 立刻就能认：

| 档位 | 内容 | 下载量 | 建议显存 |
|---|---|---|---|
| **H3 精简版** | FL2VA 主模型 + Qwen3-VL 文本编码器 + 视频/音频 VAE + 4 步 Turbo LoRA | **39.1 GB** | 8 GB 起 |
| **H3 全能版** | 再加一套 Ref2VA 主模型（参考生视频，最多 9 图 / 3 视频 / 3 音频） | **60.5 GB** | 12 GB 起 |
| **H3 全精度版** | 主模型与文本编码器都是 BF16 原精度 | **92.7 GB** | 24 GB 起 |

其他要点：

- **镜像可选**：国内（ModelScope / 清华源 / 上海交大 torch 源）或海外（HuggingFace）。国内线路下 39 GB 大约快 3~10 倍
- **断点续传**：HTTP Range 续传 + 多镜像自动回退；关掉程序再打开，已下载的部分不重来
- **续传必须校验**：`.part` 旁边会留一份 `.part.meta` 记录「来源 URL + 远端总大小」。
  对不上就丢弃重下，字节数不足就**不改名**、保留断点。
  这一段是刻意做重的：39 GB 的模型如果拼进了坏数据，会在解压或加载时才报错，
  用户已经白等几个小时。宁可多下一次，也不让用户拿到坏安装。
- **幂等**：已装好的步骤自动跳过（依赖类步骤以「完工标记文件」为准，不靠猜包名）；失败可单步重试
- **可取消**：随时中止，已下载文件保留
- **不污染系统**：所有东西都进 `runtime/`，不动注册表、不改 PATH、不装全局 Python 包
- **自动识别节点与权重**：连上 ComfyUI 后读 `/object_info` 自动映射节点类名，扫 `models/` 自动认出
  用的是哪个精度版本的权重；提交任务前还会拿 `/object_info` 把工作流校验一遍
- **没 N 卡也能用**：自动降级为「只装 FFmpeg」，生成走云端 Provider，导出照常出片

### 这一版是「对着源头逐条核过」的

v1.0.4 之后，下面这些不再凭印象，全部对得上原始出处：

| 项目 | 核对方式 |
|---|---|
| 12 个权重文件名 | HuggingFace API 列出 `Comfy-Org/MiniMax-H3` 的全部文件，逐个比对 |
| 39.1 / 60.5 / 92.7 GB | 用 API 返回的**真实字节数**相加，不是估的 |
| 「原始仓库 354 GB」 | `MiniMaxAI/MiniMax-H3` 的 `usedStorage` = 354,023,395,693 字节 |
| 节点类名与输入名 | ComfyUI 源码 `comfy_extras/nodes_minimax_h3.py` 的 `io.Schema` |
| 工作流拓扑 | 官方模板 `Comfy-Org/workflow_templates` 的 `video_minimax_h3_i2v.json` |
| 帧数栅格 | 该节点 `length` 的 `min=5 / max=3600 / step=17`，模板里的换算式也是 `17k+5` |

**两个核心节点不能混用**（这是 v1.0.4 修掉的一处静默错误）：

| 用途 | 节点类 | 参考/首帧输入 |
|---|---|---|
| 首尾帧驱动（FL2VA） | `MiniMaxH3ImageToVideo` | `first_frame` / `last_frame` |
| 参考图驱动（Ref2VA） | `MiniMaxH3ReferenceToVideo` | `ref_image_0` … `ref_image_9`（Autogrow） |

早先两个都走 `MiniMaxH3ImageToVideo`，参考图塞进一个**不存在**的 `reference_images`，
被校验逻辑默默删掉 —— 片子照样出来，只是参考图完全没生效。现在：
参考驱动走它自己的节点，并且**只要有任何「语义输入」被删掉就直接报错**，不再静默降级。

另外，Turbo LoRA 是「几步版」就配几步：官方仓库里 fl2v 有 4step 与 8step 两个文件，
文件名里写着步数，程序按文件名自动配（不带 LoRA 则 20 步）。

> **为什么不用 comfy-cli**：它的 `install` 实际只认 `--skip-manager`，
> `--nvidia` / `--yes` / `install --workspace` 这几种写法在官方文档里都不存在
> （`--workspace` 还是全局参数，得写在子命令前面），`comfy node install <github-url>`
> 也无效 —— 它要的是 Comfy Registry ID。与其赌一个没验证过的命令，不如直接下源码 zip
> 再装 `requirements.txt`，每一步都能自己核对。这也是 v1.0.4 改掉的东西。

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
# -> installer/Output/AIVerse-Setup-1.0.4.exe
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

流水线分两个 job：

- `verify` —— 语法检查 + H3 生成链路（假 ComfyUI，全本地）+ 下载器完整性
  + 部署器本体（`--skip-ffmpeg`，只下 17 MB）+ 剪辑导出（真渲染 + ffprobe 校验）。
  后三个走公网镜像或要装 ffmpeg，标了 `continue-on-error`：红了要去看日志，但不阻断出包
- `build` —— 打包 exe → 启动做 API/前端冒烟 → 编译安装包 →
  **安装 / 卸载回归**（静默装 → 校验 `aiverse.ini` → 静默卸 → 确认安装目录无残留）
  → 上传产物 → 挂 Release

```bash
git tag v1.0.2 && git push origin v1.0.2
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

## 八·五、哪些已经验过、哪些还没

这一节故意写得直白。判断标准只有一条：**是不是真跑过一遍、看的是产物而不是代码。**

### 真跑过、看过产物的

| 环节 | 怎么验的 |
|---|---|
| 单文件 exe / 安装包 | 从 Release 下载 → 校验 PE 架构 → 静默安装 → 校验 `aiverse.ini` → 启动确认 `version` 与 `runtime_dir` → 静默卸载，确认安装目录零残留、用户数据保留 |
| 8 阶段管线 + 审核门 | 首次启动自动播种示例项目，8/8 阶段跑满并逐阶段审核通过（约 2 秒） |
| 角色 / 场景 / 道具资产化 | `entities?kind=character` 返回真实实体、带状态与版本号（v1.0.3 修的就是这条） |
| 导出成片 | `tools/test_export.py` 用 ffmpeg 合成片段 → 真渲染 → ffprobe 校验分辨率 / 时长 / 音视频轨 / 编码；另外让 Release 里的 exe 自己导出过一个 408 KB、1080x1920、h264 的 MP4，抽帧肉眼确认中文字幕烧录正确 |
| H3 生成链路 | `tools/test_h3_mock.py` 起一个假 ComfyUI，端到端跑通「提交 → 轮询 → 取回 MP4」；假 ComfyUI 的节点定义与输入名照 `comfy_extras/nodes_minimax_h3.py` 写 |
| 一键部署 | `tools/test_deploy_slice.py` 从真实计划里挑最小的一步，真下载 → 解压 → 落盘 → exe 真执行 → 写 `state.json` → 再跑一遍确认幂等跳过；`--with-comfyui` 再多下 ComfyUI 源码包与 KJNodes，核对落点 |
| 下载器 | `tools/test_downloader.py` 真下载 + 逐字节比对续传 + 垃圾缓存丢弃 + 取消 |
| 59 个 API | `tools/test_api_surface.py` 逐个真调，5xx 一律算失败，外加 5 组行为断言 |
| 权重清单与体积 | 用 HuggingFace API 列出 `Comfy-Org/MiniMax-H3` 的全部文件与真实字节数，12 个文件名、三个档位合计逐个对上 |
| 节点类名 / 输入名 / 帧数规则 | 对着 ComfyUI 源码 `comfy_extras/nodes_minimax_h3.py` 与官方模板 `video_minimax_h3_i2v.json` 逐条核对（拓扑、输入名、`length` 的 `17k+5` 步长、默认采样器 `res_multistep` 与调度器 `simple`） |

### 还没验过的（说清楚，免得你踩）

- **产物观感**：SVG 参考图、内置 TTS 的合成音，只验证了「文件生成了、尺寸对了、
  ffmpeg 能读」，没有做过主观质量评估。无 N 卡时这些都是占位产物，**不能当成品看**。
- **novice / pro 两档模式**：开关是通的，但两档之间「默认行为差在哪」还没有对照测试。
- **H3 在真机上出片**：开发机没有 N 卡，也没装 ComfyUI。节点清单、输入名、权重名、
  帧数栅格、图拓扑都是**对着官方源码与仓库核对**的，端到端链路是在**假 ComfyUI** 上跑通的；
  但「一张 4090 上从点部署到出一段带音频的 MP4」这条完整路径，**没有真机验证过**。
  第一次用请拿 2 秒的短片试水，别一上来就 5 秒 768p。
- **模型下载的真实吞吐**：39 GB 那步只验证了「按文件白名单调用、体积核对逻辑正确」，
  没有真下完过 39 GB（开发机 Python 出网被限制，这条在 CI 上跑）。
- **成本数据**：接口能返回，但走本地 H3 时成本恒为 0；云端 Provider 的成本要接上真实
  API 才有意义。
- **并发**：队列默认 2 个 worker，多项目同时跑的排队行为没有压测过。
- **Phase 16 Marketplace / 商业化**：文档里标的就是「预留」，没做。

> 这些不是「大概能用」，是**还没验**。要拿来出片，请先在你自己机器上跑一遍示例项目，
> 再用自己的剧本走一次全流程。

---

## 九、更新日志

### v1.0.4 —— 「环境部署」那一步到底装了什么东西，现在能对得上了

起因是一个很直白的问题：「点击环境部署有真实功能吗」。
于是把每一步拉出来逐个核对（对着官方仓库与文档，不是凭印象），发现三处对不上：

- **修（最要命）**：模型下载的 `subdir` 参数收下了却**从来没被用过**。
  用户选「量化版 26.4 GB」，实际执行的是 `snapshot_download(repo, allow_patterns=None)`
  —— 把整个仓库拖下来。而这个仓库是 `MiniMaxAI/MiniMax-H3`（原始版，**354 GB**）。
  进度条一路走，用户以为一切按计划进行，等几小时才发现不对。
  现在改成**按文件白名单**下载，下完核对体积（不足 90% 直接报错并保留断点）。
- **修**：模型仓库选错了。ComfyUI 需要的是 `Comfy-Org/MiniMax-H3`
  （官方为 ComfyUI 重新打包的单文件版，目录结构与 `models/` 一一对应），
  不是原始仓库 —— 原始仓库分 `FL2VA/` `Ref2VA/` 两套目录树，也没有 ComfyUI 要的单文件格式。
  下载目标同步改到 `comfyui/models/`，下完 ComfyUI 立刻能认。
- **修**：体积数字是编的。「量化版 26.4 GB」在真实仓库里不存在（没有 `quantized/` 目录），
  而且光 Qwen3-VL-32B 文本编码器就 14.6 GB，主模型再省也省不掉它。
  现在三个档位都是照实测字节数算的：**精简版 39.1 GB / 全能版 60.5 GB / 全精度版 92.7 GB**。
- **修**：ComfyUI 的安装命令是错的。原来用 comfy-cli：
  `comfy install --skip-manager --nvidia --workspace <path> --yes`，
  而官方文档里 `install` 只认 `--skip-manager`，`--nvidia`/`--yes`/`install --workspace`
  都不存在（`--workspace` 是全局参数，得写在子命令前面）；加速节点那步的
  `comfy node install <github-url>` 也无效，它要的是 Comfy Registry ID。
  改成**直接下 ComfyUI 源码 zip + 装 `requirements.txt`**，KJNodes 同理，
  每一步都能自己核对，不再赌第三方 CLI 的参数。
- **修**：H3 工作流的节点类名是猜的。原来写的是 `MiniMaxH3Loader` /
  `MiniMaxH3Sampler` / `EmptyMiniMaxH3LatentVideo` —— 这些节点**根本不存在**。
  真实情况是：ComfyUI ≥ 0.30.0 **原生支持** H3，用的是内置节点
  （`UNETLoader` / `CLIPLoader` / `VAELoader` / `MiniMaxH3ImageToVideo` /
  `SamplerCustomAdvanced` / `VAEDecodeAudio` / `CreateVideo` / `SaveVideo` …）。
  现在整张图照官方模板 `video_minimax_h3_i2v.json` 重建（节点、输入名、默认值逐条对上），并且：
  - 帧数按 H3 的硬约束落在 `17k+5` 栅格（24fps 下 5 秒 = 124 帧）
  - 提交前拿 `/object_info` **校验一遍**：多余的输入删掉、缺的必需输入直接报出人话
  - 「H3 是否就绪」不再被名字里带 h3 的干扰节点（如 `MiniMaxH3SageAttentionPatch`）骗过去
- **修**：参考生视频走错了节点。H3 有**两个**核心节点，早先两个用途都用了
  `MiniMaxH3ImageToVideo`，参考图塞进一个不存在的 `reference_images` 里 ——
  校验时被默默删掉，片子照样出来，只是**参考图完全没生效**。
  现在 Ref2VA 走它自己的 `MiniMaxH3ReferenceToVideo`，参考图接在 `ref_image_0…9`
  （官方 Autogrow 命名）上；并且 `reconcile_graph()` 多了一条硬规则：
  **只要被删掉的输入属于「语义输入」（参考图 / 首尾帧 / 权重名 / VAE / 尺寸…），
  就直接判失败并报错**，不再给用户一个「看着成功了」的假结果。
- **修**：Turbo LoRA 与步数没对上。官方仓库里 fl2v 有 4step 和 8step 两个 LoRA，
  早先不管用哪个都跑 8 步。现在按文件名里的步数自动配（4step 配 4 步，不带 LoRA 配 20 步），
  并把实际步数、实际 LoRA 名记进 manifest，便于复盘。
- **修（CI 上才暴露出来的）**：KJNodes 那一步的组件名对不上 —— 部署计划里的步骤 key 是
  `comfy-nodes`，而下载地址表和落点表里写的是 `kj-nodes`。于是**有 N 卡的机器上**
  「一键部署」跑到第 8 步会直接 `未配置下载地址：comfy-nodes` 整条失败。
  （无 N 卡的机器不会装 KJNodes，所以本机一直没复现出来。）现在 key 统一成 `comfy-nodes`
  并留了别名，同时加了一条**不需要联网**的自检：计划里每个下载类步骤都必须能查到下载地址。
- **改**：可选步骤失败不再拖垮整条部署。KJNodes 只是加速节点，没它 H3 照样出片，
  所以失败时状态标 `failed` + 日志写明「跳过继续」+ 部署页顶部给出提示，
  而不是让用户对着一个 failed 的部署发呆。
- **加**：`tools/test_deploy_slice.py --with-comfyui` —— 真下 ComfyUI 源码包与 KJNodes，
  校验 `main.py` / `requirements.txt` / `custom_nodes/ComfyUI-KJNodes/__init__.py`
  的落点对不对（解压多剥一层目录这种错，只有真跑才看得见）。
- **加**：假 ComfyUI 的节点清单换成**真实的 H3 节点定义与输入名**（照
  `comfy_extras/nodes_minimax_h3.py` 的 `io.Schema` 写），`test_h3_mock.py` 从 7 组断言扩到 9 组：
  含权重识别、帧数栅格、reconcile 三条分支（删多余 / 报缺必需 / **删到要紧输入就报错**）、
  两种驱动节点不混用、步数跟 LoRA 走、权重缺失时的报错可读性。

> 这一版没有任何界面变化（只在 H3 检测卡上多显示一行「出片节点 / 参考图驱动 / ComfyUI 版本」），
> 但**强烈建议升级**：v1.0.3 及更早版本里，「一键部署」到了下权重那一步会下错东西（354 GB），
> 后面几步也大概率直接失败；就算侥幸装上了，参考生视频也是「出片但参考图不生效」。

### v1.0.3 —— 把「跑通了但结果不对」的几个地方补上

这一版没有新功能，全是「界面看着正常、东西其实没做出来」那类问题。
起因是给 59 个接口做了一次全面巡检：**59 个接口全部返回 200，但角色面板是空的。**

- **修**：角色和场景**只抽卡、不资产化**。`_draw()` 只往候选表里塞东西，
  实体要等用户点「采用」才创建。于是流水线跑满 8 阶段、阶段也 APPROVED 了，
  `entities?kind=character` 却是 0 条 —— 角色面板空白、「音色」下拉提示
  「请先生成角色设计」、质量检查把分镜里明明生成过的角色全报成「未资产化」。
  道具那边本来就在 `build()` 里 upsert，角色/场景漏了，这一版补齐。
  资产化后状态给 `DRAFT`，审核门的语义不变，点「全部通过」才转 `APPROVED`。
- **修**：`POST /api/runtime/install` 传一个不存在的模型版本会 500 + traceback。
  现在 `planner` 直接抛可读错误、路由兜成 400：
  「没有这个模型版本：xxx。可选：h3-lite（H3 精简版（文生 / 图生视频））…」。
- **修**：`/api/runtime/comfy/stop` 原来执行的是
  `taskkill /F /IM python.exe /FI "WINDOWTITLE eq *runtime*"` ——
  按窗口标题杀 python。用户自己开着的 Jupyter、别的脚本，标题里沾上这两个字就一起没了。
  改成按端口反查 PID（`netstat -ano`），并且核对进程名确实是 python 才动手；
  顺手让 `/api/runtime/comfy/start` 在已经在跑时不再起第二个实例。
- **修**：场景抽取会把道具当场景。示例剧本里「站在一块青石前」「不在箱子里」
  被猜成两个场景「一块青石」「箱子」；`【场景 药铺内 夜】` 还会带着「场景 」前缀。
  现在显式标记优先、介词猜出来的地点要求全文出现 ≥2 次才认（真场景总会出现多次），
  并剥掉前缀与尾部时间词。示例项目从 5 个场景收敛成「药铺内 / 后山」。
- **加**：`tools/test_api_surface.py` 进 CI —— 59 个接口逐个真调，5xx 一律算失败，
  另加 5 组**行为**断言（资产化真的落了实体、队列暂停真的把任务卡在 waiting、
  H3 状态自洽、错误路径给的是人话不是 traceback）。只看状态码是不够的。
- **修**：前端 `set-voice` 里残留的一句调试代码
  （对不存在的实体 `x` 发一次 PATCH 再把错误吞掉）。

### v1.0.2 —— 修掉「导出根本跑不起来」

这一版只改了两行 ffmpeg 滤镜，但性质严重：**v1.0.0 / v1.0.1 里导出是坏的**。

- **修**：`pad` 滤镜参数写成了 `pad=606x1080:...`，而 ffmpeg 要的是
  `pad=宽:高:x:y`。它把 `606x1080` 当成宽度表达式，报
  `Invalid chars 'x1080' at the end of expression`，整条导出直接失败。
  任何用户点「导出」都只会拿到一句 `导出失败（退出码 …）`。
  `scale` 用 `宽x高` 是对的，两个滤镜写法不一样，抄错了。
  顺带加上 `force_divisible_by=2`：按比例缩放出来的中间尺寸可能是奇数，
  那样 `pad` 的 `(ow-iw)/2` 不是整数会再报一次错，x264 也不接受奇数尺寸。
- **修**：竖屏分辨率算错。原来按「高 = 预设数字」算，9:16 的 1080p 会得到
  **606x1080** —— 不是任何标准尺寸，还白白丢掉一半纵向分辨率。
  改成按「短边 = 预设数字」：1080p 横屏 1920x1080、竖屏 **1080x1920**
  （抖音/快手标准），720p 竖屏 720x1280，4:5 竖屏 1080x1350。横屏结果不变。
- **加**：`tools/test_export.py` —— 用 ffmpeg 合成三段测试片段当作「已渲染镜头」，
  真跑一遍 concat + scale/pad + 烧字幕，再用 ffprobe 校验产物的分辨率、时长、
  音视频轨、编码。就是它把上面两个问题抓出来的。

> 为什么这么久才发现：导出需要「已渲染镜头」，而没有 N 卡时内置 Provider 只出
> 占位图，`run_export()` 永远走「只返回计划」那条分支 —— 真正拼视频的代码从没被执行过。
> 这个测试用合成片段绕开了显卡依赖。

### v1.0.1 —— 把「一键部署」的地基修牢

只动了一键部署链路，界面和功能没变。但这一版**建议一定要升**：

- **修**：`Downloader` 会把损坏文件当成功。测试里预置 1 MB 垃圾 `.part`，
  下载器报「100% 完成」，直到解压才 `BadZipFile` 崩掉。
  放在 39 GB 的 H3 权重上，就是用户白等几小时才收到一句报错。
  现在三道防线：`.part.meta` 记录来源与总大小 / 无记录的断点主动丢弃 /
  字节数对不上不改名。`unzip()` 坏包抛 `CorruptArchive`，安装器清缓存重下一次。
- **修**：`github.com:443` 单独不可达时，组件下载没有退路。现在每个组件配多个候选镜像
  （ghproxy / gh-proxy / 直连）依次回退。
- **修**：H3 节点识别漏掉「中间插词」的类名（`MiniMaxH3EmptyLatentVideo`）。
  新增关键词加权兜底，识别失败不再依赖精确类名。
- **修**：本机对连不上的本地端口会静默丢包，端口探测每次白等 1~2 秒，
  叠加前端 2 秒轮询后，示例项目要跑 105 秒。现在探测超时压到 0.2 秒 + TTL 缓存，
  **105 秒 → 2 秒**。
- **加**：三个端到端测试，都接进了 CI：
  - `tools/test_h3_mock.py` —— 起一个假 ComfyUI，真跑通「提交 → 轮询 → 取回 MP4」
  - `tools/test_downloader.py` —— 真实下载 + 断点续传（逐字节比对）+ 解压 + 执行 + 取消
  - `tools/test_deploy_slice.py` —— 真跑 `Installer._run()` 全程（下载 → 解压 → 落地 →
    `state.json` → 幂等跳过），实测 uv 与 FFmpeg 两个二进制都能执行
  以后这类问题不用靠运气发现。

> 后续（v1.0.2）又补了第四个：`tools/test_export.py`。就是它抓出「导出根本跑不起来」。

### v1.0.0 —— 首个可安装版本

零依赖后端 + 原生 SPA、8 阶段管线与强制审核门、Provider 抽象层、
一键部署本地 MiniMax H3 运行时、离线包分发、单文件 exe + Inno Setup 安装包。

---

## License

[MIT](LICENSE)
