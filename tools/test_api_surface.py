"""把整个 HTTP API 面跑一遍，确认 README 里「已实现能力对照」那张表不是空话。

为什么需要它：前面几轮反复证明了一件事 —— **从没被执行过的代码路径里藏着 bug**
（下载器把坏文件当成功、pad 滤镜参数写错、卸载残留……）。而 59 个接口里，
前端可能只用到其中一部分，剩下的没人点过就没人知道它坏没坏。

这个测试把 `backend.app.ROUTES` 里注册的每一个接口都真调一遍：
    * 5xx 一律算失败（接口内部异常会被兜成 500 并带 trace）
    * 最后报「覆盖了几个 / 漏了哪几个」，漏掉必须写明理由
    * 再加 5 组行为断言 —— 光看状态码不够：59 个接口全返 200 的那一轮里，
      角色实体其实一条都没建出来，队列暂停也只是回了个 200 而已。

用法：
    python tools/test_api_surface.py

脚本会起一个临时 AIVERSE_DATA / AIVERSE_RUNTIME 的实例，不碰你的真实数据。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MARKER = "--in-child"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------------------------------ 调用表
# 键是 ROUTES 里的 pattern，值是 (补充路径参数, 请求体)。
# 没有列在这里的 pattern 会被报成「未覆盖」，必须显式写进 SKIP 并说明原因。
def build_calls(pid: str, work: str, doomed: str, eid: str, tid: str,
                pvid: str = "pv_missing") -> dict:
    S = {"pid": pid, "eid": eid, "tid": tid, "pvid": pvid,
         "no": "1", "key": "script"}
    W = {"pid": work, "eid": eid, "tid": tid, "pvid": pvid,
         "no": "1", "key": "script"}
    D = {"pid": doomed, "eid": eid, "tid": tid, "pvid": pvid,
         "no": "1", "key": "script"}
    return {
        # ---- 基础
        ("GET", "/api/health"): (S, None),
        ("GET", "/api/meta"): (S, None),
        ("GET", "/api/gpu"): (S, None),
        # ---- 项目
        ("GET", "/api/projects"): (S, None),
        ("POST", "/api/projects"): ({}, {"name": "接口巡检 · 工作项目",
                                         "aspect": "9:16", "resolution": "1080p",
                                         "style": "guoman"}),
        ("GET", r"/api/projects/(?P<pid>[\w\-]+)"): (S, None),
        ("PATCH", r"/api/projects/(?P<pid>[\w\-]+)"): (W, {"name": "接口巡检 · 工作项目"}),
        ("DELETE", r"/api/projects/(?P<pid>[\w\-]+)"): (D, None),
        ("GET", r"/api/projects/(?P<pid>[\w\-]+)/files"): (S, None),
        ("GET", r"/api/projects/(?P<pid>[\w\-]+)/costs"): (S, None),
        # ---- 剧本
        ("GET", r"/api/projects/(?P<pid>[\w\-]+)/script"): (S, None),
        ("POST", r"/api/projects/(?P<pid>[\w\-]+)/script"): (
            W, {"script": "【场景 巡检室 夜】\n巡检员：接口都得能跑。\n"}),
        # ---- 阶段与审核门
        ("GET", r"/api/projects/(?P<pid>[\w\-]+)/stages"): (W, None),
        ("POST", r"/api/projects/(?P<pid>[\w\-]+)/stage/(?P<key>\w+)/run"): (W, {}),
        ("POST", r"/api/projects/(?P<pid>[\w\-]+)/stage/(?P<key>\w+)/approve"): (W, None),
        ("POST", r"/api/projects/(?P<pid>[\w\-]+)/stage/(?P<key>\w+)/reject"): (
            W, {"reason": "巡检：故意打回一次"}),
        ("POST", r"/api/projects/(?P<pid>[\w\-]+)/stage/(?P<key>\w+)/reopen"): (W, None),
        ("POST", r"/api/projects/(?P<pid>[\w\-]+)/stage/(?P<key>\w+)/approve_all"): (W, None),
        # ---- 抽卡
        ("GET", r"/api/projects/(?P<pid>[\w\-]+)/candidates"): (W, None),
        ("POST", r"/api/projects/(?P<pid>[\w\-]+)/gacha/draw"): (
            W, {"stage": "characters", "group": "巡检员", "n": 2}),
        ("POST", r"/api/projects/(?P<pid>[\w\-]+)/gacha/adopt"): (
            W, {"stage": "characters", "group": "巡检员", "candidate_id": "c_1"}),
        # ---- 实体
        ("GET", r"/api/projects/(?P<pid>[\w\-]+)/entities"): (W, None),
        ("PATCH", r"/api/projects/(?P<pid>[\w\-]+)/entities/(?P<eid>[\w\-]+)"): (
            W, {"note": "巡检改一笔"}),
        ("POST", r"/api/projects/(?P<pid>[\w\-]+)/entities/(?P<eid>[\w\-]+)/snapshot"): (W, None),
        # ---- 分镜
        ("GET", r"/api/projects/(?P<pid>[\w\-]+)/shots"): (S, None),
        ("POST", r"/api/projects/(?P<pid>[\w\-]+)/shots/(?P<no>\d+)/redraw"): (
            W, {"hint": "巡检：换个机位", "change": ["camera"]}),
        ("POST", r"/api/projects/(?P<pid>[\w\-]+)/shots/(?P<no>\d+)/adopt"): (
            W, {"candidate_id": "c_1"}),
        ("POST", r"/api/projects/(?P<pid>[\w\-]+)/shots/reorder"): (W, {"order": []}),
        # ---- 视频
        ("POST", r"/api/projects/(?P<pid>[\w\-]+)/video/generate"): (
            W, {"shots": [1], "resolution": "480p", "aspect": "9:16"}),
        ("POST", r"/api/projects/(?P<pid>[\w\-]+)/video/regenerate"): (
            W, {"no": 1, "resolution": "480p", "aspect": "9:16"}),
        ("GET", r"/api/projects/(?P<pid>[\w\-]+)/quality"): (S, None),
        # ---- 时间线与导出
        ("GET", r"/api/projects/(?P<pid>[\w\-]+)/timeline"): (S, None),
        ("POST", r"/api/projects/(?P<pid>[\w\-]+)/timeline"): (W, {"timeline": {}}),
        ("POST", r"/api/projects/(?P<pid>[\w\-]+)/export"): (
            S, {"container": "MP4", "resolution": "480p", "fps": 24}),
        # ---- 工作流与批量
        ("GET", r"/api/projects/(?P<pid>[\w\-]+)/workflow"): (S, None),
        ("POST", r"/api/projects/(?P<pid>[\w\-]+)/workflow/plan"): (
            S, {"request": "巡检：给我一条三分钟的竖屏短片流程"}),
        ("GET", r"/api/projects/(?P<pid>[\w\-]+)/batch"): (S, None),
        # ---- 任务队列
        ("GET", "/api/tasks"): (S, None),
        ("POST", r"/api/tasks/(?P<tid>[\w\-]+)/cancel"): (S, None),
        ("POST", r"/api/tasks/(?P<tid>[\w\-]+)/retry"): (S, None),
        ("POST", r"/api/tasks/(?P<tid>[\w\-]+)/bump"): (S, {"priority": 5}),
        ("POST", "/api/queue/pause"): (S, None),
        ("POST", "/api/queue/resume"): (S, None),
        # ---- Provider
        ("GET", "/api/providers"): (S, None),
        ("POST", "/api/providers"): (S, {"name": "巡检用 Provider", "type": "llm",
                                         "base_url": "http://127.0.0.1:9/v1",
                                         "api_key": "sk-test", "models": ["m"]}),
        ("PATCH", r"/api/providers/(?P<pid>[\w\-]+)"): (
            S, {"name": "巡检用 Provider（改名）", "enabled": 0}),
        ("DELETE", r"/api/providers/(?P<pid>[\w\-]+)"): (S, None),
        # ---- 运行时
        ("GET", "/api/runtime/status"): (S, None),
        ("GET", "/api/runtime/plan"): (S, None),
        # 用不存在的模型 key 逼它走「无 GPU + 指定了模型」的拒绝分支。
        # 参数名是 model 不是 model_key —— 写成 model_key 时路由读不到，
        # 守卫不生效，测试会真的去下几十 GB（踩过）。
        ("POST", "/api/runtime/install"): (S, {"mirror": "cn", "model": "no-such-model"}),
        ("POST", "/api/runtime/cancel"): (S, None),
        ("POST", "/api/runtime/retry"): (S, None),
        ("GET", "/api/runtime/h3"): (S, None),
        ("POST", "/api/runtime/h3/detect-nodes"): (S, None),
        ("POST", "/api/runtime/import/verify"): (S, {"source": "C:/no/such/pack"}),
        ("POST", "/api/runtime/import"): (S, {"source": "C:/no/such/pack"}),
        ("POST", "/api/runtime/export"): (S, {"dest": ""}),
        ("POST", "/api/runtime/comfy/start"): (S, None),
        ("POST", "/api/runtime/comfy/stop"): (S, None),
    }


# 明确不调的接口，以及为什么
SKIP: dict[tuple[str, str], str] = {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", default="", help=argparse.SUPPRESS)
    ap.add_argument("--data", default="", help=argparse.SUPPRESS)
    ap.add_argument(MARKER, dest="in_child", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if not args.in_child:
        tmp = Path(tempfile.mkdtemp(prefix="aiverse_api_"))
        rt, data = tmp / "runtime", tmp / "data"
        rt.mkdir(parents=True)
        data.mkdir(parents=True)
        env = dict(os.environ)
        env["AIVERSE_RUNTIME"] = str(rt)
        env["AIVERSE_DATA"] = str(data)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        print(f"\n临时目录：{tmp}")
        rc = __import__("subprocess").run(
            [sys.executable, "-u", str(Path(__file__).resolve()), MARKER,
             "--runtime", str(rt), "--data", str(data)], env=env).returncode
        shutil.rmtree(tmp, ignore_errors=True)
        return rc

    from backend.core.console import setup_console
    setup_console()
    from backend.app import ROUTES, serve

    fail: list[str] = []
    port = free_port()
    httpd = serve("127.0.0.1", port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"服务已起：http://127.0.0.1:{port}")

    def call(method: str, path: str, body: dict | None = None, timeout: int = 300):
        url = f"http://127.0.0.1:{port}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8")
                return r.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, raw

    def concrete(pattern: str, subs: dict) -> str:
        return re.sub(r"\(\?P<(\w+)>[^)]*\)", lambda m: str(subs[m.group(1)]), pattern)

    # ---------------------------------------------------------- 等示例项目
    print("\n[准备] 等首次运行的示例项目播种完成")
    demo = None
    end = time.time() + 90
    while time.time() < end:
        _, body = call("GET", "/api/projects")
        ps = (body or {}).get("projects") or []
        if ps and ps[0].get("progress", {}).get("done") == ps[0].get("progress", {}).get("total"):
            demo = ps[0]
            break
        time.sleep(2)
    if not demo:
        print("  ✗ 示例项目没播种完成，后面没法测")
        httpd.shutdown()
        return 1
    print(f"  ✓ 示例项目 {demo['name']}（{demo['id']}）· 8/8 阶段")

    # ---------------------------------------------------------- 造工作项目
    print("\n[准备] 建一个专门用来折腾的「工作项目」和「待删项目」")
    _, w = call("POST", "/api/projects",
                {"name": "接口巡检 · 工作项目", "aspect": "9:16",
                 "resolution": "480p", "style": "guoman"})
    work = w["project"]["id"]
    _, d = call("POST", "/api/projects",
                {"name": "接口巡检 · 待删", "aspect": "16:9", "resolution": "480p"})
    doomed = d["project"]["id"]
    print(f"  work={work}  doomed={doomed}")

    # 跑满阶段，好让后续接口有数据可用
    for key in ("script", "characters", "scenes", "storyboard"):
        call("POST", f"/api/projects/{work}/stage/{key}/run", {})
        call("POST", f"/api/projects/{work}/stage/{key}/approve", {})
    _, ents = call("GET", f"/api/projects/{work}/entities")
    ent_list = (ents or {}).get("entities") or []
    eid = ent_list[0]["id"] if ent_list else "e_missing"
    _, tk = call("GET", "/api/tasks")
    task_list = (tk or {}).get("tasks") or []
    tid = task_list[0]["id"] if task_list else "t_missing"
    print(f"  eid={eid}  tid={tid}")

    # 真建一个 Provider 再改名/删掉 —— 之前这里图省事拿项目 id 当 provider id 传，
    # PATCH 静默改了 0 行、DELETE 删了 0 行，两个接口等于没测。
    _, pv = call("POST", "/api/providers",
                 {"name": "接口巡检用 Provider", "type": "llm",
                  "base_url": "http://127.0.0.1:9/v1", "api_key": "sk-test",
                  "models": ["m"]})
    pvid = (pv or {}).get("id") or "pv_missing"
    print(f"  pvid={pvid}")

    # 本机有独显时，/api/runtime/install 即使给了不存在的模型 key 也会真的开跑，
    # 在 GPU 机器上跑这个脚本就会白下几十 GB。所以先探一下有没有 GPU。
    _, gi = call("GET", "/api/gpu")
    has_gpu = bool((gi or {}).get("available") or (gi or {}).get("devices"))

    # ---------------------------------------------------------- 逐条调
    print(f"\n[巡检] 逐个调用 {len(ROUTES)} 个接口")
    calls = build_calls(demo["id"], work, doomed, eid, tid, pvid)
    skip = dict(SKIP)
    if has_gpu:
        # 有独显时守卫不会拦住，真会开下 —— 别在巡检脚本里下 26 GB
        calls.pop(("POST", "/api/runtime/install"), None)
        skip[("POST", "/api/runtime/install")] = "本机有独显，调用会真的开始下载，改为单独测"
    by_key = {}
    for method, pattern, fname in ROUTES:
        by_key.setdefault((method, pattern), []).append(fname)

    covered: set[tuple[str, str]] = set()
    http_500: list[str] = []
    for (method, pattern), names in sorted(by_key.items(), key=lambda kv: kv[0][1]):
        fname = names[0]
        if (method, pattern) in skip:
            print(f"  –  {method:6} {pattern}  （跳过：{skip[(method, pattern)]}）")
            continue
        entry = calls.get((method, pattern))
        if entry is None:
            fail.append(f"没有为 {method} {pattern}（{fname}）准备调用参数")
            print(f"  ?  {method:6} {pattern}  ← 调用表里没有")
            continue
        subs, body = entry
        path = concrete(pattern, subs)
        t0 = time.time()
        try:
            status, resp = call(method, path, body)
        except Exception as e:
            status, resp = 0, {"error": f"{type(e).__name__}: {e}"}
        dt = time.time() - t0
        covered.add((method, pattern))
        if status >= 500:
            http_500.append(f"{method} {path} -> {status} {str(resp)[:300]}")
            print(f"  ✗  {method:6} {path}  {status}  ({dt:.1f}s)")
        elif status == 0:
            print(f"  ✗  {method:6} {path}  连接失败  ({dt:.1f}s)")
        else:
            print(f"  ✓  {method:6} {path}  {status}  ({dt:.1f}s)")

    # ---------------------------------------------------------- 行为断言
    # 只看 HTTP 状态码是不够的：上面那轮 59 个接口全返回 200 的时候，
    # 角色实体其实一条都没建出来。下面这几条是「结果对不对」。
    def check(cond: bool, ok_msg: str, bad_msg: str) -> None:
        print(("  ✓ " + ok_msg) if cond else ("  ✗ " + bad_msg))
        if not cond:
            fail.append(bad_msg)

    print("\n[断言 1/5] 返回体不是空壳，错误路径给的是人话不是 traceback")
    _, health = call("GET", "/api/health")
    check(health.get("version") == "1.0.3",
          "版本 1.0.3", f"/api/health 版本应为 1.0.3，实际 {health.get('version')}")
    _, shots_d = call("GET", f"/api/projects/{demo['id']}/shots")
    check(bool((shots_d or {}).get("shots")), "示例项目有分镜", "示例项目应有分镜")
    _, st = call("GET", f"/api/projects/{demo['id']}/stages")
    n_st = len((st or {}).get("stages") or [])
    check(n_st == 8, "8 个阶段齐全", f"应有 8 个阶段，实际 {n_st}")
    _, pl = call("GET", "/api/runtime/plan?mirror=cn")
    check(bool((pl or {}).get("plan", {}).get("steps")), "部署计划有步骤",
          "部署计划应有步骤")
    if not has_gpu:
        code, bad = call("POST", "/api/runtime/install",
                         {"mirror": "cn", "model": "no-such-model"})
        check(code == 400 and "没有这个模型版本" in str(bad.get("error", "")),
              f"写错模型版本 → {code}「{str(bad.get('error'))[:40]}…」",
              f"写错模型版本应回 400 + 可读提示，实际 {code} {str(bad)[:160]}")

    print("\n[断言 2/5] 角色 / 场景 / 道具真的被资产化了")
    # 这条是踩出来的：管线只抽卡不落实体，于是 8 阶段全绿、角色面板却是空的，
    # 分镜里的角色还会被质量检查报成「未资产化」。
    for kind, label in (("character", "角色"), ("scene", "场景"), ("prop", "道具")):
        _, r = call("GET", f"/api/projects/{demo['id']}/entities?kind={kind}")
        items = (r or {}).get("entities") or []
        names = [e.get("name") for e in items][:4]
        check(bool(items), f"{label} {len(items)} 条：{names}",
              f"示例项目跑完 8 阶段，{label}实体却是 0 条")

    print("\n[断言 3/5] 资产的状态与版本字段可用")
    _, r = call("GET", f"/api/projects/{demo['id']}/entities?kind=character")
    first = ((r or {}).get("entities") or [{}])[0]
    check(first.get("status") in ("DRAFT", "REVIEW", "APPROVED", "FINAL"),
          f"角色状态 {first.get('status')}", f"角色状态异常：{first.get('status')}")
    check(isinstance(first.get("version"), int) and first["version"] >= 1,
          f"版本号 {first.get('version')}", f"版本号异常：{first.get('version')}")

    print("\n[断言 4/5] 队列暂停是真的暂停（不是只回了个 200）")
    call("POST", "/api/queue/pause")
    _, vg = call("POST", f"/api/projects/{work}/video/generate",
                 {"shots": [1], "resolution": "480p", "aspect": "9:16"})
    paused_tid = (vg or {}).get("task_id")
    held = None
    end = time.time() + 12
    while time.time() < end and paused_tid:
        _, t = call("GET", f"/api/tasks?project_id={work}")
        row = next((x for x in (t or {}).get("tasks") or [] if x["id"] == paused_tid), None)
        held = (row or {}).get("status")
        if held != "waiting":
            break
        time.sleep(1)
    check(paused_tid is not None and held == "waiting",
          f"暂停期间任务停在 waiting（{paused_tid}）",
          f"暂停没生效：任务状态变成了 {held}")
    _, rs = call("POST", "/api/queue/resume")
    done_ok, last = False, None
    end = time.time() + 180
    while time.time() < end:
        _, t = call("GET", f"/api/tasks?project_id={work}")
        row = next((x for x in (t or {}).get("tasks") or [] if x["id"] == paused_tid), None)
        last = (row or {}).get("status")
        if last in ("done", "failed", "cancelled"):
            done_ok = last == "done"
            break
        time.sleep(2)
    check(done_ok, "继续后任务正常跑完",
          f"继续后任务没跑完，最后状态 {last}")

    print("\n[断言 5/5] H3 接入状态自洽")
    _, h3 = call("GET", "/api/runtime/h3")
    check(all(k in h3 for k in ("is_active", "connected", "detail", "provider_id")),
          f"H3 字段齐全（active={h3.get('active')} is_active={h3.get('is_active')}"
          f" connected={h3.get('connected')}）",
          f"H3 状态缺字段：{sorted(h3)}")
    # 没装 ComfyUI 时 is_active 就该是 False —— 这里要的是「如实回答」而不是「必须是 True」
    check(h3.get("is_active") is False or h3.get("connected") is True,
          f"H3 状态如实：{str(h3.get('detail'))[:60]}",
          f"H3 报告 is_active={h3.get('is_active')} 却没连上 ComfyUI，自相矛盾")
    _, prs = call("GET", "/api/providers")
    vids = [p for p in ((prs or {}).get("providers") or []) if p.get("type") == "video"]
    check(bool(vids), f"视频 Provider {len(vids)} 个：{[p.get('name') for p in vids]}",
          "没有任何视频 Provider")

    httpd.shutdown()

    # ---------------------------------------------------------- 覆盖报告
    all_keys = set(by_key)
    missing = sorted(all_keys - covered - set(skip))
    print("\n" + "─" * 60)
    print(f"路由覆盖：{len(covered)}/{len(all_keys)}"
          f"（另 {len(skip)} 个显式跳过）")
    if missing:
        print("未覆盖：")
        for m, p in missing:
            print(f"   · {m} {p}")
        fail.append(f"{len(missing)} 个接口没被调到")
    if http_500:
        print(f"\n返回 5xx 的接口（{len(http_500)} 个）：")
        for line in http_500:
            print("   · " + line)
        fail.append(f"{len(http_500)} 个接口返回 5xx")

    if fail:
        print(f"\n✗ {len(fail)} 项未通过：")
        for f in fail:
            print("   · " + f)
        return 1
    print("\n✓ 全部接口都能正常应答，没有 5xx，行为断言全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
