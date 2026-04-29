"""
Hive Worker – RPC Server Wrapper
Wraps the llama.cpp rpc-server binary.
In v1 single-node mode this is a stub; the coordinator
talks directly to Ollama instead.
"""

import subprocess
import threading
import os
from typing import Optional


class RPCServer:
    """Manages a llama.cpp rpc-server child process."""

    def __init__(self, port: int = 8080, model_path: Optional[str] = None):
        self.port = port
        self.model_path = model_path
        self._process: Optional[subprocess.Popen] = None

    def start(self, layers_start: int = 0, layers_end: int = -1):
        """
        Start the rpc-server.  In a real multi-node setup this would launch:
            llama-rpc-server --port <port> --model <path> --ngl <layers>
        For now this is a stub that logs intent.
        """
        print(
            f"[RPCServer] Would start llama.cpp rpc-server on port {self.port} "
            f"(layers {layers_start}-{layers_end})"
        )
        if not self.model_path or not os.path.exists(str(self.model_path)):
            print("[RPCServer] No model path set or file missing — skipping launch.")
            return

        # Placeholder for real launch:
        # cmd = [
        #     "llama-rpc-server",
        #     "--port", str(self.port),
        #     "--model", self.model_path,
        #     "--ngl", str(layers_end - layers_start + 1),
        # ]
        # self._process = subprocess.Popen(cmd)

    def stop(self):
        if self._process:
            self._process.terminate()
            self._process.wait(timeout=10)
            self._process = None
            print("[RPCServer] Stopped.")

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None
