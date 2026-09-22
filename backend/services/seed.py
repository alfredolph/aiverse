"""首次运行播种：自动建一个跑满 8 阶段的示例项目。

目的很单纯 —— 用户装完打开就能看到「一条产线长什么样」，
而不是面对一个空列表猜怎么用（对应文档 §53 原则 1：不让用户学习 AI 工具）。

只会在项目数为 0 时执行一次，后台线程跑，不阻塞启动。
"""
from __future__ import annotations

import threading
import time

from ..core import projects as projects_core
from ..core import store
from ..workflow import engine
from . import pipeline

DEMO_NAME = "示例 · 药铺里的秘密"

# 刻意写短：示例项目要在 30 秒内跑完，用户才有耐心看完一遍
DEMO_SCRIPT = """【场景 药铺内 夜】

雨敲在檐上，灯笼在风里晃。李明推开木门，冷风灌进来。

掌柜：这么晚了，还买药？

李明：我要一味药，三年前你欠我的。

掌柜：……三年前的事，你也敢提。

【场景 后山 晨】

雾很重。掌柜站在一块青石前，脚边放着一只旧木箱。

掌柜：你要的药，不在箱子里。

李明：那在哪里？

掌柜：在你身上。三年前那场火，活下来的人不止你一个。

李明：……我娘呢。

掌柜：她把你托付给我，然后自己走进了火里。
"""


def _run_demo(pid: str) -> None:
    """把示例项目跑满 8 个阶段，每阶段自动审核通过。"""
    order = ["script", "characters", "scenes", "storyboard", "video", "voice", "edit", "final"]
    for key in order:
        for attempt in (1, 2):
            try:
                r = pipeline.run_stage(pid, key)
                if r.get("ok"):
                    break
                time.sleep(0.4)
            except Exception:
                time.sleep(0.4)
        try:
            engine.approve(pid, key)
        except Exception:
            pass
    try:
        store.write_json(pid, "seed.json",
                         {"demo": True, "seeded_at": time.time()})
    except Exception:
        pass


def ensure_demo_project(force: bool = False) -> str | None:
    """项目列表为空时创建一个示例项目并后台跑满全流程。返回项目 id。"""
    if not force:
        try:
            if projects_core.list_projects():
                return None
        except Exception:
            return None

    p = projects_core.create(
        name=DEMO_NAME,
        script=DEMO_SCRIPT,
        style="guoman",
        aspect="9:16",
        resolution="1080p",
        mode="novice",
        source="demo",
    )
    pid = p["id"]
    store.write_text(pid, "script/script.md", DEMO_SCRIPT)
    threading.Thread(target=_run_demo, args=(pid,), name="aiverse-seed", daemon=True).start()
    return pid
