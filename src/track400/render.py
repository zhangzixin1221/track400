"""进度显示：单行刷新 / 非 TTY 自动降级为逐行。

显示字段按需求：**圈数 / 距离 / 用时 / 道次 / 剩余时间**，另加配速与状态。
非 RUNNING 状态会带 ``[paused]`` ``[lost]`` 之类的标签，避免"看起来在跑其实停了"。
"""

from __future__ import annotations

import sys
from typing import TextIO

from .controller import State, Status
from .pacing.schedule import Plan, format_pace, speed_to_pace


def format_mmss(seconds: float) -> str:
    """秒 → ``MM:SS``（超过 1 小时给 ``H:MM:SS``）。四舍五入到秒，避免 949.999 显示成 15:49。"""
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_status(st: Status, plan: Plan) -> str:
    tag = "" if st.state is State.RUNNING else f" [{st.state.value}]"
    lap = f"{st.lap:2d}"
    return (
        f"圈 {lap} | {st.s:7.1f} m | 用时 {format_mmss(st.t)} | "
        f"道次 {plan.lane} | 配速 {format_pace(speed_to_pace(plan.speed))} | "
        f"余 {format_mmss(st.remaining)}{tag}"
    )


class ProgressRenderer:
    """按虚拟时间节流的状态打印机。"""

    def __init__(
        self,
        plan: Plan,
        *,
        stream: TextIO | None = None,
        every_s: float = 1.0,
    ) -> None:
        self.plan = plan
        self.stream = stream or sys.stdout
        self.every_s = every_s
        self.is_tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self._last_t = -1e9
        self._last_state: State | None = None
        self._wrote_any = False

    def __call__(self, st: Status) -> None:
        if not self._should_print(st):
            return
        line = format_status(st, self.plan)
        if st.message and st.state is not State.RUNNING:
            line += f"  ({st.message})"
        if self.is_tty:
            self.stream.write("\r" + line.ljust(110))
        else:
            self.stream.write(line + "\n")
        self.stream.flush()
        self._last_t = st.t
        self._last_state = st.state
        self._wrote_any = True

    def _should_print(self, st: Status) -> bool:
        # 终点：最后一个点已经按节流打印过，不再重复一行 [stopped]
        if st.state is State.STOPPED and st.t == self._last_t:
            return False
        if st.state is not self._last_state:
            return True
        if st.state is not State.RUNNING:
            return False
        return (st.t - self._last_t) >= self.every_s

    def finish(self) -> None:
        if self.is_tty and self._wrote_any:
            self.stream.write("\n")
            self.stream.flush()
