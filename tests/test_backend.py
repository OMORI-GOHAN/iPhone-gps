"""Run with the optional device extra to verify the pinned library boundary."""
import asyncio
import importlib.util
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from iphone_gps.api import BackendError, Coordinate, Device, DeviceError, DeviceDisconnectedError
from iphone_gps.backends.pymobiledevice import PymobiledeviceBackend, PymobiledeviceConnection, Resources


@unittest.skipUnless(importlib.util.find_spec('pymobiledevice3'), 'optional device dependency absent')
class BackendTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.backend = PymobiledeviceBackend()
        self.device = Device('test-device')
        self.lockdown = SimpleNamespace(
            paired=True, product_version='27.0', has_developer_mode=True,
            all_values={'DeviceName': 'Test iPhone'}, get_developer_mode_status=AsyncMock(return_value=True),
            close=AsyncMock())
        self.mounter = SimpleNamespace(is_image_mounted=AsyncMock(return_value=True))
        self.mounter_context = AsyncMock()
        self.mounter_context.__aenter__.return_value = self.mounter

    async def test_usb_discovery_filters_network_and_deduplicates(self):
        devices = [SimpleNamespace(serial='usb', is_usb=True), SimpleNamespace(serial='wifi', is_usb=False),
                   SimpleNamespace(serial='usb', is_usb=True)]
        with patch('pymobiledevice3.usbmux.list_devices', AsyncMock(return_value=devices)):
            self.assertEqual(await self.backend.list_devices(), [Device('usb')])

    async def test_reveal_only_displays_toggle_and_releases_usb_connection(self):
        amfi = SimpleNamespace(reveal_developer_mode_option_in_ui=AsyncMock(),
                               enable_developer_mode=AsyncMock(),
                               enable_developer_mode_post_restart=AsyncMock())
        with patch('pymobiledevice3.lockdown.create_using_usbmux', AsyncMock(return_value=self.lockdown)) as create, \
             patch('pymobiledevice3.services.amfi.AmfiService', return_value=amfi), \
             patch('pymobiledevice3.services.mobile_image_mounter.auto_mount', AsyncMock()) as mount, \
             patch.object(self.backend, '_remote') as remote:
            await self.backend.reveal_developer_mode(self.device)
        self.assertTrue(create.call_args.kwargs['autopair'])
        amfi.reveal_developer_mode_option_in_ui.assert_awaited_once()
        amfi.enable_developer_mode.assert_not_awaited()
        amfi.enable_developer_mode_post_restart.assert_not_awaited()
        self.lockdown.close.assert_awaited_once()
        mount.assert_not_awaited()
        remote.assert_not_called()

    async def test_check_does_not_pair_or_mount(self):
        with patch('pymobiledevice3.lockdown.create_using_usbmux', AsyncMock(return_value=self.lockdown)) as create, \
             patch('pymobiledevice3.services.mobile_image_mounter.MobileImageMounterService', return_value=self.mounter_context), \
             patch('pymobiledevice3.services.mobile_image_mounter.auto_mount', AsyncMock()) as mount, \
             patch('pymobiledevice3.tunneld.api.get_tunneld_tunnels', AsyncMock(return_value={'test-device': [{}]})):
            status = await self.backend.check(self.device)
        self.assertTrue(status.ready)
        self.assertFalse(create.call_args.kwargs['autopair'])
        mount.assert_not_called()
        self.lockdown.close.assert_awaited_once()

    async def test_unpaired_reports_next_action(self):
        self.lockdown.paired = False
        with patch('pymobiledevice3.lockdown.create_using_usbmux', AsyncMock(return_value=self.lockdown)):
            status = await self.backend.check(self.device)
        self.assertFalse(status.ready)
        self.assertIsNone(status.developer_mode)
        self.assertIn('信任', status.issues[0])

    async def test_modern_connection_reused_and_resources_closed(self):
        rsd = SimpleNamespace(udid='test-device', connect=AsyncMock(), close=AsyncMock())
        dvt = SimpleNamespace(connect=AsyncMock(), close=AsyncMock(),
                              dtx=SimpleNamespace(wait_disconnected=AsyncMock()))
        location = SimpleNamespace(connect=AsyncMock(), close=AsyncMock(), set=AsyncMock(), clear=AsyncMock())
        with patch('pymobiledevice3.lockdown.create_using_usbmux', AsyncMock(return_value=self.lockdown)), \
             patch('pymobiledevice3.services.mobile_image_mounter.MobileImageMounterService', return_value=self.mounter_context), \
             patch('pymobiledevice3.tunneld.api.get_tunneld_tunnels', AsyncMock(return_value={
                 'test-device': [{'tunnel-address': '::1', 'tunnel-port': 123}]})), \
             patch('pymobiledevice3.remote.remote_service_discovery.RemoteServiceDiscoveryService', return_value=rsd), \
             patch('pymobiledevice3.services.dvt.instruments.dvt_provider.DvtProvider', return_value=dvt) as provider, \
             patch('pymobiledevice3.services.dvt.instruments.location_simulation.LocationSimulation', return_value=location):
            connection = await self.backend.connect(self.device)
            await connection.set_location(Coordinate(1, 2))
            await connection.set_location(Coordinate(3, 4))
            await connection.clear_location()
            await connection.close()
        provider.assert_called_once_with(rsd)
        self.assertEqual(location.set.await_count, 2)
        for resource in (location, dvt, rsd, self.lockdown):
            resource.close.assert_awaited_once()

    async def test_partial_connect_failure_releases_all_resources(self):
        self.lockdown.product_version = '15.0'
        self.lockdown.has_developer_mode = False
        dvt = SimpleNamespace(connect=AsyncMock(side_effect=OSError('offline')), close=AsyncMock())
        with patch('pymobiledevice3.lockdown.create_using_usbmux', AsyncMock(return_value=self.lockdown)), \
             patch('pymobiledevice3.services.mobile_image_mounter.MobileImageMounterService', return_value=self.mounter_context), \
             patch('pymobiledevice3.services.dvt.instruments.dvt_provider.DvtProvider', return_value=dvt):
            with self.assertRaises(BackendError) as raised:
                await self.backend.connect(self.device)
        self.assertIsInstance(raised.exception.__cause__, OSError)
        dvt.close.assert_awaited_once()
        self.lockdown.close.assert_awaited_once()

    async def test_tunnel_identity_must_match_usb(self):
        rsd = SimpleNamespace(udid='wrong-device', connect=AsyncMock(), close=AsyncMock())
        from iphone_gps.backends.pymobiledevice import resources_scope
        with patch('pymobiledevice3.tunneld.api.get_tunneld_tunnels', AsyncMock(return_value={
                 'test-device': [{'tunnel-address': '::1', 'tunnel-port': 123}]})), \
             patch('pymobiledevice3.remote.remote_service_discovery.RemoteServiceDiscoveryService', return_value=rsd):
            with self.assertRaises(DeviceError):
                async with resources_scope() as resources:
                    await self.backend._remote(self.device, resources)
        rsd.close.assert_awaited_once()

    async def test_prepare_explicitly_pairs_and_mounts(self):
        self.lockdown.product_version = '15.0'
        self.lockdown.has_developer_mode = False
        with patch('pymobiledevice3.lockdown.create_using_usbmux', AsyncMock(return_value=self.lockdown)) as create, \
             patch('pymobiledevice3.services.mobile_image_mounter.MobileImageMounterService', return_value=self.mounter_context), \
             patch('pymobiledevice3.services.mobile_image_mounter.auto_mount', AsyncMock()) as mount:
            status = await self.backend.prepare(self.device)
        self.assertTrue(status.ready)
        self.assertTrue(create.call_args.kwargs['autopair'])
        mount.assert_awaited_once_with(self.lockdown)

    async def test_prepare_requires_manual_developer_mode(self):
        self.lockdown.get_developer_mode_status.return_value = False
        with patch('pymobiledevice3.lockdown.create_using_usbmux', AsyncMock(return_value=self.lockdown)), \
             patch('pymobiledevice3.services.mobile_image_mounter.auto_mount', AsyncMock()) as mount:
            with self.assertRaises(DeviceError):
                await self.backend.prepare(self.device)
        mount.assert_not_called()
        self.lockdown.close.assert_awaited_once()

    async def test_cancel_partial_open_releases_resources(self):
        self.lockdown.product_version = '15.0'
        self.lockdown.has_developer_mode = False
        started = asyncio.Event()

        async def connect():
            started.set()
            await asyncio.Event().wait()

        dvt = SimpleNamespace(connect=connect, close=AsyncMock())
        with patch('pymobiledevice3.lockdown.create_using_usbmux', AsyncMock(return_value=self.lockdown)), \
             patch('pymobiledevice3.services.mobile_image_mounter.MobileImageMounterService', return_value=self.mounter_context), \
             patch('pymobiledevice3.services.dvt.instruments.dvt_provider.DvtProvider', return_value=dvt):
            task = asyncio.create_task(self.backend.connect(self.device))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        dvt.close.assert_awaited_once()
        self.lockdown.close.assert_awaited_once()

    async def test_usb_detach_detected_while_transport_stays_open(self):
        transport_cancelled = asyncio.Event()

        async def wait_transport():
            try:
                await asyncio.Event().wait()
            finally:
                transport_cancelled.set()

        dvt = SimpleNamespace(dtx=SimpleNamespace(wait_disconnected=wait_transport))
        location = SimpleNamespace(set=AsyncMock(), clear=AsyncMock())
        connection = PymobiledeviceConnection(Resources(), dvt, location, self.device)
        # Wi-Fi visibility of the same phone must not count as a USB connection.
        network_device = SimpleNamespace(is_usb=False, matches_udid=lambda udid: True)
        with patch('pymobiledevice3.usbmux.list_devices', AsyncMock(return_value=[network_device])):
            with self.assertRaisesRegex(DeviceDisconnectedError, 'USB'):
                await asyncio.wait_for(connection.wait_disconnected(), 1)
        self.assertTrue(transport_cancelled.is_set())
        with self.assertRaises(DeviceDisconnectedError):
            await connection.clear_location()
        with self.assertRaises(DeviceDisconnectedError):
            await connection.set_location(Coordinate(1, 2))
        location.clear.assert_not_awaited()
        location.set.assert_not_awaited()

    async def test_usb_monitor_error_is_not_reported_as_detach(self):
        dvt = SimpleNamespace(dtx=SimpleNamespace(wait_disconnected=asyncio.Event().wait))
        connection = PymobiledeviceConnection(Resources(), dvt, SimpleNamespace(), self.device)
        with patch('pymobiledevice3.usbmux.list_devices', AsyncMock(side_effect=OSError('usbmuxd failed'))):
            with self.assertRaisesRegex(BackendError, '监测失败'):
                await asyncio.wait_for(connection.wait_disconnected(), 1)
        self.assertFalse(connection._disconnected)

    async def test_usbmuxd_exit_after_detach_uses_host_inventory(self):
        from pymobiledevice3.exceptions import ConnectionFailedToUsbmuxdError
        dvt = SimpleNamespace(dtx=SimpleNamespace(wait_disconnected=asyncio.Event().wait))
        connection = PymobiledeviceConnection(Resources(), dvt, SimpleNamespace(), self.device)
        os_utils = SimpleNamespace(usb_devices_seen_by_host=lambda: [])
        with patch('pymobiledevice3.usbmux.list_devices', AsyncMock(side_effect=ConnectionFailedToUsbmuxdError())), \
             patch('pymobiledevice3.osu.os_utils.get_os_utils', return_value=os_utils):
            with self.assertRaisesRegex(DeviceDisconnectedError, 'USB 设备断开'):
                await asyncio.wait_for(connection.wait_disconnected(), 1)
        self.assertTrue(connection._disconnected)

    async def test_usbmuxd_exit_with_phone_present_is_monitor_failure(self):
        from pymobiledevice3.exceptions import ConnectionFailedToUsbmuxdError
        for inventory in ([SimpleNamespace(serial='testdevice')], None):
            with self.subTest(inventory=inventory):
                dvt = SimpleNamespace(dtx=SimpleNamespace(wait_disconnected=asyncio.Event().wait))
                connection = PymobiledeviceConnection(Resources(), dvt, SimpleNamespace(), self.device)
                os_utils = SimpleNamespace(usb_devices_seen_by_host=lambda: inventory)
                with patch('pymobiledevice3.usbmux.list_devices', AsyncMock(side_effect=ConnectionFailedToUsbmuxdError())), \
                     patch('pymobiledevice3.osu.os_utils.get_os_utils', return_value=os_utils):
                    with self.assertRaisesRegex(BackendError, 'ConnectionFailedToUsbmuxdError'):
                        await asyncio.wait_for(connection.wait_disconnected(), 1)
                self.assertFalse(connection._disconnected)
