"""track400 —— 沿标准 400m 田径场跑道连续绕圈，并通过 iPhone 开发者通道注入位置。

分层约定（自底向上，严格单向依赖）：

    geo / track / pacing   纯数学，零 I/O，可在任何机器上单测
    device.base            抽象接口
    device.fake            落盘实现（无设备）
    device.real            pymobiledevice3 实现（仅此模块 import 第三方包）
    controller             状态机 / 时间轴 / 保活 / 重连
    cli                    参数解析与装配

本文件当前只导出数学层（Step 2 交付物）。
"""

from __future__ import annotations

__version__ = "1.1.0"

__all__ = ["__version__"]
