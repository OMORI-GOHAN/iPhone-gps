# 可编程 iPhone GPS 工具

通过无需越狱的开发者接口模拟 iPhone 定位，提供异步 Python API 和 CLI。首版面向 Arch Linux；设计依据见 [ARCHITECTURE.md](ARCHITECTURE.md)。

已实现设备发现、准备检查、显式配对与 DDI 挂载、持久 GPS 会话、固定定位、重复更新、清除、取消与断线处理。轨迹执行、GPX、插件、自动安装与前端留待后续。

## 安装与准备

需要 Python 3.11+。设备依赖集中锁定为 `pymobiledevice3==11.49.2`；不访问设备时可不安装它。

```bash
uv sync --extra device
uv run iphone-gps setup
uv run iphone-gps devices
uv run iphone-gps doctor
```

Arch 主机需已有可用的 `usbmuxd`。解锁手机，通过 USB 连接，保留手机上的信任与开发者模式确认。系统依赖和权限由用户管理，本工具不自动安装或启动主机服务。

iOS 17+ 使用已有的本地开发者隧道。若检查提示隧道缺失，在另一终端用同一个 Python 环境启动并保持运行（可能需要系统权限）：

```bash
sudo .venv/bin/python -m pymobiledevice3 remote tunneld
```

只有以下显式命令会尝试配对及挂载 DDI，可能下载适配镜像；不会替用户打开开发者模式：

```bash
uv run iphone-gps gps prepare
uv run iphone-gps doctor
```

多设备时，对 `doctor` 和 `gps` 子命令传入 `--device UDID`。普通检查不挂载 DDI、不下载。`setup` 只检查主机依赖。

## CLI

项目提供 `gps` 快捷入口，无需配置终端别名。更新项目后运行一次 `uv sync --extra device` 即可使用：

```bash
uv run gps 28.2282 112.9388
uv run gps --coord-system gcj02 28.167440144763262 112.96048234383075
uv run gps --duration 30 -- 28.2282 112.9388
uv run gps status
uv run gps clear
```

直接跟坐标或已保存的地点名默认执行 `set`，按 Ctrl+C 结束；不传参数显示帮助，不会使用默认坐标或连接手机。原有完整命令仍然可用：

```bash
# 无需安装设备依赖、不连接手机的预演
PYTHONPATH=src python -m iphone_gps gps set --dry-run -- 28.2282 112.9388

# 保持固定位置，Ctrl+C 或 SIGTERM 时尽力清除并释放连接
uv run iphone-gps gps set -- 28.2282 112.9388

# 保持 30 秒后清除并退出
uv run iphone-gps gps set --duration 30 -- 28.2282 112.9388

uv run iphone-gps gps status
uv run iphone-gps gps clear
```

坐标顺序为纬度在前、经度在后，`--` 支持负数。默认按 WGS84 原样提交；输入是 GCJ-02 时，显式使用 `--coord-system gcj02`，工具会先换算为近似 WGS84，并显示输入和提交目标。完整命令 `iphone-gps gps set` 也支持此选项。不会按地图名称自动猜测坐标系，不支持 BD-09。GCJ-02 转换使用有界迭代算法，只接受纬度 3.86–53.55、经度 73.66–135.05 的开区间近似适用范围；此矩形不是国界判定。数值计算精度不代表手机定位精度。

可以先预演，不连接设备：

```bash
uv run gps --coord-system gcj02 --dry-run 28.167440144763262 112.96048234383075
# 提交目标（WGS84）：纬度 28.170914691，经度 112.954996509
```

此结果与用户已实机验证的手动换算坐标一致。不要对已经转换成 WGS84 的数值再次使用 `--coord-system gcj02`。

成功提交仅表示后端接受请求，本工具不读取手机实际位置，请在手机地图中确认。清除请求发送和连接关闭后，手机位置恢复及地图刷新可能有延迟，仍需在手机上确认。保持期间检测到定位连接关闭会结束会话，不自动重连或重放。

## 保存命名地点

地点保存、查看和删除均不连接手机，不需要开发者隧道。输入仍是纬度在前、经度在后，保存时声明来源坐标系；默认 WGS84。

```bash
# 保存东京地点（WGS84）
uv run gps place save 东京 35.71488401550224 139.7966438955983

# 保存教学楼的原始 GCJ-02 坐标
uv run gps place save 教学楼 --coord-system gcj02 28.169004 112.945261

# 下次直接用名称定位：自动使用保存的坐标系，无需再次指定
uv run gps 东京
uv run gps 教学楼

# 名称同样支持预演、限时和设备选择
uv run gps --dry-run 教学楼
uv run gps --duration 30 教学楼
uv run gps --device UDID 教学楼

# 管理地点
uv run gps place list
uv run gps place show 教学楼
uv run gps place delete 教学楼

# 更新同名地点必须显式覆盖，并再次声明原坐标的坐标系
uv run gps place save 教学楼 --replace --coord-system gcj02 28.167440144763262 112.96048234383075
```

名称可使用中文、空格和标点，含空格时加引号，例如 `uv run gps "学校 北门"`。名称需为 1–100 个可打印字符，不能是纯数字或数值，以免和坐标混淆。若名称与子命令重名，例如 `status`，使用 `uv run gps set status` 明确指定地点。

地点保存在 `$XDG_DATA_HOME/iphone-gps/places.sqlite3`；未设置绝对路径的 `XDG_DATA_HOME` 时使用 `~/.local/share/iphone-gps/places.sqlite3`。同一用户可跨终端和项目目录使用，采用 SQLite 事务避免多个命令同时写入时丢失其他地点。读取不存在的地点库不会创建文件。

保存的是原始坐标与来源坐标系，定位时转换为 WGS84，不会覆盖保存的原始数值。按地点名定位时不接受 `--coord-system` 覆盖，避免重复转换；要修改坐标系，重新保存并加 `--replace`。文件损坏时会报错，不会自动清空地点列表。

## Python API

```python
import asyncio
from iphone_gps.api import Coordinate, GpsSession

async def main():
    # 多设备时指定 GpsSession(device="设备 UDID")
    async with GpsSession() as gps:
        await gps.set_location(Coordinate(28.2282, 112.9388))
        await asyncio.sleep(1)
        await gps.set_location(Coordinate(28.2283, 112.9389))
        await asyncio.sleep(1)
        await gps.clear_location()

asyncio.run(main())
```

`GpsSession` 在同一连接上串行提交更新，不建立后台写入队列。调用者自行控制节奏，并使用异步上下文确保退出清理。`target` 是最近尝试提交的目标，`last_submitted` 是最近成功提交的坐标，`actual_location` 为 `None`。清除成功将前两个字段置空。操作失败后该会话不可再次写入。

公开入口还包括 `list_devices()`、`check_device()`、`prepare_device()`、结构化结果和错误类型。核心不打印、不读取输入、不安装依赖；可通过 `backend=` 注入符合内部协议的测试后端。

Python 调用者可用 `to_wgs84(latitude, longitude, source="gcj02")` 转换输入，得到可直接传给 `set_location()` 的 `Coordinate`；会话和后端始终只使用 WGS84。

命名地点也可通过公开 API 管理：`PlaceStore().save(name, latitude, longitude, coord_system="gcj02")`、`get(name)`、`list()` 和 `delete(name)`。`get()` 返回的 `SavedPlace.coordinate` 是转换后的 WGS84 坐标，可传给 `set_location()`；同名更新需 `replace=True`，地点错误使用 `PlaceError`。

退出时尽力清除和关闭连接；已确认断线时跳过清除，仅释放本地连接资源，不能保证手机定位恢复。默认设备操作超时 30 秒，清除和关闭各最多等待 5 秒（后端还对各资源关闭设有限时）。`cleanup_result` 保留清除、释放和异常结果，`clear_skipped` 表示断线后未发送清除请求；`cleared` 仅表示清除调用返回，不是手机接收确认。普通退出清理失败会抛出 `CleanupError`。若用户代码已有异常或取消，则保留原始异常并附加清理失败说明。

运行期间同时监测定位通道关闭和 USB 设备是否仍存在，USB 正常情况下约每半秒检查一次（响应时间还受 usbmuxd 影响）。所选手机仅通过网络可见时，也视为 USB 已断开。Arch 上拔掉最后一台设备后 usbmuxd 可能自动退出；此时会通过系统 USB 列表再次核对手机是否已消失。手机仍在或系统列表不可读时，单独报告监测失败及错误类型，不直接认定手机被拔出。

同一用户下，以设备为单位使用 Linux 文件锁防止本工具的跨进程争用；不协调其他定位工具。更新速率和可影响的 App 需实测，不保证全局生效或永久保持。

## 验证

无需设备依赖即可执行核心和 CLI 测试；装有指定依赖后还会执行适配器边界测试。测试不连接手机。

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
# 或安装了 device extra 的环境
PYTHONPATH=src uv run python -m unittest discover -s tests -v
```

实机已通过固定位置、同一会话连续更新、Ctrl+C 退出及拔线检测。拔线复验确认：程序报告 USB 设备断开、停止后续坐标提交、跳过离线清除并释放本地连接资源。正常清理后曾观察到约十多秒恢复地图位置，早期拔线测试曾观察到约一分钟恢复；本次拔线复验尚未记录恢复耗时。不承诺拔线立即恢复定位。最终实现同时检查定位通道与 USB；usbmuxd 在拔线后自动退出时，通过系统 USB 列表核对设备是否消失。

### 连续更新示例

保持手机解锁、USB 连接及开发者隧道运行，先退出其他定位会话，然后在项目目录执行：

```bash
# 先查看三个测试坐标，不连接手机
uv run python examples/continuous_updates.py --dry-run

# 同一个会话连续提交三个长沙附近坐标，各保持 10 秒
uv run python examples/continuous_updates.py
```

观察终端依次出现 `[1/3]`、`[2/3]`、`[3/3]`，以及手机地图是否跟随变化。三个点之间相距约数百米；这是离散坐标更新，不模拟点间的平滑行走。默认约 30 秒后自动清除并关闭，恢复情况仍需在手机上确认。地图刷新较慢时，可加 `--interval 20`，多设备时加 `--device UDID`。

分三次运行完成验收，每次等待手机位置恢复后再进行下一次：

1. 正常结束：让三个坐标全部执行，记录地图是否依次变化，以及结束后恢复的耗时。
2. Ctrl+C：重新运行，在第一个或第二个坐标保持时按 Ctrl+C，确认程序退出，观察恢复情况。取消退出码为 130。
3. 拔线：重新运行，在保持期间拔掉 USB，确认程序报告断线并退出，没有继续提交后续坐标。离线清除失败可以预期，请记录输出及手机是否恢复。失败退出码为 1。

示例使用公开 Python API，在等待期间也监听断线；不会自动重连。若测试失败，保留终端报错和清理说明，以便继续排查。
