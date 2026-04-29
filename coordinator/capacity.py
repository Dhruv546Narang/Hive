"""
Hive Capacity System
Detects local hardware (GPU VRAM, system RAM), calculates cluster-wide
usable memory, and classifies models as Available / Downloadable / Locked.
"""

import subprocess
import platform
import json
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict
from coordinator.config import settings


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GPUInfo:
    index: int = 0
    name: str = "Unknown"
    vram_total_mb: int = 0
    vram_used_mb: int = 0
    vram_free_mb: int = 0
    temperature_c: int = 0
    utilization_pct: int = 0


@dataclass
class NodeCapacity:
    hostname: str = ""
    address: str = "127.0.0.1"
    role: str = "worker"
    gpus: List[GPUInfo] = field(default_factory=list)
    ram_total_mb: int = 0
    ram_used_mb: int = 0
    ram_free_mb: int = 0
    os_name: str = ""
    last_seen: float = 0.0

    @property
    def vram_total_mb(self) -> int:
        return sum(g.vram_total_mb for g in self.gpus)

    @property
    def vram_free_mb(self) -> int:
        return sum(g.vram_free_mb for g in self.gpus)

    @property
    def usable_memory_mb(self) -> int:
        """Total usable memory: VRAM + RAM * offload_factor."""
        return self.vram_total_mb + int(self.ram_free_mb * settings.offload_factor)

    def to_dict(self) -> dict:
        return {
            "hostname": self.hostname,
            "address": self.address,
            "role": self.role,
            "gpus": [
                {
                    "index": g.index,
                    "name": g.name,
                    "vram_total_mb": g.vram_total_mb,
                    "vram_used_mb": g.vram_used_mb,
                    "vram_free_mb": g.vram_free_mb,
                    "temperature_c": g.temperature_c,
                    "utilization_pct": g.utilization_pct,
                }
                for g in self.gpus
            ],
            "ram_total_mb": self.ram_total_mb,
            "ram_used_mb": self.ram_used_mb,
            "ram_free_mb": self.ram_free_mb,
            "vram_total_mb": self.vram_total_mb,
            "vram_free_mb": self.vram_free_mb,
            "usable_memory_mb": self.usable_memory_mb,
            "os": self.os_name,
            "last_seen": self.last_seen,
        }


# ---------------------------------------------------------------------------
# Hardware detection
# ---------------------------------------------------------------------------

def get_gpu_info() -> List[GPUInfo]:
    """Detect NVIDIA GPUs via nvidia-smi."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,memory.free,temperature.gpu,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []

        gpus: List[GPUInfo] = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 7:
                gpus.append(
                    GPUInfo(
                        index=int(parts[0]),
                        name=parts[1],
                        vram_total_mb=int(float(parts[2])),
                        vram_used_mb=int(float(parts[3])),
                        vram_free_mb=int(float(parts[4])),
                        temperature_c=int(float(parts[5])),
                        utilization_pct=int(float(parts[6])),
                    )
                )
        return gpus
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def get_ram_info() -> Tuple[int, int, int]:
    """Return (total_mb, used_mb, free_mb) for system RAM."""
    if platform.system() == "Windows":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            total = stat.ullTotalPhys // (1024 * 1024)
            free = stat.ullAvailPhys // (1024 * 1024)
            return (int(total), int(total - free), int(free))
        except Exception:
            pass
    else:
        # Linux / macOS
        try:
            with open("/proc/meminfo") as f:
                lines = f.readlines()
            info: Dict[str, int] = {}
            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1])  # kB
            total = info.get("MemTotal", 0) // 1024
            free = info.get("MemAvailable", info.get("MemFree", 0)) // 1024
            return (total, total - free, free)
        except Exception:
            pass

    return (16384, 8192, 8192)  # safe fallback


def get_local_capacity() -> NodeCapacity:
    """Build a NodeCapacity snapshot for this machine."""
    import socket

    gpus = get_gpu_info()
    ram_total, ram_used, ram_free = get_ram_info()

    return NodeCapacity(
        hostname=socket.gethostname(),
        address="127.0.0.1",
        role="coordinator",
        gpus=gpus,
        ram_total_mb=ram_total,
        ram_used_mb=ram_used,
        ram_free_mb=ram_free,
        os_name=platform.system(),
        last_seen=time.time(),
    )


# ---------------------------------------------------------------------------
# Model classification
# ---------------------------------------------------------------------------

MODEL_STATUS_AVAILABLE = "available"
MODEL_STATUS_DOWNLOADABLE = "downloadable"
MODEL_STATUS_LOCKED = "locked"


def estimate_model_memory_mb(params_billions: float) -> int:
    """Q4_K_M rule of thumb: ~0.5 GB per 1B params → convert to MB."""
    return int(params_billions * 512)


def classify_model(
    model_meta: dict,
    cluster_usable_mb: int,
    local_gguf_files: List[str],
) -> str:
    """Return 'available', 'downloadable', or 'locked'."""
    required_mb = model_meta.get("vram_gb", 0) * 1024
    if required_mb == 0:
        required_mb = estimate_model_memory_mb(
            float(model_meta.get("params", "0").replace("B", ""))
        )

    if required_mb > cluster_usable_mb:
        return MODEL_STATUS_LOCKED

    # Check if any local GGUF matches this model's id pattern
    model_id = model_meta.get("id", "").lower()
    for path in local_gguf_files:
        basename = os.path.basename(path).lower()
        if model_id.replace("-", "") in basename.replace("-", ""):
            return MODEL_STATUS_AVAILABLE

    return MODEL_STATUS_DOWNLOADABLE


def get_cluster_usable_memory(nodes: List[NodeCapacity]) -> int:
    """Sum usable memory across all nodes."""
    return sum(n.usable_memory_mb for n in nodes)
