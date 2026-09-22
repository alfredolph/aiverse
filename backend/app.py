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
            return 200, CharacterAgent(c).approve_all()
        if key == "scenes":
            return 200, SceneAgent(c).approve_all()
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
        plan = ffmpeg.build_export_plan(p, shots.list_shots(m["pid"]), body or {})
        return 200, {"ok": True, "plan": plan}

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


def serve(host: str, port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd
