"""
Hive Shard Planner
Given a list of nodes and a model's layer count, assigns contiguous
layer slices to each node proportional to its available VRAM.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from coordinator.capacity import NodeCapacity


@dataclass
class ShardAssignment:
    hostname: str
    address: str
    port: int
    start_layer: int
    end_layer: int
    layer_count: int
    vram_allocated_mb: int


@dataclass
class ShardPlan:
    model_name: str
    total_layers: int
    assignments: List[ShardAssignment] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "model_name": self.model_name,
            "total_layers": self.total_layers,
            "assignments": [
                {
                    "hostname": a.hostname,
                    "address": a.address,
                    "port": a.port,
                    "start_layer": a.start_layer,
                    "end_layer": a.end_layer,
                    "layer_count": a.layer_count,
                    "vram_allocated_mb": a.vram_allocated_mb,
                }
                for a in self.assignments
            ],
            "error": self.error,
        }


# Approximate layer counts for popular architectures
MODEL_LAYER_COUNTS = {
    "7b": 32,
    "8b": 32,
    "13b": 40,
    "14b": 40,
    "30b": 60,
    "33b": 60,
    "34b": 60,
    "40b": 60,
    "47b": 56,  # Mixtral 8x7B
    "65b": 80,
    "70b": 80,
    "72b": 80,
    "405b": 126,
}


def estimate_layer_count(params_str: str) -> int:
    """Guess the number of transformer layers from parameter count."""
    cleaned = params_str.lower().replace("b", "").replace("~", "").strip()
    try:
        val = int(float(cleaned))
    except ValueError:
        return 32  # safe default

    # Find closest match
    closest_key = min(MODEL_LAYER_COUNTS.keys(), key=lambda k: abs(int(k.replace("b", "")) - val))
    return MODEL_LAYER_COUNTS[closest_key]


def plan_shards(
    nodes: List[NodeCapacity],
    model_name: str,
    params_str: str = "8B",
    total_layers: Optional[int] = None,
    worker_port: int = 8080,
) -> ShardPlan:
    """
    Distribute model layers across nodes proportional to VRAM.
    Single-node case: all layers go to the local machine.
    """
    if not nodes:
        return ShardPlan(
            model_name=model_name, total_layers=0, error="No nodes available"
        )

    if total_layers is None:
        total_layers = estimate_layer_count(params_str)

    # Total VRAM across the cluster
    total_vram = sum(n.vram_total_mb for n in nodes)
    if total_vram == 0:
        # CPU-only: distribute layers evenly
        total_vram = sum(max(n.ram_free_mb, 1) for n in nodes)
        vram_fn = lambda n: max(n.ram_free_mb, 1)
    else:
        vram_fn = lambda n: max(n.vram_total_mb, 1)

    assignments: List[ShardAssignment] = []
    current_layer = 0

    for i, node in enumerate(nodes):
        if i == len(nodes) - 1:
            # Last node gets all remaining layers
            layers_for_node = total_layers - current_layer
        else:
            share = vram_fn(node) / total_vram
            layers_for_node = max(1, round(total_layers * share))

        end_layer = min(current_layer + layers_for_node - 1, total_layers - 1)

        assignments.append(
            ShardAssignment(
                hostname=node.hostname,
                address=node.address,
                port=worker_port,
                start_layer=current_layer,
                end_layer=end_layer,
                layer_count=end_layer - current_layer + 1,
                vram_allocated_mb=vram_fn(node),
            )
        )
        current_layer = end_layer + 1

        if current_layer >= total_layers:
            break

    return ShardPlan(
        model_name=model_name,
        total_layers=total_layers,
        assignments=assignments,
    )
