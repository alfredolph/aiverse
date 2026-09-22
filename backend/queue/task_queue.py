"""任务队列（文档 §23 / §24）。

所有生成任务进入队列，支持：暂停 / 继续 / 取消 / 重试 / 优先级 / 插队 / 自动恢复。
"""
from __future__ import annotations

import queue as qmod
import threading
import time
import traceback
from typing import Any, Callable

from ..core import db
from ..core.config import STATUS

# 终态：到了这三个状态就不再是「可以取消 / 可以插队」的任务了
_FINAL = ("done", "failed", "cancelled")


class TaskCancelled(Exception):
    """任务被取消。

    取消是**协作式**的：worker 不会在任意一行被打断（那样会留下半截产物），
    而是让任务自己在下一次 `progress()` 时抛出来，由 worker 统一收尾。
    """


class TaskQueue:
    def __init__(self, workers: int = 2):
        self._q: "qmod.PriorityQueue[tuple[int, int, str]]" = qmod.PriorityQueue()
        self._fns: dict[str, Callable] = {}
        self._meta: dict[str, dict] = {}
        self._seq = 0
        self._lock = threading.RLock()
        self._cancelled: set[str] = set()
        self._paused = False
        self._workers = []
        self._stop = False
        for i in range(max(1, workers)):
            t = threading.Thread(target=self._loop, name=f"aiverse-worker-{i}", daemon=True)
            t.start()
            self._workers.append(t)

    # ---- 对外 API --------------------------------------------------
    def submit(self, project_id: str, title: str, stage_key: str,
               fn: Callable[[Callable[[float], None]], Any], priority: int = 5) -> str:
        tid = db.new_id("t_")
        with self._lock:
            self._seq += 1
            seq = self._seq
            self._fns[tid] = fn
            self._meta[tid] = {"project_id": project_id, "title": title, "stage_key": stage_key}
            db.run(
                "INSERT INTO tasks(id,project_id,title,stage_key,status,priority,progress,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,0,?,?)",
                (tid, project_id, title, stage_key, "waiting", priority, db.now(), db.now()),
            )
            # 优先级数字越小越先执行；插队用负数
            self._q.put((priority, seq, tid))
        return tid

    def _set(self, tid: str, **fields) -> None:
        if not fields:
            return
        sets, args = [], []
        for k, v in fields.items():
            sets.append(f"{k}=?")
            args.append(v)
        sets.append("updated_at=?")
        args.append(db.now())
        args.append(tid)
        db.run(f"UPDATE tasks SET {','.join(sets)} WHERE id=?", args)

    def pause(self) -> dict:
        self._paused = True
        return {"ok": True, "paused": True}

    def resume(self) -> dict:
        self._paused = False
        return {"ok": True, "paused": False}

    def cancel(self, tid: str) -> dict:
        """取消任务。

        早先这里对任何 id 都回 `{"ok": True}` —— 传一个不存在的任务 id 也是「成功」，
        前端于是弹出「已取消」。现在先查任务：不存在、或者已经跑完，都如实说明。

        对**正在运行**的任务，光改数据库状态是不够的：worker 跑完还会把状态
        覆写成 done，用户看到的「已取消」下一秒就变回「已完成」。
        所以这里把 id 记进 `_cancelled`，任务的 `progress()` 下次被调用时抛
        `TaskCancelled`，由 worker 统一收尾。
        """
        t = db.one("SELECT * FROM tasks WHERE id=?", (tid,))
        if not t:
            return {"ok": False, "error": "任务不存在"}
        if t["status"] in _FINAL:
            return {"ok": False, "error": f"任务已结束（{t['status']}），无需取消"}
        with self._lock:
            self._cancelled.add(tid)
        self._set(tid, status="cancelled", progress=0)
        return {"ok": True, "cancelled": True}

    def retry(self, tid: str) -> dict:
        t = db.one("SELECT * FROM tasks WHERE id=?", (tid,))
        if not t:
            return {"ok": False, "error": "任务不存在"}
        fn = self._fns.get(tid)
        if not fn:
            return {"ok": False, "error": "任务函数已释放，请重新触发该阶段"}
        with self._lock:
            self._cancelled.discard(tid)
            self._seq += 1
            self._set(tid, status="waiting", progress=0, error=None)
            self._q.put((int(t["priority"]), self._seq, tid))
        return {"ok": True}

    def bump(self, tid: str, priority: int = 0) -> dict:
        """插队：以更高优先级重新入队。"""
        t = db.one("SELECT * FROM tasks WHERE id=?", (tid,))
        if not t:
            return {"ok": False, "error": "任务不存在"}
        if t["status"] in _FINAL:
            return {"ok": False, "error": f"任务已结束（{t['status']}），无法插队"}
        self._set(tid, priority=priority)
        with self._lock:
            self._seq += 1
            self._q.put((priority, self._seq, tid))
        return {"ok": True}

    def list(self, project_id: str | None = None) -> list[dict]:
        if project_id:
            rs = db.rows("SELECT * FROM tasks WHERE project_id=? ORDER BY created_at DESC", (project_id,))
        else:
            rs = db.rows("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 200")
        return rs

    def stats(self) -> dict:
        out: dict[str, int] = {}
        for r in db.rows("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status"):
            out[r["status"]] = r["n"]
        return {"by_status": out, "paused": self._paused,
                "pending": self._q.qsize(), "workers": len(self._workers)}

    def clear_finished(self, project_id: str) -> None:
        db.run("DELETE FROM tasks WHERE project_id=? AND status IN ('done','failed','cancelled')",
               (project_id,))

    # ---- 工作线程 --------------------------------------------------
    def _loop(self) -> None:
        while not self._stop:
            try:
                priority, seq, tid = self._q.get(timeout=0.4)
            except qmod.Empty:
                continue
            if self._paused:
                # 暂停：放回队列稍后处理
                self._q.put((priority, seq, tid))
                time.sleep(0.4)
                continue
            if tid in self._cancelled:
                self._cancelled.discard(tid)
                self._set(tid, status="cancelled")
                continue
            fn = self._fns.get(tid)
            if not fn:
                self._set(tid, status="failed", error="任务函数丢失")
                continue
            self._set(tid, status="generating", progress=0.05)

            def progress(p: float) -> None:
                # 协作式取消点：任务每报一次进度，就检查一次是否已被取消。
                # 放在这里而不是在 worker 里强杀，是为了让任务有机会收尾，
                # 不至于留下写了一半的文件。
                if tid in self._cancelled:
                    raise TaskCancelled(tid)
                self._set(tid, progress=round(max(0.0, min(1.0, p)), 3))

            try:
                result = fn(progress)
                if tid in self._cancelled:
                    # 取消发生在「跑完」和「收尾」之间：以取消为准，
                    # 不能把它又盖回 done —— 用户明确说过不要了。
                    self._set(tid, status="cancelled", error="已取消", progress=0)
                else:
                    self._set(tid, status="done", progress=1.0)
                    with self._lock:
                        self._meta.setdefault(tid, {})["result"] = result
            except TaskCancelled:
                self._set(tid, status="cancelled", error="已取消", progress=0)
            except Exception as e:
                if tid in self._cancelled:
                    self._set(tid, status="cancelled", error="已取消", progress=0)
                else:
                    self._set(tid, status="failed", error=f"{e}\n{traceback.format_exc()[-600:]}")
            finally:
                with self._lock:
                    self._cancelled.discard(tid)
                self._fns.pop(tid, None)


_QUEUE: TaskQueue | None = None


def queue() -> TaskQueue:
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = TaskQueue(workers=2)
    return _QUEUE
