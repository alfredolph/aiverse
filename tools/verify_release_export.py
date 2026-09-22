"""【发布后手动跑】从 Release 下载绿色版，让它自己产出一个真 MP4。

不适合放进 CI：它要下载的正是本次 CI 刚产出的 Release，先有鸡还是先有蛋。
发完版手工跑一次即可，用来回答「GitHub 上那个 exe 到底能不能出片」。

这是「发布产物」级别的验证：不是跑源码测试，而是拿 GitHub 上那个 exe，
通过它自己的 HTTP API 走一遍导出，最后用 ffprobe 校验产物。

流程：
  1. 下载 Release 里的 AIVerse.exe
  2. 用临时 AIVERSE_DATA / AIVERSE_RUNTIME 启动（不碰真实数据）
  3. 等首次运行的示例项目播种完成
  4. 停掉，用 ffmpeg 合成 2 段片段塞进该项目的 shots/，并把 shot 的 payload
     改成指向这两个文件（等价于「已经渲染好的镜头」）
  5. 重新启动，POST /api/projects/<pid>/export
  6. ffprobe 校验导出的 MP4
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG = "v1.0.5"
PORT = 8796
FFMPEG_KEEP = Path(r"C:\Users\Administrator\AppData\Local\Temp\av_ffmpeg_keep\ffmpeg\bin")

fail: list[str] = []


def need(cond, msg, label=""):
    print(("  ✓ " + (label or msg)) if cond else ("  ✗ " + msg))
    if not cond:
        fail.append(msg)


def api(path: str, payload: dict | None = None, timeout: int = 120):
    url = f"http://127.0.0.1:{PORT}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8")
    return json.loads(body) if body.strip() else {}


def wait_port(deadline_s: int = 40) -> bool:
    end = time.time() + deadline_s
    while time.time() < end:
        try:
            api("/api/health", timeout=3)
            return True
        except Exception:
            time.sleep(1)
    return False


def launch(exe: Path, env: dict):
    return subprocess.Popen([str(exe), "--no-open", str(PORT)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kill_tree(proc) -> None:
    """整棵进程树一起杀。

    PyInstaller 单文件 exe 会先起一个解包用的父进程，真正的服务跑在子进程里。
    只 `proc.kill()` 父进程的话，子进程还占着端口活着 —— 下次运行就会连到
    上一次的残留实例，拿到别的临时目录里的项目 id，然后一脸懵地报「找不到目录」。
    （这个坑真的踩到了，排查了好一会儿。）
    """
    if proc.poll() is None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True)
    try:
        proc.wait(timeout=30)
    except Exception:
        proc.kill()
    time.sleep(2)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="aiverse_release_"))
    data_dir = tmp / "data"
    data_dir.mkdir(parents=True)
    exe = tmp / "AIVerse.exe"

    print(f"\n临时目录：{tmp}")

    # ---------------------------------------------------------- 1. 下载
    print(f"\n[1/7] 从 Release {TAG} 下载 AIVerse.exe")
    r = subprocess.run(["gh", "release", "download", TAG, "--repo", "alfredolph/aiverse",
                        "--pattern", "AIVerse.exe", "--dir", str(tmp)],
                       capture_output=True, text=True, encoding="utf-8")
    need(r.returncode == 0 and exe.exists(),
         f"下载失败：{(r.stderr or '')[:200]}",
         f"下载完成 {exe.stat().st_size / 1024 / 1024:.1f} MB" if exe.exists() else "")

    env = dict(os.environ)
    env["AIVERSE_DATA"] = str(data_dir)
    env["AIVERSE_RUNTIME"] = str(FFMPEG_KEEP.parent.parent)
    env["PYTHONUTF8"] = "1"

    # ---------------------------------------------------------- 2. 首次启动
    print("\n[2/7] 首次启动（等示例项目自动播种）")
    proc = launch(exe, env)
    ok = wait_port()
    need(ok, "exe 启动后 API 没起来", "exe 已启动，API 就绪")
    if not ok:
        kill_tree(proc)
        return 1
    health = api("/api/health")
    need(health.get("version") == "1.0.5",
         f"版本应为 1.0.5，实际 {health.get('version')}",
         f"版本 {health.get('version')}")

    proj = None
    end = time.time() + 60
    while time.time() < end:
        ps = api("/api/projects").get("projects") or []
        if ps and ps[0].get("progress", {}).get("done") == ps[0].get("progress", {}).get("total"):
            proj = ps[0]
            break
        time.sleep(2)
    need(proj is not None, "示例项目没播种完成", "示例项目已播种完成")
    if not proj:
        kill_tree(proc)
        return 1
    pid = proj["id"]
    print(f"     项目 {proj['name']}（{pid}）· 阶段 {proj['progress']['done']}/8"
          f" · 画幅 {proj.get('aspect')}")

    # ---------------------------------------------------------- 3. 停掉
    print("\n[3/7] 停掉 exe，注入「已渲染镜头」")
    kill_tree(proc)

    base = next((p for p in data_dir.iterdir() if p.is_dir() and pid in p.name), None)
    need(base is not None, f"找不到项目目录（{data_dir}）", f"项目目录 {base.name if base else '-'}")
    if not base:
        return 1
    shots_dir = base / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------- 4. 合成镜头
    ffmpeg_exe = FFMPEG_KEEP / "ffmpeg.exe"
    clips = []
    for i, (name, src, freq) in enumerate(
            [("rel1", "testsrc2=size=448x832:rate=24:duration=1", "440"),
             ("rel2", "smptebars=size=448x832:rate=24:duration=1", "554")], start=1):
        out = shots_dir / f"{name}.mp4"
        r = subprocess.run(
            [str(ffmpeg_exe), "-y", "-f", "lavfi", "-i", src,
             "-f", "lavfi", "-i", f"sine=frequency={freq}:duration=1", "-shortest",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "96k", str(out)],
            capture_output=True, text=True, encoding="utf-8", errors="ignore")
        need(r.returncode == 0 and out.exists(),
             f"合成 {name}.mp4 失败：{(r.stderr or '')[-200:]}",
             f"{name}.mp4 已合成（{out.stat().st_size / 1024:.0f} KB）")
        clips.append(f"shots/{name}.mp4")

    # 字幕：走一遍真实字幕文件
    srt = base / "subtitles" / "subtitle.srt"
    srt.parent.mkdir(parents=True, exist_ok=True)
    srt.write_text("1\n00:00:00,000 --> 00:00:01,900\n药铺里的秘密\n\n", encoding="utf-8")

    # ---------------------------------------------------------- 5. 改 DB
    print("\n[4/7] 把前两个镜头的 payload 指向这两个文件")
    db_path = data_dir / "aiverse.db"
    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT no, payload FROM shots WHERE project_id=? ORDER BY no",
                       (pid,)).fetchall()
    need(len(rows) >= 2, f"镜头数不足：{len(rows)}", f"共 {len(rows)} 个镜头")
    for (no, payload), rel in zip(rows, clips):
        d = json.loads(payload or "{}")
        d.setdefault("video", {})["video"] = rel
        con.execute("UPDATE shots SET payload=? WHERE project_id=? AND no=?",
                    (json.dumps(d, ensure_ascii=False), pid, no))
        print(f"     镜头 {no} -> {rel}")
    con.commit()
    con.close()

    # ---------------------------------------------------------- 6. 重启 + 导出
    print("\n[5/7] 重新启动并调用导出接口")
    proc = launch(exe, env)
    ok = wait_port()
    need(ok, "重启后 API 没起来", "重启成功，API 就绪")
    if not ok:
        kill_tree(proc)
        return 1

    resp = api(f"/api/projects/{pid}/export",
               {"container": "MP4", "resolution": "1080p", "fps": 24}, timeout=600)
    # 接口返回 {"ok": true, "plan": {...}}，渲染结果在 plan 里
    res = resp.get("plan") or {}
    print(f"     message: {res.get('message')}")
    need(res.get("rendered") is True,
         f"导出应成功，实际 rendered={res.get('rendered')} message={res.get('message')}",
         f"导出成功：{res.get('output')}（{res.get('output_size_human')}）")
    out_file = base / (res.get("output") or "nope")
    need(out_file.exists() and out_file.stat().st_size > 1024,
         f"产物不存在：{out_file}",
         f"产物 {out_file.name}，{out_file.stat().st_size / 1024:.0f} KB"
         if out_file.exists() else "")

    # ---------------------------------------------------------- 7. ffprobe
    print("\n[6/7] ffprobe 校验产物")
    if out_file.exists():
        probe = FFMPEG_KEEP / "ffprobe.exe"
        r = subprocess.run([str(probe), "-v", "error", "-print_format", "json",
                            "-show_format", "-show_streams", str(out_file)],
                           capture_output=True, text=True, timeout=120,
                           encoding="utf-8", errors="ignore")
        meta = json.loads(r.stdout or "{}")
        streams = meta.get("streams", [])
        kinds = {s.get("codec_type") for s in streams}
        v = next((s for s in streams if s.get("codec_type") == "video"), {})
        dur = float(meta.get("format", {}).get("duration") or 0)
        need("video" in kinds and "audio" in kinds,
             f"应有音视频轨，实际 {kinds}", f"音视频轨齐全 {sorted(kinds)}")
        need((v.get("width"), v.get("height")) == (1080, 1920),
             f"应为 1080x1920，实际 {v.get('width')}x{v.get('height')}",
             f"分辨率 {v.get('width')}x{v.get('height')}（9:16 竖屏）")
        need(1.6 <= dur <= 2.6, f"时长应约 2 秒，实际 {dur:.2f}s",
             f"时长 {dur:.2f}s（2 段各 1 秒）")
        need(v.get("codec_name") == "h264",
             f"编码应为 h264，实际 {v.get('codec_name')}",
             f"编码 {v.get('codec_name')} / {v.get('pix_fmt')}")

    # ---------------------------------------------------------- 收尾
    print("\n[7/7] 收尾")
    kill_tree(proc)
    need(True, "", "exe 已停止，临时目录已清理")

    print("\n" + "─" * 60)
    if fail:
        print(f"✗ {len(fail)} 项未通过：")
        for f in fail:
            print("   · " + f)
        shutil.rmtree(tmp, ignore_errors=True)
        return 1
    print("✓ Release 里的 v1.0.5 绿色版，真的导出了可播放的 MP4")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
