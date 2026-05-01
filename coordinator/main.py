"""
Hive Coordinator – Main FastAPI Application
Ties together: discovery, model watcher, metrics, router, and serves the
React dashboard as static files.
"""

import os
import socket
import asyncio
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from coordinator.config import settings
from coordinator.router import router
from coordinator.discovery import DiscoveryService
from coordinator.model_watcher import ModelWatcher
from coordinator.capacity import get_local_capacity
from coordinator import metrics as hive_metrics

# ── Shared state ─────────────────────────────────────────────────────────────

discovery_service = DiscoveryService()
known_nodes: dict = {}
rpc_workers: dict = {}  # name -> "ip:port" for RPC endpoints
model_watcher: ModelWatcher | None = None
inference_server = None


def on_node_discovered(node_data: dict):
    name = node_data["name"]
    known_nodes[name] = node_data
    props = node_data.get("properties", {})
    role = props.get("role", "")
    rpc_port = props.get("rpc_port", "50052")
    addr = node_data["address"]
    print(f"[Discovery] Node joined: {name} @ {addr}:{node_data['port']} (role={role})")

    # Track RPC workers
    if role == "worker":
        endpoint = f"{addr}:{rpc_port}"
        rpc_workers[name] = endpoint
        print(f"[Discovery] RPC worker registered: {endpoint} (total: {len(rpc_workers)})")


def on_node_lost(name: str):
    if name in known_nodes:
        del known_nodes[name]
    if name in rpc_workers:
        del rpc_workers[name]
        print(f"[Discovery] RPC worker removed: {name} (remaining: {len(rpc_workers)})")
    print(f"[Discovery] Node left: {name}")


def get_rpc_endpoints() -> list:
    """Get the current list of RPC worker endpoints."""
    return list(rpc_workers.values())


# ── Background task: periodic hardware refresh ───────────────────────────────

async def hardware_refresh_loop():
    """Refresh local hardware metrics every 5 seconds."""
    while True:
        try:
            local = get_local_capacity()
            hive_metrics.update_node_metrics([local])
        except Exception as e:
            print(f"[Metrics] Refresh error: {e}")
        await asyncio.sleep(5)


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global model_watcher, inference_server

    hostname = socket.gethostname()
    local = get_local_capacity()

    print(f"\n{'='*60}")
    print(f"  [*] HIVE COORDINATOR  -  {hostname}")
    print(f"{'='*60}")
    print(f"  VRAM : {local.vram_total_mb:,} MB  ({len(local.gpus)} GPU(s))")
    print(f"  RAM  : {local.ram_total_mb:,} MB")
    print(f"  Usable memory : {local.usable_memory_mb:,} MB")
    print(f"  API  : http://0.0.0.0:{settings.coordinator_port}")
    print(f"  UI   : http://localhost:{settings.coordinator_port}")
    print(f"{'='*60}\n")

    # Start mDNS (async)
    props = {
        "vram": str(local.vram_total_mb),
        "ram": str(local.ram_total_mb),
        "role": "coordinator",
    }
    await discovery_service.start_broadcasting(
        f"hive-{hostname}", settings.coordinator_port, props
    )
    await discovery_service.start_listening(on_node_discovered, on_node_lost)

    # Start model watcher
    model_dir = os.path.expanduser(settings.model_dir)
    model_watcher = ModelWatcher(model_dir)
    model_watcher.start()

    # Start inference server
    from coordinator.inference import InferenceServer
    from coordinator.binary_manager import get_binary_path, ensure_binaries
    
    # Auto-download llama.cpp binaries if not present
    await ensure_binaries()
    
    llama_bin = get_binary_path("llama-server")
    inference_server = InferenceServer(str(llama_bin), port=settings.inference_port)
    # We don't start the model yet since we need the user to pick one, 
    # but the server instance is ready.

    # Start background hardware refresh
    refresh_task = asyncio.create_task(hardware_refresh_loop())

    yield

    # Shutdown
    refresh_task.cancel()
    if inference_server:
        inference_server.stop()
    model_watcher.stop()
    await discovery_service.stop()
    print("\n[Hive] Coordinator stopped.\n")


# ── App factory ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Hive – Distributed Local AI Inference",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: allow the Vite dev server and the built dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(router)

# Serve React dashboard (production build)
ui_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "dist")
if os.path.isdir(ui_dist):
    app.mount("/", StaticFiles(directory=ui_dist, html=True), name="ui")


# ── Direct execution ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "coordinator.main:app",
        host="0.0.0.0",
        port=settings.coordinator_port,
        reload=True,
    )
