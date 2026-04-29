"""
Hive Coordinator – Distributed Inference Server
Manages a llama-server instance that distributes model layers
across local GPU + remote RPC workers.

Flow:
1. Workers register via mDNS (each running rpc-server on port 50052)
2. Coordinator builds --rpc flag: "worker1:50052,worker2:50052"
3. Coordinator starts llama-server with the model + --rpc
4. llama-server auto-distributes layers proportional to VRAM
5. CLI/API talks to llama-server's OpenAI-compatible endpoint
"""

import asyncio
import subprocess
import threading
import sys
import os
import time
from typing import Optional, List, Dict
from pathlib import Path


class InferenceServer:
    """Manages a llama-server process for distributed inference."""

    DEFAULT_PORT = 8081  # OpenAI-compatible API port

    def __init__(self, binary_path: str, port: int = DEFAULT_PORT):
        self.binary_path = binary_path  # path to llama-server binary
        self.port = port
        self._process: Optional[subprocess.Popen] = None
        self._log_thread: Optional[threading.Thread] = None
        self._stopping = False
        self._ready = threading.Event()

        # State
        self.model_path: Optional[str] = None
        self.rpc_workers: List[str] = []  # ["ip:port", ...]
        self.gpu_layers: int = 99  # offload all layers to GPU by default

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def api_base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def set_workers(self, workers: List[str]):
        """Update the list of RPC worker endpoints."""
        self.rpc_workers = list(workers)

    def start(
        self,
        model_path: str,
        rpc_workers: Optional[List[str]] = None,
        ctx_size: int = 4096,
        gpu_layers: int = 99,
        threads: int = 0,
    ):
        """Start llama-server with the given model and RPC workers.

        Args:
            model_path: Path to GGUF model file
            rpc_workers: List of "ip:port" endpoints for remote GPUs
            ctx_size: Context window size
            gpu_layers: Number of layers to offload (-ngl)
            threads: CPU threads (0 = auto)
        """
        if self.is_running:
            print("[InferenceServer] Already running, stopping first...")
            self.stop()

        binary = Path(self.binary_path)
        if not binary.exists():
            raise FileNotFoundError(f"llama-server not found: {binary}")

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")

        self.model_path = model_path
        if rpc_workers:
            self.rpc_workers = rpc_workers
        self.gpu_layers = gpu_layers

        cmd = [
            str(binary),
            "-m", model_path,
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "-ngl", str(gpu_layers),
            "-c", str(ctx_size),
        ]

        if threads > 0:
            cmd.extend(["-t", str(threads)])

        # Add RPC workers
        if self.rpc_workers:
            rpc_str = ",".join(self.rpc_workers)
            cmd.extend(["--rpc", rpc_str])
            print(f"[InferenceServer] RPC workers: {rpc_str}")

        # Environment with bin dir in PATH
        env = os.environ.copy()
        bin_dir = str(binary.parent)
        if sys.platform == "win32":
            env["PATH"] = bin_dir + ";" + env.get("PATH", "")
        else:
            env["LD_LIBRARY_PATH"] = bin_dir + ":" + env.get("LD_LIBRARY_PATH", "")

        print(f"[InferenceServer] Starting: {' '.join(cmd)}")
        self._stopping = False
        self._ready.clear()

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            bufsize=1,
            universal_newlines=True,
        )

        self._log_thread = threading.Thread(
            target=self._read_output, daemon=True
        )
        self._log_thread.start()

    def _read_output(self):
        """Read subprocess output, detect when server is ready."""
        try:
            for line in self._process.stdout:
                if self._stopping:
                    break
                line = line.rstrip()
                if line:
                    print(f"[llama-server] {line}")
                    # Detect ready state
                    if "listening" in line.lower() or "server listening" in line.lower():
                        self._ready.set()
        except (ValueError, OSError):
            pass

    def wait_ready(self, timeout: float = 120.0) -> bool:
        """Wait for the server to be ready."""
        return self._ready.wait(timeout=timeout)

    def stop(self):
        """Stop the llama-server process."""
        self._stopping = True
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
            self._process = None
            self._ready.clear()
            print("[InferenceServer] Stopped.")

    async def restart_with_workers(self, workers: List[str]):
        """Restart the server with an updated worker list."""
        if not self.model_path:
            print("[InferenceServer] No model loaded, cannot restart")
            return
        self.stop()
        await asyncio.sleep(1)
        self.start(
            model_path=self.model_path,
            rpc_workers=workers,
            gpu_layers=self.gpu_layers,
        )

    def health_check(self) -> bool:
        """Check if the server is responding."""
        if not self.is_running:
            return False
        try:
            import httpx
            r = httpx.get(f"{self.api_base}/health", timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False
