"""
Hive Worker – RPC Server
Manages the llama.cpp rpc-server child process.
The rpc-server exposes local GPU(s) as remote compute devices
that the coordinator's llama-server can offload layers to.
"""

import subprocess
import threading
import sys
import os
import time
from typing import Optional
from pathlib import Path


class RPCServer:
    """Manages a llama.cpp rpc-server child process."""

    DEFAULT_PORT = 50052

    def __init__(self, port: int = DEFAULT_PORT, binary_path: Optional[str] = None):
        self.port = port
        self.binary_path = binary_path  # path to rpc-server binary
        self._process: Optional[subprocess.Popen] = None
        self._log_thread: Optional[threading.Thread] = None
        self._stopping = False

    def start(self, host: str = "0.0.0.0", enable_cache: bool = True):
        """
        Start the rpc-server binary.
        - host: bind address (0.0.0.0 for LAN access)
        - enable_cache: use local tensor cache (-c) for faster reloads
        """
        if self._process and self._process.poll() is None:
            print(f"[RPCServer] Already running on port {self.port}")
            return

        if not self.binary_path:
            raise FileNotFoundError("rpc-server binary path not set")

        binary = Path(self.binary_path)
        if not binary.exists():
            raise FileNotFoundError(f"rpc-server binary not found: {binary}")

        cmd = [
            str(binary),
            "-H", host,
            "-p", str(self.port),
        ]
        if enable_cache:
            cmd.append("-c")

        # Set environment for the binary (add bin dir to PATH for DLLs)
        env = os.environ.copy()
        bin_dir = str(binary.parent)
        if sys.platform == "win32":
            env["PATH"] = bin_dir + ";" + env.get("PATH", "")
        else:
            env["LD_LIBRARY_PATH"] = bin_dir + ":" + env.get("LD_LIBRARY_PATH", "")

        print(f"[RPCServer] Starting: {' '.join(cmd)}")
        self._stopping = False
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            bufsize=1,
            universal_newlines=True,
        )

        # Log output in background
        self._log_thread = threading.Thread(
            target=self._read_output, daemon=True
        )
        self._log_thread.start()

        # Give it a moment to start
        time.sleep(1.0)
        if self._process.poll() is not None:
            raise RuntimeError(
                f"rpc-server exited immediately with code {self._process.returncode}"
            )

        print(f"[RPCServer] Running on {host}:{self.port} (PID {self._process.pid})")

    def _read_output(self):
        """Read and print subprocess output."""
        try:
            for line in self._process.stdout:
                if self._stopping:
                    break
                line = line.rstrip()
                if line:
                    print(f"[rpc-server] {line}")
        except (ValueError, OSError):
            pass  # Process closed

    def stop(self):
        """Stop the rpc-server process."""
        self._stopping = True
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
            self._process = None
            print("[RPCServer] Stopped.")

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def endpoint(self) -> str:
        """Return the network endpoint for this rpc-server."""
        return f"0.0.0.0:{self.port}"
