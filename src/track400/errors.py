"""领域异常。

约定：每个异常都带 ``hint``（自愈建议）与 ``code``（稳定的机器可读标识），
CLI 层只负责把 ``code`` / ``hint`` 原样打印，不做二次翻译。
"""

from __future__ import annotations


class Track400Error(Exception):
    """所有本工具异常的基类。"""

    code: str = "track400_error"
    hint: str = ""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        if hint is not None:
            self.hint = hint


class ConfigError(Track400Error):
    """命令行参数或业务参数不合法。"""

    code = "config_error"


class LaneError(ConfigError):
    """道次非法或超出该场地容量。"""

    code = "lane_error"


class PaceError(ConfigError):
    """配速非法（<=0 或换算后速度不合理）。"""

    code = "pace_error"


class DtError(ConfigError):
    """采样间隔超出允许区间 [0.5, 1.0] s。"""

    code = "dt_error"


class MathError(Track400Error):
    """数学层内部一致性校验失败（理论上不该发生）。"""

    code = "math_error"


class GpxError(Track400Error):
    """GPX 生成或校验失败。"""

    code = "gpx_error"


class DeviceError(Track400Error):
    """设备层失败（未连接、隧道断开、DDI 未挂载、注入被拒等）。"""

    code = "device_error"
