"""
Hive Worker Daemon
Announces itself over mDNS, reports hardware stats,
and (when multi-node is enabled) runs the llama.cpp rpc-server.
"""

import asyncio
import socket
from coordinator.config import settings
from coordinator.discovery import DiscoveryService
from coordinator.capacity import get_local_capacity
from worker.rpc_server import RPCServer


async def async_main():
    hostname = socket.gethostname()
    local = get_local_capacity()
    local.role = "worker"

    discovery_service = DiscoveryService()
    rpc_server = RPCServer(port=settings.worker_port)

    node_name = f"hive-worker-{hostname}"
    properties = {
        "vram": str(local.vram_total_mb),
        "ram": str(local.ram_total_mb),
        "role": "worker",
    }

    print(f"\n{'='*60}")
    print(f"  🐝  HIVE WORKER  –  {hostname}")
    print(f"{'='*60}")
    print(f"  VRAM : {local.vram_total_mb:,} MB  ({len(local.gpus)} GPU(s))")
    print(f"  RAM  : {local.ram_total_mb:,} MB")
    print(f"  Port : {settings.worker_port}")
    print(f"{'='*60}\n")

    await discovery_service.start_broadcasting(node_name, settings.worker_port, properties)

    try:
        while True:
            await asyncio.sleep(5)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n[Worker] Shutting down...")
    finally:
        rpc_server.stop()
        await discovery_service.stop()


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
