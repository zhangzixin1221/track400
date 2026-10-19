# 常见报错对照表

> 本文与代码一一对应：`errors.py` 里的每个 `code`、`device/real.py` 里每条 `DeviceError` 的 `hint`，都能在下表找到。  
> 先跑「0. 一分钟定位」，90% 的问题能直接定位到层。

---

## 0. 一分钟定位

```powershell
# ① 驱动与设备枚举：应有 JSON，含 ProductVersion
pymobiledevice3 usbmux list

# ② 配对与信任：应返回完整 plist（ActivationState 等）
pymobiledevice3 lockdown info

# ③ 隧道 + DVT + DDI：应返回 JSON（2~3 s）
pymobiledevice3 developer dvt device-information

# ④ 开发者镜像是否挂载：退出码 0 即已挂载
pymobiledevice3 developer dvt ls /Developer

# ⑤ 本工具版本
track400 --version
```

| 在哪一步失败 | 去哪一节 |
|---|---|
| ① 空数组 / 报错 | [1. 连接与前置](#1-连接与前置) |
| ② 报 PairingDialogResponsePending / 空 | [1. 连接与前置](#1-连接与前置) |
| ③ 报 dtservicehub / 超时 | [2. DDI / 隧道 / DVT](#2-ddi--隧道--dvt) |
| ④ 非 0 | [2. DDI / 隧道 / DVT](#2-ddi--隧道--dvt) |
| 全部通过但 track400 报错 | [3. 运行期](#3-运行期) |

---

## 1. 连接与前置

| 现象 | 典型报错 | 原因 | 处置 |
|---|---|---|---|
| `usbmux list` 返回 `[]` | — | 线是“只充电”线；USB 口故障；`Apple Mobile Device Service` 没跑 | 换数据线/换口；`Get-Service "Apple Mobile Device Service"` 应为 Running；必要时重装 Apple Mobile Device Support |
| 报设备未连接 | `NoDeviceConnectedError` / `Device is not connected` | 手机锁屏未信任；配对记录丢失 | 解锁手机，点“信任”；`pymobiledevice3 lockdown pair` |
| 弹出信任框但一直不点 | 命令挂起 | 手机端等待确认 | 在手机上点“信任”，输入锁屏密码 |
| `lockdown info` 报 `PairingDialogResponsePending` | — | 配对未完成 | 手机上完成信任；或删除 `C:\ProgramData\Apple\Lockdown\<UDID>.plist` 后重新配对 |
| `track400` 报「无法连接设备」 | `DeviceError: 无法连接设备: ...` | 上述任一 | 按 hint 四步查：数据线 → 信任 → 开发者模式 → 服务 |
| 开发者命令全挂 | `DeveloperModeStatus = false` | 开发者模式没开 | 设置 → 隐私与安全性 → 开发者模式 → 打开 → 重启 → 解锁 |
| 重启手机后立刻跑失败 | `InvalidServiceError` / 隧道失败 | iOS 17+ 重启后需解锁一次才提供开发者服务 | 解锁一次，等 5 s，重试 |

---

## 2. DDI / 隧道 / DVT

| 现象 | 典型报错 | 原因 | 处置 |
|---|---|---|---|
| `track400` 报「RSD 隧道建立失败」 | `DeviceError: RSD 隧道建立失败: ...` | 设备未解锁；同进程已有隧道；USB 掉线 | ① 解锁手机 ② 确认没有别的 `track400`/pymobiledevice3 在跑 ③ 重插 USB |
| 报隧道单例冲突 | `UserspaceTunnelUnavailableError` / “already active” | 无 root userspace 隧道是**进程级单例** | 等上一个进程退出；或用 `remote tunneld` 走独立进程 |
| 报「DVT 通道打开失败」 | `DeviceError: DVT 通道打开失败: ...` | DDI 没挂载 / 已失效 | 见下一行 |
| 报「DDI 未挂载，自动挂载失败」 | `ModuleNotFoundError: lzss` 等 | Python 依赖残缺 | `pip install pylzss lzfse construct pycryptodome`（cp314 有预编译轮子） |
| 同上 | `SSLCertVerificationError`（raw.githubusercontent.com） | **本机 hosts 把 GitHub 指到 127.0.0.1**（Steam++ 加速器在 443 上中转，Python 不信任其 CA） | 三选一：① 用 Xcode/Apple Configurator 挂一次 DDI；② 让 Python 信任该 CA / 临时注释 hosts 那行；③ 手动下 DDI 后 `pymobiledevice3 mounter mount` |
| 报「DDI 挂载命令返回成功，但 dtservicehub 仍不可见」 | — | 挂载未真正生效 | 重启手机 → 解锁 → 重新挂载；确认开发者模式未被关 |
| `mounter` 命令直接崩 | `ModuleNotFoundError: No module named 'construct'` | pyiosbackup 依赖缺失 | `pip install construct` |
| `pymobiledevice3 --help` 崩 | `No module named 'remotezip2'` | 安装残缺（与主链路无关） | 建干净 venv 重装；不影响 `developer dvt` 路径 |

---

## 3. 运行期

| 现象 | 日志/报错 | 原因 | 处置 |
|---|---|---|---|
| 进度里出现 `[lost]` | `LOST` + `注入坐标失败: ...` | USB 断线 / 手机锁屏被杀 / 设备重启 | 保持程序运行，插回线；重连成功会打印 `[reconnected]`，按 `r` 续跑 |
| 一直停在 `[reconnected]` | — | **设计如此**：按你的要求，重连后等你确认 | 按 `r`；或启动时加 `--resume-after-reconnect` |
| 按 `p` 没反应 | — | 非交互终端（管道/CI） | 只有 `Ctrl+C` 可用；要键盘控制请在真实终端里跑 |
| `Ctrl+C` 后定位没恢复 | — | `clear` 失败（极少见） | 手动兜底：`pymobiledevice3 developer dvt simulate-location clear`；或拔线/重启 |
| 蓝点没动 / 还在原地 | 进度正常、无报错 | 模拟未生效（DDI 异常）或看错设备 | 先用 7.2(a) 的 60 s 用例目视确认；`pymobiledevice3 developer dvt simulate-location set 34.0382 108.7645` 单独试 |
| 蓝点跳变 | — | `--dt` 过大或 `--speedup` 用在真机 | `--dt 0.5`；真机禁用 `--speedup`（程序会拒绝） |
| 单点延迟高（>200 ms） | 日志 `延迟: 中位 ...` | USB 2.0 / 线材差 / 系统负载 | 换 USB 3 口与好线；1 Hz 下 200 ms 仍可接受 |
| 跑完最后一行重复 | — | 旧版本渲染节流缺陷 | 升级到 1.0.0（已修） |

---

## 4. 参数与数学层

| 报错码 | 文案 | 处置 |
|---|---|---|
| `config_error` | `--lat 与 --lon 必须同时提供` | 两个都给，或改用 `--bd09` |
| `config_error` | `--bd09 需要 '纬度,经度' 两个数` | 写成 `--bd09 34.04244774,108.77577825` |
| `config_error` | `duration / laps / distance 必须且只能指定一个` | `--distance 5km`、`--duration 950`、`--laps 12.28` 三选一；都不给则默认 5 km |
| `config_error` | `无法解析距离 '...'` | 写成 `--distance 5km` / `5000m` / `5000` |
| `lane_error` | `道次 N 超出范围 1..8` | 用 1..8 |
| `dt_error` | `采样间隔 dt=... 超出允许区间 [0.5, 1.0] s` | `--dt 0.5`~`1.0` |
| `pace_error` | `无法解析配速 '...'` | `--pace 4:00` 或 `--pace 240` |
| `gpx_error` | `点数不符` / `总时长不符` / `Δt 不符` / `总距离不符` | 重新生成 GPX；或检查是否被手工改过 |
| `math_error` | `gcj02_to_wgs84 未在 30 次迭代内收敛` | 理论上不会出现；出现即坐标输入异常（如 NaN） |

---

## 5. 兜底命令

```powershell
# 立即恢复真实定位
pymobiledevice3 developer dvt simulate-location clear

# 看设备当前是否已挂载 DDI
pymobiledevice3 developer dvt ls /Developer

# 重新挂载 DDI（依赖网络，见上表）
pymobiledevice3 mounter auto-mount

# 校验 GPX
python tools\verify_gpx.py runs\route.gpx --points 661 --duration 660 --dt 1.0 --distance 2750 --lane 2

# 无设备全链路自检
python -m pytest
```
