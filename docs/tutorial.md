# 使用教程：从零到在手机上跑起来

> 目标：让 iPhone 的定位沿标准 400m 跑道、按 **3'10"/km** 跑完 **5 km**（15 分 50 秒），停止后立刻恢复真实定位。
>
> 全程 **不需要越狱**，也不需要 iPhone 上装任何 App。

![跑道几何示意](track400_geometry.png)

---

## 0. 它到底做了什么

```
Windows 电脑                         iPhone
┌──────────────┐   USB 数据线   ┌──────────────────┐
│ track400     │ ────────────▶ │ 开发者调试通道    │
│ 生成跑道坐标  │   DVT 协议     │ simulateLocation │
│ 每 1 秒一个点 │               │ 系统定位被替换    │
└──────────────┘               └──────────────────┘
```

- 位置注入是**内存级**的：程序退出、按停止、手机重启都会恢复真实定位；
- 第三方 App（地图、微信、运动软件）看到的是系统定位，所以它们都以为你在跑道上；
- 边界：只用 Apple 公开的开发者调试接口，不越狱、不伪造传感器/步频/IP、不针对任何 App 的风控做绕过。

---

## 1. 准备清单

| 项 | 要求 |
|---|---|
| 电脑 | Windows 10 / 11（macOS、Linux 未验证） |
| Python | 3.10 及以上（`python --version` 检查） |
| 数据线 | 能传数据的 USB 线（很多充电线不传数据） |
| 手机 | iPhone，iOS 17 及以上 |
| 网络 | 仅首次安装依赖需要 |

---

## 2. 安装（约 3 分钟）

```powershell
git clone https://github.com/zhangzixin1221/track400.git
cd track400
python -m pip install -e ".[device]"
```

验证：

```powershell
track400 --version      # 应输出 track400 1.1.0
python -m pytest        # 应输出 82 passed
```

> 不想装环境？项目根目录的 `start.bat` 会自动把 `src/` 加进 `PYTHONPATH`，
> 只要 Python 能跑、且已 `pip install -e ".[device]"` 装过依赖即可。

---

## 3. 先不接手机，跑一遍看看（30 秒）

```powershell
track400 --fake --speedup 400
```

`--fake` = 不接手机，把坐标流写到 `runs/*.jsonl`；`--speedup 400` = 400 倍速。

期望输出：

```
== track400 ==
中心  : 34.0382408, 108.7644990 (WGS-84)
计划  : 道次 2 | 圈长 407.04 m | 配速 3'10"/km | 时长 950.0 s | 距离 5000.0 m | 圈数 12.284
配速  : 3'10"/km | 单圈 77.337 s
...
圈  4 |  1578.9 m | 用时 05:00 | 道次 2 | 配速 3'10"/km | 余 10:50
...
完成  : stopped | 注入 951 点 | 重连 0 次 | 保活 0 次 | 计划 15:50
```

字段含义：**圈数 | 累计距离 | 已用时 | 道次 | 配速 | 剩余时间**。

---

## 4. 接上手机：5 个前置检查

按顺序执行，**每一步都要通过**再往下走。

### 4.1 驱动能认到手机

```powershell
pymobiledevice3 usbmux list
```

期望：出现一段 JSON，含 `"ProductVersion": "27.0.1"` 之类。

没有输出 → 换数据线/换 USB 口；检查服务：

```powershell
Get-Service "Apple Mobile Device Service"    # 应为 Running
```

### 4.2 手机已信任这台电脑

```powershell
pymobiledevice3 lockdown info
```

期望：返回一大段 plist 信息（`ActivationState`、`ProductVersion` 等）。

报错 → 解锁手机，点「信任」，输入锁屏密码。

### 4.3 开发者模式已打开

设置 → 隐私与安全性 → **开发者模式** → 打开 → 重启 → 解锁后确认。

### 4.4 隧道 + 开发者服务可用

```powershell
pymobiledevice3 developer dvt device-information
```

期望：2~3 秒内返回 JSON（CPU、内核信息）。

### 4.5 开发者镜像（DDI）已挂载

```powershell
pymobiledevice3 developer dvt ls /Developer
```

期望：退出码 0（无报错）。

> 这一步失败是最常见的坑，处理办法见 [`errors.md`](errors.md) 第 2 节。

---

## 5. 第一次真机短跑（60 秒）

```powershell
python tools\live_test.py --seconds 60 --pace 9:00
```

然后在手机上打开「地图」：

- ✅ 蓝点应该出现在操场上，沿**东侧直道由南往北**缓慢移动；
- ✅ 60 秒后（或按 `Ctrl+C`）蓝点弹回你真实位置。

第一次跑通后，再去跑正式配置。

---

## 6. 正式跑：5 km @ 3'10"/km

### 方式 A：一键启动

双击项目根目录的 **`start.bat`**。

### 方式 B：命令行

```powershell
track400
```

两者等价，都是默认配置：**5 km、3'10"/km、第 2 道、西安操场、约 15 分 50 秒**。

运行中的按键：

| 按键 | 动作 |
|---|---|
| `p` | 暂停（时间轴冻结，恢复后配速不变形） |
| `r` | 继续 |
| `s` / `q` | 停止（立即恢复真实定位） |
| `Ctrl+C` | 同上 |

> 暂停/停止都会走 `clear()`，所以**任何退出方式都会恢复真实定位**。

---

## 7. 常用自定义

```powershell
track400 --pace 4:30 --distance 10km     # 换配速和距离
track400 --lane 1                        # 第 1 道（一圈 400.00 m）
track400 --laps 12                       # 按圈数跑（12 圈 = 4884 m）
track400 --heading 180                   # 反向跑（顺时针）
track400 --duration 600                  # 按时间跑 10 分钟
track400 --gpx-out runs/my_route.gpx     # 顺手导出 GPX
```

换场地（比如另一个操场）：

```powershell
# 方式 1：百度地图拾取的 BD09 坐标（程序自动两级反纠偏）
track400 --bd09 34.04244774,108.77577825

# 方式 2：已知 WGS-84 坐标
track400 --lat 34.0382408 --lon 108.7644990

# 方式 3：只想看格式，不接手机
track400 --fake --speedup 400 --bd09 39.90869,116.39748
```

---

## 8. 跑完怎么确认

1. **定位恢复**：手机地图蓝点回到真实位置。若没有：
   ```powershell
   pymobiledevice3 developer dvt simulate-location clear
   ```
2. **数据在哪**：`runs/` 目录，FakeDevice 是 JSONL，GPX 是 `--gpx-out` 指定的文件。
3. **复盘轨迹**（可选）：
   ```powershell
   python tools\verify_gpx.py runs\my_route.gpx --points 951 --duration 950 --dt 1.0 --distance 5000 --lane 2
   ```

---

## 9. 出问题先看这张表

| 现象 | 先做什么 |
|---|---|
| `usbmux list` 空 | 换线/换口，确认服务在跑 |
| 隧道建不起来 | 解锁手机一次；确认没有另一个 `track400` 在跑 |
| DVT 打不开 | 检查 DDI：`pymobiledevice3 developer dvt ls /Developer` |
| 蓝点不动 | 先跑 60 秒短测；不行就单独 `simulate-location set` 试 |
| 中途 `[lost]` | 插回线，按 `r` 继续；程序不会崩 |
| 定位没恢复 | `pymobiledevice3 developer dvt simulate-location clear` |

完整对照表：[`errors.md`](errors.md)。

---

## 10. 常见问题

**Q：需要越狱吗？**
不需要。走的是 Apple 给 Xcode 用的开发者调试通道。

**Q：手机需要装 App 吗？**
不需要。

**Q：iOS 16 能用吗？**
不能。`simulate-location` 的 DVT 实现在 iOS 17+ 才提供；项目里还有一条 `developer simulate-location`（旧协议）仅支持 < 17，本项目未使用。

**Q：会被检测到吗？**
这是系统级定位替换，第三方 App 拿到的是系统定位，与真机定位在 API 层没有区别。但本项目**不提供**任何针对风控的对抗手段，也不建议用于违反第三方服务条款的场景。

**Q：能同时跑两个吗？**
不能。无 root 隧道是进程级单例，同一时刻只能有一个 `track400` 在跑。

**Q：跑的时候能用手机导航吗？**
不建议——这 15 分钟里所有 App 看到的都是操场。

---

## 11. 原理一页纸

| 层 | 做什么 |
|---|---|
| `geo/` | BD09→GCJ02→WGS84 反纠偏；局部 ENU 平面 |
| `track/` | 400m 几何（直道 84.39、R(2)=37.92）、等间距采样 |
| `pacing/` | 配速 → 时间戳：`deadline = anchor + t + paused_total` |
| `gpx` | GPX 1.1 写出与契约校验 |
| `device/` | `IDevice` 接口：`FakeDevice` 落盘 / `RealDevice` 走 DVT |
| `controller` | 状态机：RUNNING ⇄ PAUSED，断线→LOST→等你 resume |
| `cli` | 参数、键盘控制、Ctrl+C 安全退出 |

更细的设计见 [README](../README.md)，报错处置见 [errors.md](errors.md)。
