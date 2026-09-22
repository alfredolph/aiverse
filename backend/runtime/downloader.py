"""断点续传下载器。

特性：
  * HTTP Range 断点续传（.part 临时文件 + 校验通过后才改名）
  * 多镜像自动回退 —— 连不上要换，**连得上但被限速到十几 KB/s 也要换**
  * 启动前按实测速度给候选源排序
  * 实时进度回调（已下载 / 总大小 / 速度 / 剩余时间）
  * 支持取消
  * 模型仓库下载：优先调用 modelscope / huggingface_hub CLI，缺失时回退 HTTP 直链

**完整性校验（别删）**：续传最大的坑是「.part 其实是垃圾，但大小看着对」——
比如上次下到一半的文件被别的东西覆盖、或者远端 `latest` 已经换了个版本，
这时接着下会得到一个体积正常、内容全坏的文件，而 26 GB 的模型下载
等到解压/加载时才报错，用户已经白等几小时。

所以这里做了三道防线：
  1. `.part.meta` 记下「来源 URL + 远端总大小」，续传前比对，对不上就丢弃重下
  2. 下完先比对 `have == total`，不足就**不改名**，保留 .part 供下次续传
  3. `unzip()` 对坏压缩包抛明确错误；上层 `installer` 会清掉缓存重下一次

**为什么要有「慢也算失败」（别删）**：2026-09 实测，ghproxy.net / gh-proxy.com /
github.com 三个源都连得上、也都能返回 206，但全被限速到 12~15 KB/s。
uv 才 17 MB，跑了两分半只下到 2 MB，进度条停在 11% 再也不动 ——
用户看到的现象是「点了『开始一键部署』没反应」，而不是报错。
所以只判断「请求是否成功」是不够的：必须拿**实测吞吐**当判据，
不达标的源直接放弃换下一个，否则 43 GB 的权重能下到天荒地老。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

Progress = Callable[[dict], None]

CHUNK = 1024 * 256

# ---------------------------------------------------------------- 网速判据
# 单位都是字节/秒。96 KB/s 是个刻意压低的值：正常家用宽带下任何一个
# 真实可用的源都能轻松超过它，只有「被限速 / 被 QoS / 源站半死」才会掉到下面。
MIN_SPEED_BPS = 96 * 1024
SPEED_WINDOW = 12.0      # 观察窗口：窗口内平均速度不达标就放弃这个源
READ_TIMEOUT = 15.0      # 单次 socket 读超时（彻底不吐数据时的兜底）
PROBE_BYTES = 768 * 1024
PROBE_BUDGET = 6.0       # 单个源测速最长花多久
PROBE_TTL = 600.0        # 同一域名的测速结果缓存 10 分钟


class Cancelled(Exception):
    pass


class IncompleteDownload(RuntimeError):
    """下载字节数与远端声明不符 —— 保留 .part，换镜像或稍后续传。"""


class CorruptArchive(RuntimeError):
    """压缩包损坏（常见于续传到了垃圾数据），需要清缓存重下。"""


class SlowMirror(RuntimeError):
    """连得上、不报错，但吞吐低到不可用 —— 当成失败处理，换下一个源。"""


class Downloader:
    def __init__(self, progress: Progress | None = None,
                 is_cancelled: Callable[[], bool] | None = None):
        self.progress = progress or (lambda d: None)
        self.is_cancelled = is_cancelled or (lambda: False)

    # ------------------------------------------------------------ HTTP
    def rank_mirrors(self, urls: list[str]) -> list[str]:
        """按**实测速度**给候选源排序，快在前；完全连不上的丢掉。

        为什么不是「按配置顺序试」：配置里排第一的往往是国内加速镜像，
        它可能正在被限速。挨个试到第三个源要浪费几十秒到几分钟，
        而先花几秒测一遍，之后每个组件都直接命中快的那个。
        测速结果按域名缓存 10 分钟，所以整场部署其实只测了一轮。
        """
        if len(urls) < 2:
            return list(urls)

        scored: list[tuple[float, int, str]] = []
        for i, url in enumerate(urls):
            host = _host_of(url)
            cached = _host_speed_get(host)
            if cached is None:
                try:
                    speed = probe_speed(url, self.is_cancelled)
                except Cancelled:
                    raise
                _host_speed_put(host, speed)
                self.progress({"phase": "probe",
                               "message": f"测速 {host}："
                                          f"{_speed_text(speed)}"})
            else:
                speed = cached
            # 连不上的源（0）沉到最后；同速时保持原顺序，结果可复现
            scored.append((0.0 if speed <= 0 else speed, -i, url))

        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        ranked = [u for _s, _i, u in scored]
        if ranked != list(urls):
            self.progress({"phase": "probe",
                           "message": "已按实测速度排序镜像："
                                      + " > ".join(_host_of(u) for u in ranked)})
        return ranked

    def fetch(self, urls: list[str], dest: Path, label: str = "",
              expected_gb: float = 0.0) -> Path:
        """依次尝试多个镜像地址，支持断点续传。"""
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")
        errors: list[str] = []

        for url in self.rank_mirrors(urls):
            try:
                self._fetch_one(url, part, dest, label or dest.name, expected_gb)
                return dest
            except Cancelled:
                raise
            except Exception as e:
                errors.append(f"{_host_of(url)}：{e}")
                self.progress({"phase": "retry",
                               "message": f"镜像失败，切换下一个：{e}"})
                continue

        # 全都失败时把每个源各自的死因摊开 —— 只说「全部镜像下载失败」
        # 会让人以为是自己网络断了，而真实原因往往是「三个源都被限速」。
        if errors and all("太慢" in e for e in errors):
            raise RuntimeError(
                "所有镜像都太慢（低于 %.0f KB/s），已逐个放弃：\n  "
                % (MIN_SPEED_BPS / 1024) + "\n  ".join(errors)
                + "\n\n这通常不是你的网络断了，而是这些加速源当前被限速。"
                  "可以试试：① 换个镜像源（设置里切「海外直连」）；"
                  "② 用离线包导入（在别的机器上部署好，拷 U 盘过来）。"
            )
        raise RuntimeError("全部镜像下载失败：\n  " + "\n  ".join(errors))

    def _fetch_one(self, url: str, part: Path, dest: Path, label: str,
                   expected_gb: float) -> None:
        meta_path = part.with_suffix(part.suffix + ".meta")
        have = part.stat().st_size if part.exists() else 0
        prev_meta = _read_meta(meta_path)

        # 有 .part 但没有配套 .meta —— 这段缓存来路不明（旧版本残留、被别的程序写过、
        # 或者干脆是垃圾），续传上去只会得到一个体积正常但内容全坏的文件。
        # 宁可从零重下，也不要让用户拿到坏安装。
        if have and not prev_meta.get("total"):
            self.progress({"phase": "retry",
                           "message": f"{label}：发现无记录的断点缓存 {human_size(have)}，"
                                      f"为保证完整性，重新下载"})
            part.unlink(missing_ok=True)
            have = 0

        req = urllib.request.Request(url, headers={"User-Agent": "AIVerse/1.0"})
        if have:
            req.add_header("Range", f"bytes={have}-")

        try:
            resp = urllib.request.urlopen(req, timeout=READ_TIMEOUT)
        except urllib.error.HTTPError as e:
            if e.code == 416:                      # 已下完
                total = _read_meta(meta_path).get("total") or 0
                if total and part.stat().st_size != total:
                    part.unlink(missing_ok=True)
                    meta_path.unlink(missing_ok=True)
                    raise IncompleteDownload(
                        f"缓存文件大小 {part.stat().st_size} 与远端 {total} 不符，已丢弃")
                part.replace(dest)
                meta_path.unlink(missing_ok=True)
                return
            raise

        total = 0
        if have and resp.status == 206:
            cr = resp.headers.get("Content-Range", "")
            if "/" in cr:
                try:
                    total = int(cr.split("/")[-1])
                except ValueError:
                    total = 0
            # 远端换了文件（例如 latest 指向了新版本）：本地这段 .part 作废
            prev = prev_meta.get("total") or 0
            if prev and total and prev != total:
                resp.close()
                part.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                self.progress({"phase": "retry",
                               "message": f"{label}：远端文件已更新（{prev} → {total}），重新下载"})
                raise IncompleteDownload("远端文件已更新，需重新下载")
        else:
            have = 0
            total = int(resp.headers.get("Content-Length") or 0)
        if not total and expected_gb:
            total = int(expected_gb * 1024 ** 3)

        if total:
            _write_meta(meta_path, url, total)

        mode = "ab" if have else "wb"
        t0 = time.time()
        base_have = have
        # 观察窗口的起点：每过一个 SPEED_WINDOW 就结算一次平均速度。
        # 不能用「从 t0 到现在的总平均」——那样前面跑得快、后面被限速时
        # 总平均还很好看，卡死就检测不出来。
        win_t0 = time.time()
        win_have = have
        with open(part, mode) as f, resp:
            while True:
                if self.is_cancelled():
                    raise Cancelled()
                chunk = resp.read(CHUNK)
                now = time.time()
                if not chunk:
                    break
                f.write(chunk)
                have += len(chunk)

                win_dt = now - win_t0
                if win_dt >= SPEED_WINDOW:
                    win_speed = (have - win_have) / win_dt
                    if win_speed < MIN_SPEED_BPS:
                        raise SlowMirror(
                            f"{_host_of(url)} 太慢：{_speed_text(win_speed)}"
                            f"（低于 {MIN_SPEED_BPS / 1024:.0f} KB/s），放弃换源")
                    win_t0, win_have = now, have

                dt = max(0.001, now - t0)
                speed = (have - base_have) / dt
                self.progress({
                    "phase": "download",
                    "label": label,
                    "downloaded": have,
                    "total": total,
                    "percent": round(have / total * 100, 2) if total else 0.0,
                    "speed_mbps": round(speed / 1024 / 1024, 2),
                    "eta_seconds": int((total - have) / speed) if speed > 0 and total else 0,
                    "message": f"{label}  {have / 1024**2:.0f}/{total / 1024**2:.0f} MB"
                               f"  {speed / 1024**2:.1f} MB/s",
                })

        # 关键：字节数对不上就不改名，把 .part 留着下次续传
        if total and have != total:
            raise IncompleteDownload(
                f"{label} 下载不完整：{have}/{total} 字节（已保留断点，可继续）")

        part.replace(dest)
        meta_path.unlink(missing_ok=True)
        self.progress({"phase": "done", "label": label, "percent": 100.0,
                       "message": f"{label} 下载完成（{have / 1024**2:.0f} MB）"})

    # ------------------------------------------------------------ 解压
    def unzip(self, archive: Path, target: Path, strip_root: bool = True) -> Path:
        target.mkdir(parents=True, exist_ok=True)
        self.progress({"phase": "extract", "message": f"解压 {archive.name}…"})
        try:
            self._unzip_inner(archive, target, strip_root)
        except zipfile.BadZipFile as e:
            # 续传到了垃圾数据、或下载中途被截断，都会走到这里
            raise CorruptArchive(f"{archive.name} 压缩包损坏（{e}）") from e
        self.progress({"phase": "done", "message": f"{archive.name} 解压完成"})
        return target

    @staticmethod
    def _unzip_inner(archive: Path, target: Path, strip_root: bool) -> None:
        with zipfile.ZipFile(archive) as z:
            names = z.namelist()
            root = ""
            if strip_root and names:
                first = names[0].split("/")[0]
                if first and all(n.startswith(first + "/") or n == first for n in names):
                    root = first + "/"
            for member in names:
                if member.endswith("/"):
                    continue
                rel = member[len(root):] if root and member.startswith(root) else member
                if not rel:
                    continue
                out = target / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                with z.open(member) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    # ------------------------------------------------------------ 模型仓库
    def download_model_repo(self, repo: str, target: Path, backend: str = "modelscope",
                            files: list[str] | None = None,
                            venv_python: Path | None = None,
                            expected_gb: float = 0.0) -> Path:
        """从 modelscope / huggingface_hub 拉取指定文件（自带续传）。

        **必须传 files**。早先这里有个 `subdir` 参数，收下了却从没用过，
        结果用户选「精简版 39 GB」，实际会把整个仓库（原始 H3 仓库 354 GB）拖下来 ——
        这种错最坑：进度条一路走，用户以为在按计划下。

        files 是仓库内的相对路径（形如 `diffusion_models/xxx.safetensors`），
        而 ComfyUI 的 models/ 目录结构与之一一对应，所以 local_dir 直接指到
        `comfyui/models`，文件就会落到 ComfyUI 期望的位置。
        """
        target.mkdir(parents=True, exist_ok=True)
        py = str(venv_python or "python")
        patterns = list(files or [])
        if not patterns:
            raise RuntimeError("未指定要下载的模型文件（拒绝整仓库下载）")

        if backend == "modelscope":
            # modelscope 的 allow_patterns 参数名在不同版本里叫法不同
            # （allow_patterns / allow_file_pattern），所以两种都试一次。
            code = (
                "from modelscope import snapshot_download as d\n"
                f"kw = dict(local_dir=r'{target}')\n"
                f"try:\n"
                f"    d(r'{repo}', allow_patterns={patterns!r}, **kw)\n"
                f"except TypeError:\n"
                f"    d(r'{repo}', allow_file_pattern={patterns!r}, **kw)\n"
                "print('OK')\n"
            )
        else:
            code = (
                "from huggingface_hub import snapshot_download as d\n"
                f"d(repo_id=r'{repo}', local_dir=r'{target}', "
                f"allow_patterns={patterns!r}, max_workers=4)\n"
                "print('OK')\n"
            )

        total_bytes = int(expected_gb * 1024 ** 3)
        self.progress({"phase": "download", "label": f"模型 {repo}",
                       "percent": 0.0,
                       "message": f"正在从 {backend} 拉取 {len(patterns)} 个文件"
                                  f"（约 {expected_gb:.1f} GB，请耐心等待）…"})

        # 目录体积轮询：modelscope / hf 的 tqdm 进度条是 \r 刷新的，
        # 按行读根本读不到百分比。所以自己盯着目录长多大，进度才真的会动。
        stop_poll = threading.Event()

        def poll() -> None:
            while not stop_poll.wait(3.0):
                got = _dir_size(target)
                pct = round(min(got / total_bytes * 100, 99.0), 2) if total_bytes else 0.0
                self.progress({"phase": "download", "label": f"模型 {repo}",
                               "percent": pct,
                               "message": f"已下载 {human_size(got)} / "
                                          f"{expected_gb:.1f} GB"})

        poller = threading.Thread(target=poll, name="aiverse-model-progress", daemon=True)
        poller.start()

        proc = subprocess.Popen(
            [py, "-c", code], cwd=str(target), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="ignore",
            bufsize=1,
        )
        t0 = time.time()
        tail: list[str] = []
        try:
            for line in proc.stdout:               # type: ignore[union-attr]
                if self.is_cancelled():
                    proc.kill()
                    raise Cancelled()
                line = line.strip()
                if not line:
                    continue
                # 留最后几行，出错时好告诉用户到底哪一步炸了
                tail.append(line[:200])
                tail[:] = tail[-8:]
                pct = _parse_percent(line)
                if pct is not None:
                    self.progress({"phase": "download", "label": f"模型 {repo}",
                                   "percent": pct, "message": line[:120]})
                elif "%" not in line:
                    self.progress({"phase": "download", "label": f"模型 {repo}",
                                   "percent": 0.0, "message": line[:120]})
            proc.wait()
        finally:
            stop_poll.set()

        if proc.returncode != 0:
            raise RuntimeError(
                f"模型下载失败（退出码 {proc.returncode}）："
                + (" / ".join(tail[-3:]) or "无输出")
            )

        got = _dir_size(target)
        if total_bytes and got < total_bytes * 0.9:
            # 退出码是 0 但体积明显不够 —— 常见于仓库文件被改名 / 网络中间截断
            raise RuntimeError(
                f"模型文件不完整：只下到 {human_size(got)}，"
                f"预期约 {expected_gb:.1f} GB。请检查仓库 {repo} 是否仍有这些文件，"
                f"或换镜像源后重试（已下载的部分会续传）"
            )

        self.progress({"phase": "done", "label": f"模型 {repo}", "percent": 100.0,
                       "message": f"{repo} 下载完成（{human_size(got)}），"
                                  f"耗时 {int(time.time() - t0)}s"})
        return target


# ---------------------------------------------------------------- 测速
def _host_of(url: str) -> str:
    """取域名 —— 限速是**按域名**发生的，所以测速结果也按域名缓存。"""
    parts = url.split("/")
    return parts[2] if len(parts) > 2 and parts[2] else url


def _speed_text(bps: float) -> str:
    if bps <= 0:
        return "连不上"
    if bps >= 1024 * 1024:
        return f"{bps / 1024 / 1024:.1f} MB/s"
    return f"{bps / 1024:.0f} KB/s"


def probe_speed(url: str, is_cancelled: Callable[[], bool] | None = None,
                nbytes: int = PROBE_BYTES, budget: float = PROBE_BUDGET) -> float:
    """实测一个地址的下载速度（字节/秒）。连不上或超时返回 0。

    只读前 768 KB 就下结论：真正的瓶颈（限速 / 半死源）在头几百 KB 就能看出来，
    而为了测速去下几十 MB 反而是在浪费用户的时间。
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": "AIVerse/1.0",
        "Range": f"bytes=0-{nbytes - 1}",
    })
    t0 = time.time()
    got = 0
    try:
        with urllib.request.urlopen(req, timeout=READ_TIMEOUT) as r:
            while got < nbytes:
                if is_cancelled and is_cancelled():
                    raise Cancelled()
                if time.time() - t0 > budget:
                    break
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                got += len(chunk)
    except Cancelled:
        raise
    except Exception:
        return 0.0
    dt = time.time() - t0
    return got / dt if dt > 0 else 0.0


_HOST_SPEED: dict[str, tuple[float, float]] = {}
_HOST_LOCK = threading.Lock()


def _host_speed_get(host: str) -> float | None:
    with _HOST_LOCK:
        hit = _HOST_SPEED.get(host)
    if hit and time.time() - hit[0] < PROBE_TTL:
        return hit[1]
    return None


def _host_speed_put(host: str, speed: float) -> None:
    with _HOST_LOCK:
        _HOST_SPEED[host] = (time.time(), speed)


def _write_meta(meta_path: Path, url: str, total: int) -> None:
    """记录 .part 的来源与远端总大小，续传前用它判断「这段缓存还作不作数」。"""
    try:
        meta_path.write_text(json.dumps({"url": url, "total": total}),
                             encoding="utf-8")
    except OSError:
        pass


def _read_meta(meta_path: Path) -> dict:
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse_percent(line: str) -> float | None:
    import re
    m = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", line)
    if m:
        try:
            return min(100.0, float(m.group(1)))
        except ValueError:
            return None
    return None


def _dir_size(p: Path) -> int:
    total = 0
    if not p.exists():
        return 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
