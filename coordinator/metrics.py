"""
Hive Prometheus Metrics
Exposes tok/s, VRAM usage, RAM usage, latency, and node count
as Prometheus gauges and counters.
"""

import time
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

# ---------------------------------------------------------------------------
# Gauges (current values)
# ---------------------------------------------------------------------------

NODE_COUNT = Gauge("hive_node_count", "Number of connected nodes in the cluster")
VRAM_TOTAL_MB = Gauge("hive_vram_total_mb", "Total VRAM across the cluster (MB)")
VRAM_USED_MB = Gauge("hive_vram_used_mb", "Used VRAM across the cluster (MB)")
RAM_TOTAL_MB = Gauge("hive_ram_total_mb", "Total RAM across the cluster (MB)")
RAM_USED_MB = Gauge("hive_ram_used_mb", "Used RAM across the cluster (MB)")
GPU_TEMP_C = Gauge("hive_gpu_temperature_celsius", "GPU temperature", ["gpu_index"])
GPU_UTIL_PCT = Gauge("hive_gpu_utilization_percent", "GPU utilization", ["gpu_index"])
ACTIVE_MODEL = Info("hive_active_model", "Currently loaded model")
TOKENS_PER_SEC = Gauge("hive_tokens_per_second", "Current inference tok/s")

# ---------------------------------------------------------------------------
# Counters (cumulative)
# ---------------------------------------------------------------------------

INFERENCE_REQUESTS = Counter(
    "hive_inference_requests_total", "Total inference requests processed"
)
TOKENS_GENERATED = Counter(
    "hive_tokens_generated_total", "Total tokens generated"
)

# ---------------------------------------------------------------------------
# Histograms (distributions)
# ---------------------------------------------------------------------------

INFERENCE_LATENCY = Histogram(
    "hive_inference_latency_seconds",
    "Inference request latency",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def update_node_metrics(nodes: list):
    """Refresh all node-derived gauges."""
    NODE_COUNT.set(len(nodes))

    total_vram = 0
    used_vram = 0
    total_ram = 0
    used_ram = 0

    for node in nodes:
        nd = node if isinstance(node, dict) else node.to_dict()
        total_vram += nd.get("vram_total_mb", 0)
        used_vram += nd.get("vram_total_mb", 0) - nd.get("vram_free_mb", 0)
        total_ram += nd.get("ram_total_mb", 0)
        used_ram += nd.get("ram_used_mb", 0)

        for gpu in nd.get("gpus", []):
            idx = str(gpu.get("index", 0))
            GPU_TEMP_C.labels(gpu_index=idx).set(gpu.get("temperature_c", 0))
            GPU_UTIL_PCT.labels(gpu_index=idx).set(gpu.get("utilization_pct", 0))

    VRAM_TOTAL_MB.set(total_vram)
    VRAM_USED_MB.set(used_vram)
    RAM_TOTAL_MB.set(total_ram)
    RAM_USED_MB.set(used_ram)


def record_inference(tokens: int, latency_s: float):
    """Record a completed inference request."""
    INFERENCE_REQUESTS.inc()
    TOKENS_GENERATED.inc(tokens)
    INFERENCE_LATENCY.observe(latency_s)
    if latency_s > 0:
        TOKENS_PER_SEC.set(tokens / latency_s)


def get_metrics_text() -> bytes:
    """Return Prometheus exposition format."""
    return generate_latest()
