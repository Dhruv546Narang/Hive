"""
Hive Worker Daemon
1. Auto-downloads llama.cpp binaries if needed
2. Starts rpc-server to expose local GPU(s)
3. Broadcasts itself via mDNS for coordinator discovery
"""

import asyncio
import socket
import sys
from coordinator.config import settings
from coordinator.discovery import DiscoveryService
from coordinator.capacity import get_local_capacity
from coordinator.binary_manager import ensure_binaries, get_binary_path
from worker.rpc_server import RPCServer


async def async_main():
    hostname = socket.gethostname()
    local = get_local_capacity()
    local.role = "worker"

    # ── Auto-download llama.cpp binaries ──
    print(f"\n{'='*60}")
    print(f"  🐼  HIVE WORKER  –  {hostname}")
    print(f"{'='*60}")

    def on_status(msg):
        print(f"  [setup] {msg}")

    def on_progress(downloaded, total):
        pct = downloaded * 100 // total
        bar = "█" * (pct // 2) + "░" * (50 - pct // 2)
        sys.stdout.write(f"\r  [{bar}] {pct}% ({downloaded // 1024 // 1024} MB)")
        sys.stdout.flush()
        if downloaded >= total:
            sys.stdout.write("\n")

    try:
        await ensure_binaries(on_progress=on_progress, on_status=on_status)
    except Exception as e:
        print(f"  ❌ Failed to download llama.cpp: {e}")
        print(f"  Please download manually to ~/.hive/bin/")
        return

    # ── Start RPC server ──
    rpc_binary = get_binary_path("rpc-server")
    rpc_server = RPCServer(
        port=settings.worker_port,
        binary_path=str(rpc_binary),
    )

    try:
        rpc_server.start(host="0.0.0.0", enable_cache=True)
    except Exception as e:
        print(f"  ❌ Failed to start rpc-server: {e}")
        return

    print(f"  VRAM : {local.vram_total_mb:,} MB  ({len(local.gpus)} GPU(s))")
    print(f"  RAM  : {local.ram_total_mb:,} MB")
    print(f"  RPC  : 0.0.0.0:{settings.worker_port}")
    print(f"{'='*60}\n")

    # ── Broadcast via mDNS ──
    discovery_service = DiscoveryService()
    node_name = f"hive-worker-{hostname}"
    properties = {
        "vram": str(local.vram_total_mb),
        "ram": str(local.ram_total_mb),
        "role": "worker",
        "rpc_port": str(settings.worker_port),
        "gpu": local.gpus[0].name if local.gpus else "CPU",
    }
    await discovery_service.start_broadcasting(
        node_name, settings.worker_port, properties
    )

    # ── Keep running ──
    try:
        while True:
            if not rpc_server.is_running:
                print("[Worker] rpc-server died, restarting...")
                try:
                    rpc_server.start(host="0.0.0.0", enable_cache=True)
                except Exception as e:
                    print(f"[Worker] Restart failed: {e}")
                    break
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
