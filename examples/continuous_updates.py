"""Exercise three location updates over one GPS session.

Run from the project root:
    uv run python examples/continuous_updates.py --dry-run
    uv run python examples/continuous_updates.py
"""

import argparse
import asyncio
import math
import sys

from iphone_gps.api import Coordinate, DeviceDisconnectedError, GpsError, GpsSession

POINTS = (
    Coordinate(28.2282, 112.9388),
    Coordinate(28.2302, 112.9408),
    Coordinate(28.2322, 112.9428),
)


def positive_seconds(value):
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("间隔必须是秒数") from exc
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("间隔必须是正的有限秒数")
    return number


async def update_locations(session, interval):
    for index, point in enumerate(POINTS, 1):
        await session.set_location(point)
        print(f"[{index}/{len(POINTS)}] 已提交：{point.latitude}, {point.longitude}；保持 {interval:g} 秒。", flush=True)
        await asyncio.sleep(interval)


async def run(args):
    session = GpsSession(device=args.device)
    try:
        async with session:
            print("已建立一个 GPS 会话，接下来连续更新三个坐标。请在手机地图中观察，Ctrl+C 可提前退出。", flush=True)
            updates = asyncio.create_task(update_locations(session, args.interval))
            disconnected = asyncio.create_task(session.wait_disconnected())
            try:
                done, _ = await asyncio.wait((updates, disconnected), return_when=asyncio.FIRST_COMPLETED)
                # Prefer reporting a disconnect if both tasks finish together.
                if disconnected in done:
                    disconnected.result()
                updates.result()
            finally:
                for task in (updates, disconnected):
                    task.cancel()
                await asyncio.gather(updates, disconnected, return_exceptions=True)
        return 0
    except asyncio.CancelledError as exc:
        print("测试已取消，已尝试清理会话。", file=sys.stderr)
        for note in getattr(exc, "__notes__", ()):
            print(note, file=sys.stderr)
        return 130
    except DeviceDisconnectedError as exc:
        print(f"测试因断线停止：{exc}", file=sys.stderr)
        for note in getattr(exc, "__notes__", ()):
            print(note, file=sys.stderr)
        return 1
    except (GpsError, TimeoutError) as exc:
        print(f"测试失败：{str(exc) or '设备操作超时，请检查 USB 及开发者隧道'}", file=sys.stderr)
        for note in getattr(exc, "__notes__", ()):
            print(note, file=sys.stderr)
        return 1
    finally:
        result = session.cleanup_result
        if result is not None:
            if result.cleared and result.released:
                print("清除调用已完成，连接已关闭；未验证手机是否收到请求。", flush=True)
            elif result.clear_skipped:
                print("设备已断开，未发送清除请求；手机定位恢复情况需在手机上确认。", file=sys.stderr)
                if result.released:
                    print("本地连接资源已释放。", flush=True)
            elif result.errors:
                print("清理未完全成功；离线时无法保证清除定位。", file=sys.stderr)
            print("手机位置恢复及地图刷新可能有延迟，请在手机上确认。", flush=True)


def main():
    parser = argparse.ArgumentParser(description="同一 GPS 会话连续更新三个长沙附近坐标，结束后清除")
    parser.add_argument("--device", metavar="UDID", help="多设备时指定 USB 设备")
    parser.add_argument("--interval", type=positive_seconds, default=10.0, help="每个坐标保持的秒数，默认 10")
    parser.add_argument("--dry-run", action="store_true", help="只显示坐标，不连接手机")
    args = parser.parse_args()
    if args.dry_run:
        for index, point in enumerate(POINTS, 1):
            print(f"[{index}/{len(POINTS)}] {point.latitude}, {point.longitude}；保持 {args.interval:g} 秒")
        print("预演完成，未连接手机。")
        return 0
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
