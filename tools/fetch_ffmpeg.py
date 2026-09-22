"""构建期抓取 FFmpeg，放进 assets/ffmpeg/bin/，供打包时打进去。

为什么要有这一步（而不是让用户走「一键部署」去下）：
    FFmpeg 是导出成片（concat + scale/pad + 烧字幕）的**唯一**硬依赖，
    跟有没有 NVIDIA 显卡毫无关系。而「一键部署」的主体是 39 GB 的 H3 权重，
    为了烧个字幕让用户先等几个小时，说不通。所以从 v1.0.6 起随程序自带。

抓的是 GyanD 的 essentials_build：只带常用编解码器（含 libx264 / aac / libass），
体积比 full_build 小一个数量级，够用且是官方推荐的默认档。

用法：
    python tools/fetch_ffmpeg.py                # 缺了才下，下了就跳过
    python tools/fetch_ffmpeg.py --force        # 强制重下
    python tools/fetch_ffmpeg.py --mirror global

产物（会被 aiverse.spec 与 installer/aiverse.iss 打包）：
    assets/ffmpeg/bin/ffmpeg.exe
    assets/ffmpeg/bin/ffprobe.exe
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.runtime import catalog                        # noqa: E402
from backend.runtime.downloader import Downloader          # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "assets" / "ffmpeg" / "bin"
WANT = ("ffmpeg.exe", "ffprobe.exe")
MIN_BYTES = 30 * 1024 * 1024      # 小于 30 MB 说明抓到的是个错误页 / 空壳


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="已存在也重新下载")
    ap.add_argument("--mirror", default="cn", choices=sorted(catalog.MIRRORS))
    args = ap.parse_args()

    DEST.mkdir(parents=True, exist_ok=True)

    if not args.force:
        have = [(DEST / n) for n in WANT]
        if all(p.exists() and p.stat().st_size >= MIN_BYTES for p in have):
            print("✓ FFmpeg 已就位，跳过下载")
            for p in have:
                print(f"    {p.relative_to(ROOT)}  {p.stat().st_size / 1024 ** 2:.1f} MB")
            return 0

    urls = catalog.component_urls("ffmpeg", args.mirror)
    print("下载源：")
    for u in urls:
        print("  " + u.split("/")[2])

    def on_progress(d: dict) -> None:
        msg = d.get("message")
        if msg:
            print(f"  · {msg}", flush=True)

    dl = Downloader(progress=on_progress)
    with tempfile.TemporaryDirectory(prefix="aiverse-ffmpeg-") as td:
        tmp = Path(td)
        archive = tmp / "ffmpeg.zip"
        dl.fetch(urls, archive, label="FFmpeg 7.1", expected_gb=0.09)
        print(f"  下载完成 {archive.stat().st_size / 1024 ** 2:.1f} MB，解压中…")
        dl.unzip(archive, tmp / "unzipped")

        # essentials_build 的 zip 里是 bin/ffmpeg.exe、bin/ffprobe.exe、bin/ffplay.exe。
        # 我们只要前两个：ffplay 是播放器，程序里用不到，白占 80 MB。
        found: dict[str, Path] = {}
        for name in WANT:
            hit = next((tmp / "unzipped").rglob(name), None)
            if not hit:
                print(f"✗ 压缩包里没有 {name}")
                return 1
            found[name] = hit

        for name, src in found.items():
            dst = DEST / name
            shutil.copy2(src, dst)
            size = dst.stat().st_size
            print(f"✓ {name}  {size / 1024 ** 2:.1f} MB")
            if size < MIN_BYTES:
                print(f"✗ {name} 只有 {size} 字节，像是抓错了东西")
                return 1

    print(f"\n✓ 已写入 {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
