"""AIVerse 本地服务（文档 §35 / §39）。

零依赖：仅使用 Python 标准库 http.server。
- /api/*   JSON 接口
- /        前端 SPA
- /files/* 项目资产（图片 / 音频 / 字幕 / 时间线）
"""
from __future__ import annotations

import json
import mimetypes
import posixpath
import re
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .agents import DirectorAgent, AgentContext
from .core import candidates as gacha
from .core import costs, db, entities, projects, shots, store
from .core.config import (APP_CODE, APP_NAME, ASPECTS, CONTAINERS, FRONTEND_DIR,
                          RESOLUTIONS, STAGES, STATUS, STYLES, VERSION)
from .gpu import detector as gpu
from .media import ffmpeg
from .providers import registry
from .queue.task_queue import queue
from .services import pipeline
from .workflow import engine

ROUTES: list[tuple[str, str, str]] = []


def route(method: str, pattern: str):
    def deco(fn):
        ROUTES.append((method, pattern, fn.__name__))
        return fn
    return deco


def _comfy_listen_pid(port: int = 8188) -> int | None:
    """反查监听指定端口的进程 PID。查不到返回 None。

    用 `netstat -ano -p TCP` 而不是记 PID 文件：ComfyUI 会自己再 fork 子进程，
    启动时拿到的那个 PID 未必是最终持着端口的那个；按端口查永远拿到真的那个。
    """
    import subprocess
    try:
        r = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                           capture_output=True, text=True, timeout=15,
                           encoding="utf-8", errors="replace")
    except Exception:
        return None
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        # 形如：TCP  127.0.0.1:8188  0.0.0.0:0  LISTENING  12345
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        if not parts[1].endswith(f":{port}") or parts[3].upper() != "LISTENING":
            continue
        try:
            return int(parts[4])
        except ValueError:
            continue
    return None


def _is_python_pid(pid: int) -> bool:
    """确认这个 PID 的进程名是 python 系（python.exe / pythonw.exe）。"""
    import subprocess
    try:
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, timeout=15,
                           encoding="utf-8", errors="replace")
    except Exception:
        return False
    return "python" in (r.stdout or "").lower()


class Api:
    """所有接口实现。每个方法返回 (status, payload)。"""

    # ------------------------------------------------------------ 元信息
    @route("GET", r"/api/health")
    def health(self, m, body, q):
        return 200, {"ok": True, "app": APP_NAME, "code": APP_CODE, "version": VERSION}

    @route("GET", r"/api/meta")
    def meta(self, m, body, q):
        return 200, {
            "app": {"name": APP_NAME, "code": APP_CODE, "version": VERSION},
            "styles": STYLES,
            "aspects": ASPECTS,
            "resolutions": RESOLUTIONS,
            "containers": CONTAINERS,
            "stages": engine.stage_defs(),
            "status": STATUS,
            "gpu": gpu.detect(),
            "ffmpeg": ffmpeg.detect(),
            "providers": registry.list_providers(),
            "voices": [
                {"id": "male_deep", "name": "沉稳男声"},
                {"id": "male_young", "name": "青年男声"},
                {"id": "female_soft", "name": "温柔女声"},
                {"id": "female_bright", "name": "明亮女声"},
                {"id": "child", "name": "童声"},
                {"id": "narrator", "name": "旁白"},
            ],
        }

    @route("GET", r"/api/gpu")
    def gpu_info(self, m, body, q):
        return 200, gpu.detect()

    # ------------------------------------------------------------ 项目
    @route("GET", r"/api/projects")
    def projects_list(self, m, body, q):
        return 200, {"projects": projects.list_projects()}

    @route("POST", r"/api/projects")
    def projects_create(self, m, body, q):
        p = projects.create(
            name=body.get("name") or "未命名项目",
            script=body.get("script") or "",
            style=body.get("style") or "guoman",
            aspect=body.get("aspect") or "9:16",
            resolution=body.get("resolution") or "1080p",
            mode=body.get("mode") or "novice",
            source=body.get("source") or "input",
        )
        return 200, {"ok": True, "project": p}

    @route("GET", r"/api/projects/(?P<pid>[\w\-]+)")
    def project_detail(self, m, body, q):
        d = projects.detail(m["pid"])
        if not d:
            return 404, {"error": "项目不存在"}
        return 200, d

    @route("PATCH", r"/api/projects/(?P<pid>[\w\-]+)")
    def project_update(self, m, body, q):
        p = projects.update(m["pid"], **body)
        return 200, {"ok": True, "project": p}

    @route("DELETE", r"/api/projects/(?P<pid>[\w\-]+)")
    def project_delete(self, m, body, q):
        return 200, projects.delete(m["pid"])

    @route("GET", r"/api/projects/(?P<pid>[\w\-]+)/files")
    def project_files(self, m, body, q):
        return 200, {"files": store.dir_tree(m["pid"])}

    @route("GET", r"/api/projects/(?P<pid>[\w\-]+)/costs")
    def project_costs(self, m, body, q):
        return 200, {"summary": costs.summary(m["pid"]), "by_kind": costs.by_kind(m["pid"])}

    # ------------------------------------------------------------ 剧本
    @route("GET", r"/api/projects/(?P<pid>[\w\-]+)/script")
    def script_get(self, m, body, q):
        return 200, {
            "script": store.read_text(m["pid"], "script/script.md"),
            "analysis": store.read_json(m["pid"], "script/analysis.json", {}),
        }

    @route("POST", r"/api/projects/(?P<pid>[\w\-]+)/script")
    def script_set(self, m, body, q):
        store.write_text(m["pid"], "script/script.md", body.get("script") or "")
        return 200, {"ok": True}

    # ------------------------------------------------------------ 阶段
    @route("GET", r"/api/projects/(?P<pid>[\w\-]+)/stages")
    def stages(self, m, body, q):
        return 200, {"stages": engine.stages_of(m["pid"]),
                     "progress": engine.progress(m["pid"])}

    @route("POST", r"/api/projects/(?P<pid>[\w\-]+)/stage/(?P<key>\w+)/run")
    def stage_run(self, m, body, q):
        try:
            return 200, pipeline.run_stage(m["pid"], m["key"], body or {})
        except Exception as e:
            return 500, {"error": str(e), "trace": traceback.format_exc()[-800:]}

    @route("POST", r"/api/projects/(?P<pid>[\w\-]+)/stage/(?P<key>\w+)/approve")
    def stage_approve(self, m, body, q):
        return 200, engine.approve(m["pid"], m["key"])

    @route("POST", r"/api/projects/(?P<pid>[\w\-]+)/stage/(?P<key>\w+)/reject")
    def stage_reject(self, m, body, q):
        return 200, engine.reject(m["pid"], m["key"], (body or {}).get("reason", ""))

    @route("POST", r"/api/projects/(?P<pid>[\w\-]+)/stage/(?P<key>\w+)/reopen")
    def stage_reopen(self, m, body, q):
        return 200, engine.reopen(m["pid"], m["key"])

    # ------------------------------------------------------------ 抽卡
    @route("GET", r"/api/projects/(?P<pid>[\w\-]+)/candidates")
    def cand_list(self, m, body, q):
        return 200, {
            "candidates": gacha.list_candidates(m["pid"], q.get("stage", [None])[0],
                                                q.get("group", [None])[0]),
            "counts": gacha.group_counts(m["pid"], q.get("stage", ["characters"])[0]),
        }

    @route("POST", r"/api/projects/(?P<pid>[\w\-]+)/gacha/draw")
    def cand_draw(self, m, body, q):
        stage = body.get("stage")
        group = body.get("group")
        n = int(body.get("n") or 3)
        hint = body.get("hint") or ""
        lock = body.get("lock") or []
        name = group.split(":", 1)[1] if ":" in (group or "") else (group or "")
        c = pipeline.ctx(m["pid"])
        from .agents import CharacterAgent, SceneAgent
        if stage == "characters":
            return 200, {"candidates": CharacterAgent(c).redraw(name, n=n, hint=hint, lock=lock)}
        if stage == "scenes":
            return 200, {"candidates": SceneAgent(c).redraw(name, n=n, hint=hint, lock=lock)}
        return 400, {"error": "该阶段暂不支持直接抽卡"}

    @route("POST", r"/api/projects/(?P<pid>[\w\-]+)/gacha/adopt")
    def cand_adopt(self, m, body, q):
        stage = body.get("stage")
        group = body.get("group")
        cid = body.get("candidate_id")
        name = group.split(":", 1)[1] if ":" in (group or "") else (group or "")
        c = pipeline.ctx(m["pid"])
        from .agents import CharacterAgent, SceneAgent
        if stage == "characters":
            return 200, CharacterAgent(c).adopt(name, cid)
        if stage == "scenes":
            return 200, SceneAgent(c).adopt(name, cid)
        return 400, {"error": "该阶段暂不支持直接采用"}

    @route("POST", r"/api/projects/(?P<pid>[\w\-]+)/stage/(?P<key>\w+)/approve_all")
    def approve_all(self, m, body, q):
        c = pipeline.ctx(m["pid"])
        key = m["key"]
        from .agents import CharacterAgent, SceneAgent, StoryboardAgent, VideoAgent
        if key == "characters":
            a = CharacterAgent(c)
            # 先兜底资产化：老项目（这个修复之前跑的）只有候选没有实体，
            # 直接点「全部通过」会通过 0 条。materialize_all 是幂等的。
            a.materialize_all()
            return 200, a.approve_all()
        if key == "scenes":
            a = SceneAgent(c)
            a.materialize_all()
            return 200, a.approve_all()
        if key == "storyboard":
            return 200, StoryboardAgent(c).approve_all()
        if key == "video":
            return 200, VideoAgent(c).approve_all()
        return 400, {"error": "该阶段不支持一键通过"}

    # ------------------------------------------------------------ 资产
    @route("GET", r"/api/projects/(?P<pid>[\w\-]+)/entities")
    def ent_list(self, m, body, q):
        kind = q.get("kind", ["character"])[0]
        return 200, {"entities": entities.list_by_kind(m["pid"], kind)}

    @route("PATCH", r"/api/projects/(?P<pid>[\w\-]+)/entities/(?P<eid>[\w\-]+)")
    def ent_update(self, m, body, q):
        r = entities.update_payload(m["pid"], m["eid"], body.get("patch") or {},
                                    body.get("status"))
        return 200, {"ok": bool(r), "entity": r}

    @route("POST", r"/api/projects/(?P<pid>[\w\-]+)/entities/(?P<eid>[\w\-]+)/snapshot")
    def ent_snapshot(self, m, body, q):
        return 200, entities.snapshot(m["pid"], m["eid"], (body or {}).get("note", ""))

    # ------------------------------------------------------------ 分镜
    @route("GET", r"/api/projects/(?P<pid>[\w\-]+)/shots")
    def shot_list(self, m, body, q):
        return 200, {"shots": shots.list_shots(m["pid"])}

    @route("POST", r"/api/projects/(?P<pid>[\w\-]+)/shots/(?P<no>\d+)/redraw")
    def shot_redraw(self, m, body, q):
        c = pipeline.ctx(m["pid"])
        from .agents import StoryboardAgent
        return 200, StoryboardAgent(c).redraw_shot(
            int(m["no"]), hint=body.get("hint") or "",
            lock=body.get("lock") or [], change=body.get("change") or [])

    @route("POST", r"/api/projects/(?P<pid>[\w\-]+)/shots/(?P<no>\d+)/adopt")
    def shot_adopt(self, m, body, q):
        c = pipeline.ctx(m["pid"])
        from .agents import StoryboardAgent, VideoAgent
        if body.get("kind") == "video":
            return 200, VideoAgent(c).adopt(int(m["no"]), body.get("candidate_id"))
        return 200, StoryboardAgent(c).adopt_shot(int(m["no"]), body.get("candidate_id"))

    @route("POST", r"/api/projects/(?P<pid>[\w\-]+)/shots/reorder")
    def shot_reorder(self, m, body, q):
        return 200, shots.reorder(m["pid"], body.get("order") or [])

    # ------------------------------------------------------------ 视频
    @route("POST", r"/api/projects/(?P<pid>[\w\-]+)/video/generate")
    def video_generate(self, m, body, q):
        pid = m["pid"]
        opts = body or {}
        c = pipeline.ctx(pid)

        def job(progress):
            from .agents import VideoAgent
            total = max(1, len(shots.list_shots(pid)))
            done = 0

            def step(no):
                nonlocal done
                res = VideoAgent(c).generate_shot(
                    no,
                    resolution=opts.get("resolution") or c.project.get("resolution") or "1080p",
                    aspect=opts.get("aspect") or c.project.get("aspect") or "16:9",
                    lock=opts.get("lock"), change=opts.get("change"), hint=opts.get("hint") or "",
                )
                done += 1
                progress(done / total)
                return res

            only = opts.get("only")
            if only:
                return [step(int(n)) for n in only]
            out = []
            for s in shots.list_shots(pid):
                out.append(step(s["no"]))
            engine.set_status(pid, "video", STATUS["REVIEW"],
                              {"generated": [x["no"] for x in out], "failed": []})
            return out

        tid = queue().submit(pid, "视频生成", "video", job, priority=int(opts.get("priority") or 5))
        return 200, {"ok": True, "task_id": tid}

    @route("POST", r"/api/projects/(?P<pid>[\w\-]+)/video/regenerate")
    def video_regenerate(self, m, body, q):
        pid = m["pid"]
        opts = body or {}
        c = pipeline.ctx(pid)

        def job(progress):
            from .agents import VideoAgent
            progress(0.2)
            res = VideoAgent(c).generate_shot(
                int(opts["no"]),
                resolution=opts.get("resolution") or "1080p",
                aspect=opts.get("aspect") or "16:9",
                lock=opts.get("lock") or ["character", "scene", "camera", "style"],
                change=opts.get("change") or ["action"],
                hint=opts.get("hint") or "",
            )
            progress(1.0)
            return res

        tid = queue().submit(pid, f"S{int(opts['no']):03d} 局部重生成", "video", job, priority=1)
        return 200, {"ok": True, "task_id": tid}

    @route("GET", r"/api/projects/(?P<pid>[\w\-]+)/quality")
    def quality(self, m, body, q):
        return 200, pipeline.quality_report(m["pid"])

    # ------------------------------------------------------------ 时间线
    @route("GET", r"/api/projects/(?P<pid>[\w\-]+)/timeline")
    def timeline_get(self, m, body, q):
        return 200, {"timeline": store.read_json(m["pid"], "timeline/timeline.json", {}),
                     "audio": store.read_json(m["pid"], "audio/timeline.json", {}),
                     "subtitle": store.read_text(m["pid"], "subtitles/subtitle.srt", "")}

    @route("POST", r"/api/projects/(?P<pid>[\w\-]+)/timeline")
    def timeline_set(self, m, body, q):
        store.write_json(m["pid"], "timeline/timeline.json", body.get("timeline") or {})
        return 200, {"ok": True}

    # ------------------------------------------------------------ 导出
    @route("POST", r"/api/projects/(?P<pid>[\w\-]+)/export")
    def export(self, m, body, q):
        p = projects.get(m["pid"])
        result = ffmpeg.run_export(p, shots.list_shots(m["pid"]), body or {})
        return 200, {"ok": True, "plan": result}

    # ------------------------------------------------------------ 环境部署（本地 H3）
    @route("GET", r"/api/runtime/status")
    def runtime_status(self, m, body, q):
        from .runtime.installer import installer
        return 200, installer().status()

    @route("GET", r"/api/runtime/plan")
    def runtime_plan(self, m, body, q):
        from .runtime import catalog, planner
        mirror = q.get("mirror", ["cn"])[0]
        model = q.get("model", [None])[0]
        nodes = q.get("nodes", [None])[0]
        return 200, {
            "plan": planner.build_plan(
                mirror=mirror, model_key=model or None,
                include_nodes=(None if nodes is None else nodes == "1"),
            ),
            "mirrors": {k: v["name"] for k, v in catalog.MIRRORS.items()},
            "models": {k: {"name": v["name"], "size_gb": v["size_gb"],
                           "min_vram": v["min_vram"], "desc": v["desc"]}
                       for k, v in catalog.MODEL_REPOS.items()},
            "deps": catalog.RUNTIME_DEPS,
        }

    @route("POST", r"/api/runtime/install")
    def runtime_install(self, m, body, q):
        from .runtime.installer import installer
        try:
            return 200, installer().start(
                mirror=body.get("mirror") or "cn",
                model_key=body.get("model"),
                include_nodes=body.get("nodes"),
            )
        except ValueError as e:
            # 参数写错（比如不存在的模型版本）是 400，不是 500
            return 400, {"error": str(e)}

    @route("POST", r"/api/runtime/cancel")
    def runtime_cancel(self, m, body, q):
        from .runtime.installer import installer
        return 200, installer().cancel()

    @route("POST", r"/api/runtime/retry")
    def runtime_retry(self, m, body, q):
        from .runtime.installer import installer
        return 200, installer().retry_failed()

    @route("GET", r"/api/runtime/h3")
    def runtime_h3(self, m, body, q):
        """H3 Provider 健康检查：ComfyUI 是否在跑、H3 节点是否就绪。

        优先检查 H3 Adapter（id=video-h3），而不是当前生效的占位 Provider，
        这样用户还没接通时也能看到「差在哪一步」。
        """
        from .providers import registry
        p = registry.get("video", "video-h3") or registry.get("video")
        active = registry.get("video")
        detail = p.health() if hasattr(p, "health") else {"ok": False, "detail": "无视频 Provider"}
        return 200, {
            "provider": p.name if p else None,
            "provider_id": p.id if p else None,
            "type": p.type if p else None,
            "active": active.name if active else None,
            "is_active": bool(p and active and p.id == active.id),
            "base_url": p.base_url if p else "",
            **detail,
        }

    @route("POST", r"/api/runtime/h3/detect-nodes")
    def runtime_h3_detect(self, m, body, q):
        """连本地 ComfyUI 自动识别 H3 节点类名，并持久化写回 Provider 配置。"""
        from .providers import registry
        p = registry.get("video", "video-h3") or registry.get("video")
        if not hasattr(p, "node_map"):
            return 400, {"error": "当前视频 Provider 不支持节点识别"}
        nm = p.node_map()
        meta = dict(getattr(p, "meta", {}) or {})
        meta["node_map"] = nm
        # 只有 ComfyUI 真的连得上、H3 节点真的就绪，才把它设为默认视频 Provider；
        # 否则只记住映射，等环境装好后再自动接管。
        try:
            healthy = bool(p.health().get("ok"))
        except Exception:
            healthy = False
        try:
            registry.upsert_builtin(p.id or "video-h3", {
                "name": p.name, "type": "video", "base_url": p.base_url,
                "models": list(p.models or []), "meta": meta, "enabled": healthy,
            })
            persisted = True
        except Exception:
            persisted = False
        return 200, {"ok": True, "node_map": nm, "persisted": persisted,
                     "enabled": healthy,
                     "message": ("H3 已就绪，已设为默认视频 Provider"
                                 if healthy else
                                 "节点映射已保存；ComfyUI/H3 尚未就绪，装好后会自动接管")}

    @route("POST", r"/api/runtime/import/verify")
    def runtime_import_verify(self, m, body, q):
        """只读校验：判断某个目录是否是完整可用的离线运行时包。"""
        from .runtime.installer import installer
        return 200, installer().verify_offline((body or {}).get("source") or "")

    @route("POST", r"/api/runtime/import")
    def runtime_import(self, m, body, q):
        """从离线包（U 盘 / 内网共享）导入运行时，全程不联网。"""
        from .runtime.installer import installer
        return 200, installer().import_offline((body or {}).get("source") or "")

    @route("POST", r"/api/runtime/export")
    def runtime_export(self, m, body, q):
        """把本机已部署好的运行时导出成可拷贝的离线包。"""
        from .runtime.installer import installer
        return 200, installer().export_offline((body or {}).get("dest") or "")

    @route("POST", r"/api/runtime/comfy/start")
    def runtime_comfy_start(self, m, body, q):
        """启动本地 ComfyUI（由部署器安装的那份）。"""
        import subprocess
        from .core.config import RUNTIME_DIR
        rt = RUNTIME_DIR
        main_py = rt / "comfyui" / "main.py"
        venv_py = rt / "venv" / "Scripts" / "python.exe"
        if not main_py.exists() or not venv_py.exists():
            return 400, {"error": "ComfyUI 尚未部署，请先在「环境部署」里一键安装"}
        running = _comfy_listen_pid()
        if running:
            # 重复点「启动」不该再起一个 —— 第二个实例会抢不到端口然后静默退出，
            # 用户看到的是「启动了但没反应」。
            return 200, {"ok": True, "url": "http://127.0.0.1:8188", "pid": running,
                         "message": "ComfyUI 已经在运行了"}
        try:
            subprocess.Popen(
                [str(venv_py), str(main_py), "--listen", "127.0.0.1", "--port", "8188"],
                cwd=str(rt / "comfyui"),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            return 500, {"error": f"启动失败：{e}"}
        return 200, {"ok": True, "url": "http://127.0.0.1:8188",
                     "message": "ComfyUI 正在启动，约 20 秒后可用"}

    @route("POST", r"/api/runtime/comfy/stop")
    def runtime_comfy_stop(self, m, body, q):
        """停掉本机 8188 上的 ComfyUI。

        早先这里是 `taskkill /F /IM python.exe /FI "WINDOWTITLE eq *runtime*"`：
        按「窗口标题里含 runtime」去杀 python.exe —— 用户自己开着的 Jupyter、
        别的 python 脚本，只要窗口标题沾上这两个字就一起没了。
        改成按端口反查 PID：只杀真正监听 8188 的那个进程，而且额外核对镜像名，
        确认它确实是 python.exe 才动手。
        """
        import subprocess
        pid = _comfy_listen_pid()
        if not pid:
            return 200, {"ok": True, "stopped": False,
                         "message": "没有发现监听 8188 的进程，ComfyUI 应该已经停了"}
        if not _is_python_pid(pid):
            return 200, {"ok": False, "stopped": False,
                         "message": f"8188 被 PID {pid} 占着，但它不是 python.exe，"
                                    f"不敢动它（可能是别的软件）"}
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=15)
        except Exception as e:
            return 200, {"ok": False, "stopped": False, "message": f"停止失败：{e}"}
        return 200, {"ok": True, "stopped": True, "pid": pid,
                     "message": f"已停止 ComfyUI（PID {pid}）"}

    # ------------------------------------------------------------ 工作流
    @route("GET", r"/api/projects/(?P<pid>[\w\-]+)/workflow")
    def workflow_get(self, m, body, q):
        c = pipeline.ctx(m["pid"])
        return 200, DirectorAgent(c).summarize()

    @route("POST", r"/api/projects/(?P<pid>[\w\-]+)/workflow/plan")
    def workflow_plan(self, m, body, q):
        c = pipeline.ctx(m["pid"])
        return 200, DirectorAgent(c).plan((body or {}).get("request") or "")

    @route("GET", r"/api/projects/(?P<pid>[\w\-]+)/batch")
    def batch(self, m, body, q):
        n = int(q.get("episodes", ["3"])[0])
        return 200, pipeline.batch_plan(m["pid"], n)

    # ------------------------------------------------------------ 任务队列
    @route("GET", r"/api/tasks")
    def tasks(self, m, body, q):
        pid = q.get("project_id", [None])[0]
        return 200, {"tasks": queue().list(pid), "stats": queue().stats()}

    @route("POST", r"/api/tasks/(?P<tid>[\w\-]+)/cancel")
    def task_cancel(self, m, body, q):
        return 200, queue().cancel(m["tid"])

    @route("POST", r"/api/tasks/(?P<tid>[\w\-]+)/retry")
    def task_retry(self, m, body, q):
        return 200, queue().retry(m["tid"])

    @route("POST", r"/api/tasks/(?P<tid>[\w\-]+)/bump")
    def task_bump(self, m, body, q):
        return 200, queue().bump(m["tid"], int((body or {}).get("priority") or 0))

    @route("POST", r"/api/queue/pause")
    def queue_pause(self, m, body, q):
        return 200, queue().pause()

    @route("POST", r"/api/queue/resume")
    def queue_resume(self, m, body, q):
        return 200, queue().resume()

    # ------------------------------------------------------------ Provider
    @route("GET", r"/api/providers")
    def prov_list(self, m, body, q):
        return 200, {"providers": registry.list_providers()}

    @route("POST", r"/api/providers")
    def prov_add(self, m, body, q):
        r = registry.add(body.get("name") or "新 Provider", body.get("type") or "llm",
                         body.get("base_url") or "", body.get("api_key") or "",
                         body.get("models") or [], body.get("meta") or {})
        return 200, {"ok": True, **r}

    @route("PATCH", r"/api/providers/(?P<pid>[\w\-]+)")
    def prov_update(self, m, body, q):
        registry.update(m["pid"], **body)
        return 200, {"ok": True}

    @route("DELETE", r"/api/providers/(?P<pid>[\w\-]+)")
    def prov_delete(self, m, body, q):
        registry.delete(m["pid"])
        return 200, {"ok": True}


API = Api()


class Handler(BaseHTTPRequestHandler):
    server_version = f"AIVerse/{VERSION}"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 静默访问日志
        pass

    # ---- 工具 ------------------------------------------------------
    def _send_json(self, status: int, payload) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_bytes(self, status: int, data: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _dispatch(self, method: str) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        q = urllib.parse.parse_qs(parsed.query)
        body = self._read_body() if method in ("POST", "PATCH", "PUT", "DELETE") else {}

        if path.startswith("/api/"):
            for rmethod, pattern, fname in ROUTES:
                if rmethod != method:
                    continue
                mm = re.fullmatch(pattern, path)
                if mm:
                    try:
                        status, payload = getattr(API, fname)(mm.groupdict(), body, q)
                    except Exception as e:
                        status, payload = 500, {"error": str(e),
                                                "trace": traceback.format_exc()[-800:]}
                    return self._send_json(status, payload)
            return self._send_json(404, {"error": f"未找到接口 {method} {path}"})

        if method == "GET":
            return self._serve_static(path)
        return self._send_json(405, {"error": "method not allowed"})

    # ---- 静态资源 --------------------------------------------------
    def _serve_static(self, path: str) -> None:
        if path.startswith("/files/"):
            rel = path[len("/files/"):]
            parts = rel.split("/", 1)
            if len(parts) != 2:
                return self._send_json(404, {"error": "bad file path"})
            pid, sub = parts
            base = store.resolve(pid)
            target = (base / posixpath.normpath(sub)).resolve()
            try:
                target.relative_to(base.resolve())
            except Exception:
                return self._send_json(403, {"error": "forbidden"})
            if not target.exists() or target.is_dir():
                return self._send_json(404, {"error": "file not found"})
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            return self._send_bytes(200, target.read_bytes(), ctype)

        if path in ("/", "/index.html"):
            f = FRONTEND_DIR / "index.html"
        else:
            f = (FRONTEND_DIR / posixpath.normpath(path.lstrip("/"))).resolve()
            try:
                f.relative_to(FRONTEND_DIR.resolve())
            except Exception:
                return self._send_json(403, {"error": "forbidden"})
        if not f.exists() or f.is_dir():
            # SPA 回退
            f = FRONTEND_DIR / "index.html"
            if not f.exists():
                return self._send_json(404, {"error": "frontend not found"})
        ctype = mimetypes.guess_type(str(f))[0] or "text/plain"
        if f.suffix in (".js", ".css", ".html"):
            ctype += "; charset=utf-8"
        return self._send_bytes(200, f.read_bytes(), ctype)

    # ---- HTTP 方法 -------------------------------------------------
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET,POST,PATCH,DELETE,OPTIONS")
        self.end_headers()


class _Server(ThreadingHTTPServer):
    """静默掉浏览器主动断开连接时抛的 ConnectionResetError/BrokenPipe。

    这些异常本身无害（前端轮询、用户刷新页面都会触发），
    但 socketserver 默认会打一整片 traceback，把真正的日志淹掉。
    """

    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def serve(host: str, port: int) -> ThreadingHTTPServer:
    httpd = _Server((host, port), Handler)
    # 首次运行自动播种一个示例项目（项目数为 0 时才做，后台跑，不阻塞启动）
    try:
        from .services import seed
        seed.ensure_demo_project()
    except Exception as e:
        print(f"  [warn] 示例项目播种失败：{e}")
    return httpd
