"""pytest 全局配置：把 ``src/`` 挂到 sys.path（无需安装包即可跑测试）。"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
