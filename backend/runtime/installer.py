"""部署执行引擎 —— 把计划变成真实动作。

特性：
  * 后台线程顺序执行，实时输出日志
  * 状态持久化到 runtime/state.json，中途关掉程序也能看到进度
  * 可取消；已完成的步骤会跳过（幂等）
  * 所有文件只写入 RUNTIME_DIR，不碰系统环境
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from ..core import db
from ..core.config import RUNTIME_DIR
from . import catalog, planner
from .downloader import Cancelled, CorruptArchive, Downloader, human_size

STATE_FILE = RUNTIME_DIR / "state.json"
COMFY_URL = "http://127.0.0.1:8188"


class Installer:
    """单例式部署器（同一时间只允许一个部署任务）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._state: dict[str, Any] = self._load()

    # ------------------------------------------------------------ 状态
    def _load(self) -> dict[str, Any]:
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"status": "idle", "steps": {}, "log": [], "plan": None}

    def _save(self) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(self._state, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    def _log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        with self._lock:
            self._state.setdefault("log", []).append(line)
            self._state["log"] = self._state["log"][-400:]
        print(f"[runtime] {msg}")

    def status(self) -> dict[str, Any]:
        """前端每 2 秒轮询一次，所以这里的所有探测都必须带缓存。

        `import torch` 要跑 5~20 秒、`_dir_size` 要遍历十万个文件，
        没有缓存的话光轮询就能把机器拖死。
        """
        with self._lock:
            st = dict(self._state)
        st["runtime_dir"] = str(RUNTIME_DIR)
        st["installed"] = self.detect_installed()
        st["disk_used_gb"] = round(_cached("dirsize", 30.0,
                                           lambda: _dir_size(RUNTIME_DIR)) / 1024 ** 3, 2)
        st["running"] = bool(self._thread and self._thread.is_alive())
        return st

    # ------------------------------------------------------------ 检测
    def detect_installed(self) -> dict[str, Any]:
        """探测各组件是否就位（整体缓存 3 秒，避免 2 秒轮询里重复劳动）。"""
        return _cached("installed", 3.0, self._detect_installed)

    def _detect_installed(self) -> dict[str, Any]:
        rt = RUNTIME_DIR
        venv_py = rt / "venv" / "Scripts" / "python.exe"
        return {
            "uv": (rt / "uv" / "uv.exe").exists(),
            "python": (rt / "venv" / "pyvenv.cfg").exists(),
            "torch": _has_package(venv_py, "torch"),
            "comfyui": (rt / "comfyui" / "main.py").exists(),
            "ffmpeg": (rt / "ffmpeg" / "bin" / "ffmpeg.exe").exists(),
            "h3_weights": _model_ready(rt / "comfyui" / "models"),
            "comfy_running": _comfy_alive(COMFY_URL),
        }

    # ------------------------------------------------------------ 启动
    def start(self, mirror: str = "cn", model_key: str | None = None,
              include_nodes: bool | None = None) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return {"ok": False, "error": "已有部署任务在进行中"}
            plan = planner.build_plan(mirror=mirror, model_key=model_key,
                                      include_nodes=include_nodes)
            if not plan["can_local"] and model_key:
                return {"ok": False, "error": "当前无可用 GPU，无法部署本地推理环境"}
            self._state = {
                "status": "running", "plan": plan, "log": [],
                "steps": {s["key"]: {"status": "pending", "percent": 0.0,
                                     "message": s["desc"]} for s in plan["steps"]},
                "started_at": time.time(), "finished_at": None, "error": None,
            }
            self._cancel.clear()
            self._save()
            self._thread = threading.Thread(target=self._run, args=(plan,),
                                            name="aiverse-installer", daemon=True)
            self._thread.start()
        return {"ok": True, "plan": plan}

    def cancel(self) -> dict[str, Any]:
        self._cancel.set()
        self._log("收到取消请求，正在停止…")
        return {"ok": True}

    def retry_failed(self) -> dict[str, Any]:
        with self._lock:
            plan = self._state.get("plan")
        if not plan:
            return {"ok": False, "error": "没有可重试的部署计划"}
        return self.start(mirror=plan.get("mirror", "cn"), model_key=plan.get("model"),
                          include_nodes=any(s["key"] == "comfy-nodes" for s in plan["steps"]))

    # ------------------------------------------------------------ 执行
    def _set_step(self, key: str, **fields) -> None:
        with self._lock:
            self._state.setdefault("steps", {}).setdefault(key, {})
            self._state["steps"][key].update(fields)
        self._save()

    def _progress_cb(self, key: str):
        def cb(d: dict) -> None:
            self._set_step(key,
                           status="running",
                           percent=d.get("percent", 0.0),
                           message=d.get("message", ""),
                           speed_mbps=d.get("speed_mbps"),
                           eta_seconds=d.get("eta_seconds"))
        return cb

    def _run(self, plan: dict) -> None:
        dl = Downloader(progress=None, is_cancelled=self._cancel.is_set)
        rt = RUNTIME_DIR
        rt.mkdir(parents=True, exist_ok=True)
        m = dict(catalog.MIRRORS.get(plan["mirror"], catalog.MIRRORS["cn"]))
        m["_key"] = plan["mirror"] if plan["mirror"] in catalog.MIRRORS else "cn"
        self._log(f"开始部署，目标目录 {rt}，预计下载 {plan['total_download_human']}")

        try:
            for s in plan["steps"]:
                key = s["key"]
                if self._cancel.is_set():
                    raise Cancelled()
                if self._already_done(s):
                    self._set_step(key, status="done", percent=100.0, message="已存在，跳过")
                    self._log(f"跳过（已安装）：{s['name']}")
                    continue

                self._set_step(key, status="running", percent=0.0, message=s["desc"])
                self._log(f"开始：{s['name']}")
                dl.progress = self._progress_cb(key)
                t0 = time.time()

                self._execute(s, plan, dl, m, rt)

                if s.get("marker"):
                    mp = rt / s["marker"]
                    mp.parent.mkdir(parents=True, exist_ok=True)
                    mp.write_text(f"done at {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
                                  encoding="utf-8")

                self._set_step(key, status="done", percent=100.0,
                               message=f"完成，耗时 {int(time.time() - t0)}s")
                self._log(f"完成：{s['name']}（{int(time.time() - t0)}s）")

            with self._lock:
                self._state["status"] = "done"
                self._state["finished_at"] = time.time()
            self._save()
            invalidate_cache()
            self._log("全部部署完成，可以开始本地出片了")

        except Cancelled:
            with self._lock:
                self._state["status"] = "cancelled"
                self._state["finished_at"] = time.time()
            self._save()
            self._log("部署已取消")
        except Exception as e:
            with self._lock:
                self._state["status"] = "failed"
                self._state["error"] = str(e)
                self._state["finished_at"] = time.time()
            self._save()
            self._log(f"部署失败：{e}")

    def _already_done(self, s: dict) -> bool:
        """这一步是否已经完成过（幂等判断）。

        带 marker 的步骤（装依赖、装节点）以「完工标记文件」为准 ——
        比去猜某个包有没有装上可靠，猜错的代价是每次重跑都重装一遍。
        """
        key = s["key"]
        rt = RUNTIME_DIR
        marker = s.get("marker")
        if marker and (rt / marker).exists():
            return True
        inst = self.detect_installed()
        return {
            "uv": inst["uv"],
            "python": inst["python"],
            "venv": inst["python"],
            "torch": inst["torch"],
            "comfyui": (rt / "comfyui" / "main.py").exists(),
            "comfyui-install": inst["comfyui"],          # 旧 state.json 兼容
            "comfy-nodes": (rt / "comfyui" / "custom_nodes"
                            / "ComfyUI-KJNodes" / "__init__.py").exists(),
            "model-tool": False,
            "h3-weights": inst["h3_weights"],
            "ffmpeg": inst["ffmpeg"],
            "wire": (rt / "wired.json").exists(),
        }.get(key, False)

    def _execute(self, s: dict, plan: dict, dl: Downloader, m: dict, rt: Path) -> None:
        kind = s["kind"]

        if kind == "download_zip":
            self._do_download_zip(s, m, rt, dl)

        elif kind == "exec":
            self._do_exec(s["cmd"], s.get("cwd") or str(rt), s["key"])

        elif kind == "install_reqs":
            self._do_install_reqs(s["cmd"], s.get("cwd") or str(rt))

        elif kind == "model_download":
            # 早期版本把参数塞进 cmd 里用 `--k v` 解析，结果 subdir 被收下却从没用过，
            # 用户选「精简版」实际会拖整个原始仓库。现在直接读步骤字段，少一层转手。
            venv_py = rt / "venv" / "Scripts" / "python.exe"
            dl.download_model_repo(
                repo=s["repo"], target=Path(s["target"]), backend=s["backend"],
                files=s.get("files") or [], venv_python=venv_py,
                expected_gb=s["size_gb"],
            )

        elif kind == "wire":
            self._do_wire(plan, rt, dl)

        else:
            raise RuntimeError(f"未知步骤类型 {kind}")

    # ------------------------------------------------------------ 各类型实现
    def _do_download_zip(self, s: dict, m: dict, rt: Path, dl: Downloader) -> None:
        key = s["key"]
        # 每个组件的落点 + 判断安装成功的标志文件
        targets = {
            "uv": (rt / "uv", rt / "uv" / "uv.exe"),
            "ffmpeg": (rt / "ffmpeg", rt / "ffmpeg" / "bin" / "ffmpeg.exe"),
            "comfyui": (rt / "comfyui", rt / "comfyui" / "main.py"),
            "kj-nodes": (rt / "comfyui" / "custom_nodes" / "ComfyUI-KJNodes",
                         rt / "comfyui" / "custom_nodes" / "ComfyUI-KJNodes" / "__init__.py"),
        }
        entry = targets.get(key)
        if not entry:
            raise RuntimeError(f"未配置下载地址：{key}")
        unzip_to, dest = entry
        if s.get("unzip_to"):
            unzip_to = Path(s["unzip_to"])
            dest = unzip_to / dest.name

        # 同一个组件给多个镜像候选，前一个挂了自动换下一个
        urls = catalog.component_urls(key, m.get("_key") or "cn")
        if not urls:
            raise RuntimeError(f"未配置下载地址：{key}")

        tmp = rt / "cache" / f"{key}.zip"
        for attempt in (1, 2):
            try:
                dl.fetch(urls, tmp, label=s["name"], expected_gb=s["size_gb"])
                dl.unzip(tmp, unzip_to)
                break
            except CorruptArchive as e:
                # 压缩包坏了通常是缓存被污染（续传到了垃圾数据）。
                # 清掉重下一次，还坏就老实报错，别让用户拿到一个坏安装。
                self._log(f"  ! {s['name']} 压缩包损坏，清理缓存后重下：{e}")
                for p in (tmp, tmp.with_suffix(tmp.suffix + ".part"),
                          tmp.with_suffix(tmp.suffix + ".part.meta")):
                    try:
                        p.unlink()
                    except OSError:
                        pass
                if attempt == 2:
                    raise

        try:
            tmp.unlink()
        except OSError:
            pass
        if not dest.exists():
            # 兼容压缩包内多一层目录的情况
            found = next(rt.rglob(dest.name), None)
            if found:
                found.parent.mkdir(parents=True, exist_ok=True)
                if found != dest:
                    import shutil
                    shutil.copy2(found, dest)
        if not dest.exists():
            raise RuntimeError(f"{s['name']} 安装后仍未找到 {dest.name}，安装不完整")

    def _do_install_reqs(self, cmd: list[str], cwd: str) -> None:
        """跑 `uv pip install -r <requirements.txt>`。

        没有 requirements.txt 就跳过 —— KJNodes 之类的节点包不一定带，
        这不是错误，不该让整个部署失败。
        """
        if "-r" in cmd:
            req = Path(cmd[cmd.index("-r") + 1])
            if not req.exists():
                self._log(f"  没有 {req.name}，跳过（该组件不需要额外依赖）")
                return
        self._do_exec(cmd, cwd, "install_reqs")

    def _do_exec(self, cmd: list[str], cwd: str, key: str) -> None:
        exe = Path(cmd[0])
        if not exe.exists():
            raise RuntimeError(f"找不到可执行文件：{exe}")
        env = dict(os.environ)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env["UV_INDEX_URL"] = catalog.MIRRORS["cn"]["pypi"]
        Path(cwd).mkdir(parents=True, exist_ok=True)

        self._log("  $ " + " ".join(cmd))
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="ignore", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            if self._cancel.is_set():
                proc.kill()
                raise Cancelled()
            line = line.rstrip()
            if line:
                self._log("  | " + line[:200])
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"命令失败（退出码 {proc.returncode}）：{cmd[0]}")

    def _do_wire(self, plan: dict, rt: Path, dl: Downloader | None = None) -> None:
        """写入 H3 工作流模板，并把 H3 注册为视频 Provider。"""
        from ..providers import registry
        from ..providers.h3_workflows import detect_model_files, export_templates

        wf_dir = rt / "comfyui" / "user" / "default" / "workflows" / "aiverse"
        wf_dir.mkdir(parents=True, exist_ok=True)
        written = export_templates(wf_dir)
        self._log(f"已写入 H3 工作流模板：{', '.join(p.name for p in written)}")

        # 把「实际下到哪些权重文件」记进 Provider：H3 的图要按文件名去 UNETLoader /
        # CLIPLoader / VAELoader 里选，名字对不上 ComfyUI 就直接报节点校验失败。
        models_dir = rt / "comfyui" / "models"
        found = detect_model_files(models_dir)
        self._log("识别到权重：" + ("、".join(f"{k}={v}" for k, v in found.items())
                                   or "（未找到，需先完成权重下载）"))

        registry.upsert_builtin("video-h3", {
            "name": "MiniMax H3（本地 ComfyUI）",
            "type": "video",
            "base_url": COMFY_URL,
            "models": ["h3-fl2va", "h3-ref2va"],
            "enabled": True,
            "meta": {
                "backend": "comfyui",
                "model_dir": str(models_dir),
                "workflow_dir": str(wf_dir),
                "model_files": found,
                "variant": plan.get("model") or "",
                "precision": plan.get("tier", {}).get("precision", ""),
                "offload": plan.get("tier", {}).get("offload", True),
                "native_resolution": "768p",
                "notes": "ComfyUI 原生支持 H3（需 0.30.0+）；原生 768p，含音频轨。"
                         "中文口播较弱，建议走 TTS 后期配音。",
            },
        })
        (rt / "wired.json").write_text(
            json.dumps({"wired_at": time.time(), "model": plan.get("model"),
                        "model_files": found}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        self._log("H3 已注册为视频 Provider（地址 %s）" % COMFY_URL)

    # ------------------------------------------------------------ 离线包
    def export_offline(self, dest_dir: str) -> dict[str, Any]:
        """把已部署好的运行时导出成可拷贝的离线包（U 盘 / 内网共享）。

        导出后对方机器上「离线导入」即可，无需再下载任何东西。
        """
        import shutil

        src = RUNTIME_DIR
        if not (src / "comfyui" / "main.py").exists():
            return {"ok": False, "error": "本机尚未部署运行时，没有可导出的内容"}
        if not dest_dir:
            return {"ok": False, "error": "请填写导出目标目录"}

        dest = Path(dest_dir).expanduser().resolve() / "AIVerse-Runtime"
        skip = {"cache", "state.json", "logs"}
        self._log(f"开始导出离线包到 {dest}")

        def _ignore(_dir, names):
            return [n for n in names if n in skip]

        try:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dest, dirs_exist_ok=True, ignore=_ignore)
        except Exception as e:
            return {"ok": False, "error": f"导出失败：{e}"}

        size_gb = round(_dir_size(dest) / 1024 ** 3, 2)
        (dest / "离线安装说明.txt").write_text(_offline_readme(size_gb),
                                              encoding="utf-8")
        self._log(f"离线包导出完成：{dest}（{size_gb} GB）")
        return {"ok": True, "path": str(dest), "size_gb": size_gb}

    def verify_offline(self, source_dir: str) -> dict[str, Any]:
        """在不复制任何文件的前提下，检查一个目录像不像可用的离线包。"""
        if not source_dir:
            return {"ok": False, "error": "请填写离线包目录"}
        src = Path(source_dir).expanduser()
        if not src.exists():
            return {"ok": False, "error": f"目录不存在：{src}"}
        root = src / "AIVerse-Runtime" if (src / "AIVerse-Runtime").exists() else src

        checks = {
            "ComfyUI 执行引擎": root / "comfyui" / "main.py",
            "Python 隔离环境": root / "venv" / "pyvenv.cfg",
            "PyTorch + CUDA": root / "venv" / "Lib" / "site-packages" / "torch",
            "MiniMax H3 权重": root / "comfyui" / "models" / "diffusion_models",
            "FFmpeg": root / "ffmpeg" / "bin" / "ffmpeg.exe",
        }
        found = [k for k, p in checks.items() if p.exists()]
        missing = [k for k, p in checks.items() if not p.exists()]
        size_gb = round(_dir_size(root) / 1024 ** 3, 2)
        if not found:
            return {"ok": False, "error": f"该目录里没有找到任何运行时组件：{root}"}
        return {"ok": True, "root": str(root), "found": found, "missing": missing,
                "size_gb": size_gb,
                "warnings": ([f"缺少：{'、'.join(missing)}，导入后仍可能需要联网补齐"]
                             if missing else [])}

    def import_offline(self, source_dir: str) -> dict[str, Any]:
        """从离线包导入运行时（后台线程，带进度与日志）。"""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return {"ok": False, "error": "已有任务在进行中"}
            if not source_dir:
                return {"ok": False, "error": "请填写离线包目录"}
            src = Path(source_dir).expanduser().resolve()
            if src.name == "AIVerse-Runtime":
                root = src
            elif (src / "AIVerse-Runtime").exists():
                root = src / "AIVerse-Runtime"
            else:
                root = src
            if not (root / "comfyui" / "main.py").exists() and \
               not (root / "venv" / "pyvenv.cfg").exists():
                return {"ok": False,
                        "error": f"该目录不像是离线包（缺少 comfyui/ 或 venv/）：{root}"}
            self._state = {
                "status": "running",
                "plan": {"mirror": "offline", "steps": [
                    {"key": "offline-import", "name": "导入离线运行时",
                     "desc": f"从 {root} 复制到 {RUNTIME_DIR}", "size_gb": 0,
                     "size_human": "—", "kind": "import", "optional": False}]},
                "log": [],
                "steps": {"offline-import": {"status": "running", "percent": 0.0,
                                             "message": "正在复制文件…"}},
                "started_at": time.time(), "finished_at": None, "error": None,
            }
            self._cancel.clear()
            self._save()
            self._thread = threading.Thread(target=self._run_import, args=(root,),
                                            name="aiverse-import", daemon=True)
            self._thread.start()
        return {"ok": True, "source": str(root), "dest": str(RUNTIME_DIR)}

    def _run_import(self, root: Path) -> None:
        import shutil

        rt = RUNTIME_DIR
        rt.mkdir(parents=True, exist_ok=True)
        self._log(f"开始导入离线运行时：{root} → {rt}")
        try:
            total = max(_dir_size(root), 1)
            copied = 0
            for dirpath, dirnames, filenames in os.walk(root):
                if self._cancel.is_set():
                    raise Cancelled()
                rel = Path(dirpath).relative_to(root)
                if rel.parts and rel.parts[0] == "cache":
                    dirnames[:] = []
                    continue
                (rt / rel).mkdir(parents=True, exist_ok=True)
                for fn in filenames:
                    if fn == "state.json":
                        continue
                    s = Path(dirpath) / fn
                    d = rt / rel / fn
                    try:
                        if not (d.exists() and d.stat().st_size == s.stat().st_size):
                            shutil.copy2(s, d)
                        copied += s.stat().st_size
                    except Exception:
                        pass
                    if total:
                        pct = min(99.9, copied / total * 100)
                        self._set_step("offline-import", percent=pct,
                                       message=f"已复制 {human_size(copied)} / {human_size(total)}")

            self._set_step("offline-import", status="done", percent=100.0, message="复制完成")
            # 复用 wire：写工作流模板 + 注册 Provider
            plan = {"model": None, "tier": {}}
            wf = rt / "wired.json"
            if wf.exists():
                try:
                    plan["model"] = json.loads(wf.read_text(encoding="utf-8")).get("model")
                except Exception:
                    pass
            try:
                self._do_wire(plan, rt, None)   # type: ignore[arg-type]
            except Exception as e:
                self._log(f"注册 Provider 时出现非致命问题：{e}")

            with self._lock:
                self._state["status"] = "done"
                self._state["finished_at"] = time.time()
            self._save()
            invalidate_cache()
            self._log("离线运行时导入完成，可以开始本地出片了")

        except Cancelled:
            with self._lock:
                self._state["status"] = "cancelled"
                self._state["finished_at"] = time.time()
            self._save()
            self._log("导入已取消")
        except Exception as e:
            with self._lock:
                self._state["status"] = "failed"
                self._state["error"] = str(e)
                self._state["finished_at"] = time.time()
            self._save()
            self._log(f"导入失败：{e}")


# ---------------------------------------------------------------- 辅助
def _dir_size(p: Path) -> int:
    total = 0
    if not p.exists():
        return 0
    for root, _d, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _has_package(venv_py: Path, pkg: str) -> bool:
    if not venv_py.exists():
        return False

    def probe() -> bool:
        try:
            r = subprocess.run([str(venv_py), "-c", f"import {pkg}"],
                               capture_output=True, timeout=60,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return r.returncode == 0
        except Exception:
            return False

    # import torch 可能要跑十几秒，缓存 5 分钟
    return _cached(f"pkg:{pkg}:{venv_py}", 300.0, probe)


# ---------------------------------------------------------------- TTL 缓存
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = threading.Lock()


def _cached(key: str, ttl: float, fn):
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = fn()
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), value)
    return value


def invalidate_cache() -> None:
    """部署/导入完成后调用，让下次 status() 重新探测。"""
    with _CACHE_LOCK:
        _CACHE.clear()


def _model_ready(models_dir: Path) -> bool:
    """H3 权重是否就位。

    判据：ComfyUI 的 models/diffusion_models 下有一个 >1GB 的 safetensors。
    为什么不看总目录体积：ComfyUI 的 models/ 里还有它自带的其它模型，
    算总量会把「别人的文件」算成自己的进度。
    """
    dm = models_dir / "diffusion_models"
    if not dm.exists():
        return False
    for f in dm.glob("*.safetensors"):
        try:
            if f.stat().st_size > 1024 ** 3:
                return True
        except OSError:
            continue
    return False


def _comfy_alive(url: str) -> bool:
    import urllib.request

    def probe() -> bool:
        try:
            with urllib.request.urlopen(url + "/system_stats", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    # 前端 2 秒一刷，这里缓存 5 秒，别把 ComfyUI 打爆
    return _cached(f"comfy:{url}", 5.0, probe)


_INSTALLER: Installer | None = None


def _offline_readme(size_gb: float) -> str:
    return f"""AIVerse 离线推理运行时（{size_gb} GB）
==================================================

这个文件夹是「AI 漫剧一键生产客户端」的本地推理运行时，
已经包含：Python 隔离环境、PyTorch+CUDA、ComfyUI、MiniMax H3 权重、FFmpeg。

在另一台机器上怎么用
--------------------
1. 安装 AI Studio 客户端（AIVerse-Setup.exe），随便装到哪都行；
2. 打开客户端 → 左侧「⚡ 环境部署」→ 找到「离线包导入」；
3. 把下面这个路径粘进去，点「导入」：

   {RUNTIME_DIR.parent}

   注意：上面是本机路径，在目标机器上请填「你拷贝过去的这个文件夹的路径」，
   例如 D:\\AIVerse-Runtime

4. 等待复制完成（几分钟，取决于硬盘速度），完成后会自动注册 H3 Provider；
5. 回到「环境部署」页点「🩺 检测 H3 环境」，显示「就绪」即可开始出片。

注意事项
--------
* 全程不需要联网，也不会重复下载任何东西。
* 目标机器仍需有 NVIDIA 显卡（8GB 显存起步，12GB 更舒适，24GB 随便跑）。
* 如果显卡驱动版本低于 550，请先升级驱动，否则 CUDA 跑不起来。
* 想重新导出：在已部署好的机器上点「导出离线包」，指定一个目录即可。

—— 由 AI Studio / AIVerse 自动生成
"""


def installer() -> Installer:
    global _INSTALLER
    if _INSTALLER is None:
        _INSTALLER = Installer()
    return _INSTALLER
