"""
Hive Node Discovery
Uses AsyncZeroconf for mDNS broadcast and discovery inside the async event loop.
"""

import asyncio
import socket
from typing import Dict, Any, Callable, Optional
from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser, AsyncServiceInfo


SERVICE_TYPE = "_hive._tcp.local."


class DiscoveryService:
    def __init__(self):
        self._azc: Optional[AsyncZeroconf] = None
        self._browser: Optional[AsyncServiceBrowser] = None
        self._service_info: Optional[AsyncServiceInfo] = None
        self._on_discovered: Optional[Callable] = None
        self._on_lost: Optional[Callable] = None

    async def _ensure_zeroconf(self):
        if not self._azc:
            self._azc = AsyncZeroconf()

    async def start_broadcasting(self, name: str, port: int, properties: Dict[str, str]):
        hostname = socket.gethostname()
        try:
            local_ip = socket.gethostbyname(hostname)
        except socket.gaierror:
            local_ip = "127.0.0.1"

        await self._ensure_zeroconf()

        self._service_info = AsyncServiceInfo(
            SERVICE_TYPE,
            f"{name}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(local_ip)],
            port=port,
            properties={k: v.encode() for k, v in properties.items()},
            server=f"{hostname}.local.",
        )
        await self._azc.async_register_service(self._service_info)
        print(f"[Discovery] Broadcasting: {name} on {local_ip}:{port}")

    async def start_listening(
        self,
        on_discovered: Callable[[Dict[str, Any]], None],
        on_lost: Callable[[str], None],
    ):
        self._on_discovered = on_discovered
        self._on_lost = on_lost

        await self._ensure_zeroconf()

        self._browser = AsyncServiceBrowser(
            self._azc.zeroconf, SERVICE_TYPE, handlers=[self._on_state_change]
        )
        print(f"[Discovery] Listening for Hive nodes...")

    def _on_state_change(self, zeroconf, service_type, name, state_change):
        """Sync callback from the browser — schedule async lookup."""
        if state_change == ServiceStateChange.Removed:
            if self._on_lost:
                self._on_lost(name)
            return

        if state_change in (ServiceStateChange.Added, ServiceStateChange.Updated):
            asyncio.ensure_future(self._async_resolve(zeroconf, service_type, name))

    async def _async_resolve(self, zeroconf, service_type, name):
        """Resolve service info asynchronously (safe inside the event loop)."""
        try:
            info = AsyncServiceInfo(service_type, name)
            if await info.async_request(zeroconf, 3000):
                addresses = [socket.inet_ntoa(addr) for addr in info.addresses]
                if addresses and self._on_discovered:
                    node_data = {
                        "name": name,
                        "address": addresses[0],
                        "port": info.port,
                        "properties": {
                            k.decode(): v.decode()
                            for k, v in info.properties.items()
                        },
                    }
                    self._on_discovered(node_data)
        except Exception as e:
            print(f"[Discovery] Failed to resolve {name}: {e}")

    async def stop(self):
        if self._browser:
            await self._browser.async_cancel()
        if self._azc:
            if self._service_info:
                await self._azc.async_unregister_service(self._service_info)
            await self._azc.async_close()
        print("[Discovery] Stopped.")
