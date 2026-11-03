"""GPS CLI; all device work goes through the public API."""

import argparse
import asyncio
import math

from ...api import GpsError, GpsSession, PlaceStore, check_device, prepare_device, to_wgs84


def coordinate(value: str, limit: int) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("坐标必须是数字") from exc
    if not math.isfinite(number) or not -limit <= number <= limit:
        raise argparse.ArgumentTypeError(f"坐标必须在 {-limit} 到 {limit} 之间")
    return number


def duration(value):
    number = coordinate(value, 86400 * 365)
    if number <= 0:
        raise argparse.ArgumentTypeError("持续时间必须大于 0")
    return number


def latitude_or_place(value):
    try:
        float(value)
    except ValueError:
        return value
    return coordinate(value, 90)


def register_parser(commands):
    gps = commands.add_parser("gps", help="GPS 模拟定位")
    configure_parser(gps)


def configure_parser(gps):
    actions = gps.add_subparsers(dest="gps_command", required=True)
    for name, description in (("status", "查看准备状态"), ("prepare", "配对及挂载 DDI（可能下载镜像）"),
                              ("set", "保持模拟定位直到 Ctrl+C"), ("clear", "清除模拟定位")):
        action = actions.add_parser(name, help=description)
        action.add_argument("--device", metavar="UDID", help="指定 USB 设备；多设备时必填")
        action.set_defaults(handler=run)
        if name == "set":
            action.add_argument("latitude", type=latitude_or_place, metavar="纬度或地点名")
            action.add_argument("longitude", nargs="?", type=lambda value: coordinate(value, 180), metavar="经度")
            action.add_argument("--dry-run", action="store_true", help="仅预演，不连接手机")
            action.add_argument("--duration", type=duration, help="保持指定秒数后清除并退出")
            action.add_argument("--coord-system", choices=("wgs84", "gcj02"),
                                help="坐标输入默认 wgs84；地点名使用保存的坐标系，无需重复指定")
    places = actions.add_parser("place", help="保存、查看和删除命名地点（不连接设备）")
    place_actions = places.add_subparsers(dest="place_command", required=True)
    for name, description in (("save", "保存地点"), ("list", "列出所有地点"),
                              ("show", "查看地点坐标"), ("delete", "删除地点")):
        action = place_actions.add_parser(name, help=description)
        action.set_defaults(handler=run_places)
        if name != "list":
            action.add_argument("name", help="地点名，含空格时使用引号；不能为纯数字")
        if name == "save":
            action.add_argument("latitude", type=lambda value: coordinate(value, 90))
            action.add_argument("longitude", type=lambda value: coordinate(value, 180))
            action.add_argument("--coord-system", choices=("wgs84", "gcj02"), default="wgs84")
            action.add_argument("--replace", action="store_true", help="覆盖已有同名地点")


def print_place(place):
    print(f"{place.name} | {place.latitude}, {place.longitude} | {place.coord_system.upper()}")


async def run_places(args):
    store = PlaceStore()
    if args.place_command == "save":
        place = store.save(args.name, args.latitude, args.longitude,
                           coord_system=args.coord_system, replace=args.replace)
        print("已保存地点：", end="")
        print_place(place)
    elif args.place_command == "list":
        places = store.list()
        for place in places:
            print_place(place)
        if not places:
            print("尚未保存地点；使用 gps place save 名称 纬度 经度 添加。")
    elif args.place_command == "show":
        place = store.get(args.name)
        print_place(place)
        target = place.coordinate
        print(f"提交目标（WGS84）：纬度 {target.latitude:.9f}，经度 {target.longitude:.9f}")
    else:
        store.delete(args.name)
        print(f"已删除地点：{args.name}")
    return 0


def print_readiness(result):
    print(f"{result.name} / iOS {result.product_version} / {result.device.udid}")
    for name, value in (("配对", result.paired), ("开发者模式", result.developer_mode),
                        ("DDI", result.ddi_mounted), ("开发者隧道", result.tunnel_available)):
        print(f"{name}：" + ("未知或不适用" if value is None else "就绪" if value else "未就绪"))
    for issue in result.issues:
        print(f"下一步：{issue}")
    print("本工具不读取手机实际位置，请在手机地图中确认。")
    return 0 if result.ready else 1


async def hold(session, seconds):
    tasks = [asyncio.create_task(session.wait_disconnected())]
    if seconds is not None:
        tasks.append(asyncio.create_task(asyncio.sleep(seconds)))
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def run(args):
    if args.gps_command == "set":
        if isinstance(args.latitude, str):
            if args.longitude is not None:
                raise GpsError("地点名后不能再跟经度；请使用“地点名”或“纬度 经度”")
            if args.coord_system is not None:
                raise GpsError("命名地点已保存坐标系，无需再加 --coord-system；修改请重新保存并加 --replace")
            place = PlaceStore().get(args.latitude)
            latitude, longitude, system = place.latitude, place.longitude, place.coord_system
            print(f"使用地点：{place.name}")
        else:
            if args.longitude is None:
                raise GpsError("坐标需要同时提供纬度和经度；也可以输入已保存的地点名")
            latitude, longitude, system = args.latitude, args.longitude, args.coord_system or 'wgs84'
        try:
            target = to_wgs84(latitude, longitude, source=system)
        except ValueError as exc:
            raise GpsError(f"坐标转换失败：{exc}") from exc
        if args.dry_run or system == "gcj02":
            print(f"输入（{system.upper()}）：纬度 {latitude}，经度 {longitude}")
            print(f"提交目标（WGS84）：纬度 {target.latitude:.9f}，经度 {target.longitude:.9f}")
        if args.dry_run:
            print(f"设备：{args.device or '自动选择唯一 USB 设备'}")
            print("预演完成，未连接手机。")
            return 0
    if args.gps_command in ("status", "prepare"):
        operation = prepare_device if args.gps_command == "prepare" else check_device
        return print_readiness(await operation(args.device))
    async with GpsSession(args.device) as session:
        if args.gps_command == "clear":
            await session.clear_location()
        else:
            await session.set_location(target)
            print("定位请求已提交，请在手机地图中确认。保持连接中，按 Ctrl+C 清除并退出。", flush=True)
            await hold(session, args.duration)
    print("清除调用已完成，连接已关闭；未验证手机是否收到请求。手机位置恢复及地图刷新可能有延迟，请在手机上确认。")
    return 0
