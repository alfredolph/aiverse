"""断点续传下载器。

特性：
  * HTTP Range 断点续传（.part 临时文件 + 校验通过后才改名）
  * 多镜像自动回退
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
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

Progress = Callable[[dict], None]

CHUNK = 1024 * 256


class Cancelled(Exception):
    pass


class IncompleteDownload(RuntimeError):
    """下载字节数与远端声明不符 —— 保留 .part，换镜像或稍后续传。"""


class CorruptArchive(RuntimeError):
    """压缩包损坏（常见于续传到了垃圾数据），需要清缓存重下。"""


class Downloader:
    def __init__(self, progress: Progress | None = None,
                 is_cancelled: Callable[[], bool] | None = None):
        self.progress = progress or (lambda d: None)
        self.is_cancelled = is_cancelled or (lambda: False)

    # ------------------------------------------------------------ HTTP
    def fetch(self, urls: list[str], dest: Path, label: str = "",
              expected_gb: float = 0.0) -> Path:
        """依次尝试多个镜像地址，支持断点续传。"""
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")
        last_err: Exception | None = None

        for url in urls:
            try:
                self._fetch_one(url, part, dest, label or dest.name, expected_gb)
                return dest
            except Cancelled:
                raise
            except Exception as e:
                last_err = e
                self.progress({"phase": "retry", "message": f"镜像失败，切换下一个：{e}"})
                continue
        raise RuntimeError(f"全部镜像下载失败：{last_err}")

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
            resp = urllib.request.urlopen(req, timeout=30)
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
        with open(part, mode) as f, resp:
            while True:
                if self.is_cancelled():
                    raise Cancelled()
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                have += len(chunk)
                dt = max(0.001, time.time() - t0)
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
                            subdir: str = "", venv_python: Path | None = None,
                            expected_gb: float = 0.0) -> Path:
        """调用 modelscope / huggingface_hub CLI 下载整个仓库（自带续传与进度）。"""
        target.mkdir(parents=True, exist_ok=True)
        py = str(venv_python or "python")

        if backend == "modelscope":
            code = (
                "import sys;from modelscope import snapshot_download as d;"
                f"d('{repo}', local_dir=r'{target}', allow_patterns=None);"
                "print('OK')"
            )
        else:
            code = (
                "from huggingface_hub import snapshot_download as d;"
                f"d(repo_id='{repo}', local_dir=r'{target}', max_workers=4);"
                "print('OK')"
            )

        self.progress({"phase": "download", "label": f"模型 {repo}",
                       "percent": 0.0, "message": f"正在从 {backend} 拉取 {repo}（大文件，请耐心等待）…"})

        proc = subprocess.Popen(
            [py, "-c", code], cwd=str(target), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="ignore",
            bufsize=1,
        )
        t0 = time.time()
        for line in proc.stdout:               # type: ignore[union-attr]
            if self.is_cancelled():
                proc.kill()
                raise Cancelled()
            line = line.strip()
            if not line:
                continue
            # 把 CLI 的百分比行转成统一进度
            pct = _parse_percent(line)
            if pct is not None:
                self.progress({"phase": "download", "label": f"模型 {repo}",
                               "percent": pct, "message": line[:120]})
            elif "%" not in line:
                self.progress({"phase": "download", "label": f"模型 {repo}",
                               "percent": 0.0, "message": line[:120]})
            # 兜底：估算体积进度
            elif expected_gb:
                got = _dir_size(target) / (expected_gb * 1024 ** 3) * 100
                self.progress({"phase": "download", "label": f"模型 {repo}",
                               "percent": round(min(got, 99.0), 2),
                               "message": line[:120]})
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"模型下载失败（退出码 {proc.returncode}）")

        self.progress({"phase": "done", "label": f"模型 {repo}", "percent": 100.0,
                       "message": f"{repo} 下载完成，耗时 {int(time.time() - t0)}s"})
        return target


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
