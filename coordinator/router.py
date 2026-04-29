"""
Hive Coordinator – FastAPI Router
All HTTP endpoints: OpenAI-compatible inference API, cluster management
API consumed by the React dashboard, and Prometheus metrics.
"""

import json
import time
import os
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from typing import List, Optional

from coordinator.config import settings
from coordinator import rpc_client
from coordinator import metrics as hive_metrics
from coordinator.capacity import (
    get_local_capacity,
    classify_model,
    get_cluster_usable_memory,
    MODEL_STATUS_AVAILABLE,
    MODEL_STATUS_DOWNLOADABLE,
    MODEL_STATUS_LOCKED,
)
from coordinator.shard_planner import plan_shards

router = APIRouter()


# ── Pydantic models ──────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    stream: Optional[bool] = False
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 1024


# ── OpenAI-compatible inference endpoints ────────────────────────────────────

@router.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """Proxy chat completions to Ollama (single-node) or workers (multi-node)."""
    try:
        if request.stream:
            generator = rpc_client.chat_completion_stream(
                model=request.model,
                messages=request.messages,
                temperature=request.temperature or 0.7,
                max_tokens=request.max_tokens or 1024,
            )
            return StreamingResponse(generator, media_type="text/event-stream")
        else:
            data = await rpc_client.chat_completion(
                model=request.model,
                messages=request.messages,
                temperature=request.temperature or 0.7,
                max_tokens=request.max_tokens or 1024,
            )
            return data
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Ollama is not running. Start it with `ollama serve`.",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/v1/models")
async def openai_list_models():
    """OpenAI-compatible model listing."""
    ollama_models = await rpc_client.ollama_list_models()
    return {
        "object": "list",
        "data": [
            {
                "id": m.get("name", m.get("model", "unknown")),
                "object": "model",
                "owned_by": "ollama",
                "permission": [],
            }
            for m in ollama_models
        ],
    }


# ── Cluster / Dashboard API ─────────────────────────────────────────────────

@router.get("/api/health")
async def health():
    ollama_ok = await rpc_client.ollama_health_check()
    return {
        "status": "healthy",
        "ollama_connected": ollama_ok,
        "timestamp": time.time(),
    }


@router.get("/api/cluster/status")
async def cluster_status():
    """Full cluster snapshot consumed by the dashboard."""
    from coordinator.main import known_nodes, model_watcher

    # Build node list: always include self
    local = get_local_capacity()
    nodes = [local]

    # Add any discovered remote nodes (stored as raw dicts)
    for _name, nd in known_nodes.items():
        props = nd.get("properties", {})
        nodes.append(
            type(local)(
                hostname=nd.get("name", "remote"),
                address=nd.get("address", "?"),
                role=props.get("role", "worker"),
                ram_total_mb=int(props.get("ram", 0)),
                os_name="Remote",
                last_seen=time.time(),
            )
        )

    # Cluster-wide usable memory
    cluster_mem = get_cluster_usable_memory(nodes)

    # Model registry + classification
    registry_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "models", "registry.json"
    )
    registry = []
    if os.path.exists(registry_path):
        with open(registry_path) as f:
            registry = json.load(f)

    local_ggufs = model_watcher.gguf_files if model_watcher else []
    classified = []
    for m in registry:
        status = classify_model(m, cluster_mem, local_ggufs)
        classified.append({**m, "status": status})

    # Ollama models (always available)
    ollama_models = await rpc_client.ollama_list_models()
    ollama_running = await rpc_client.ollama_running_models()
    ollama_ok = await rpc_client.ollama_health_check()

    # Update prometheus
    hive_metrics.update_node_metrics(nodes)

    return {
        "cluster": {
            "node_count": len(nodes),
            "total_vram_mb": sum(n.vram_total_mb for n in nodes),
            "total_ram_mb": sum(n.ram_total_mb for n in nodes),
            "usable_memory_mb": cluster_mem,
            "ollama_connected": ollama_ok,
        },
        "nodes": [n.to_dict() for n in nodes],
        "registry_models": classified,
        "ollama_models": [
            {
                "name": m.get("name", m.get("model", "")),
                "size": m.get("size", 0),
                "modified_at": m.get("modified_at", ""),
                "digest": m.get("digest", ""),
                "details": m.get("details", {}),
            }
            for m in ollama_models
        ],
        "running_models": [
            {
                "name": m.get("name", m.get("model", "")),
                "size": m.get("size", 0),
                "vram": m.get("size_vram", 0),
                "expires_at": m.get("expires_at", ""),
            }
            for m in ollama_running
        ],
    }


@router.get("/api/cluster/nodes")
async def cluster_nodes():
    """List all nodes with hardware details."""
    from coordinator.main import known_nodes

    local = get_local_capacity()
    nodes = [local.to_dict()]
    for _name, nd in known_nodes.items():
        nodes.append(nd)
    return {"nodes": nodes}


@router.get("/api/cluster/models")
async def cluster_models():
    """List all Ollama-installed models."""
    models = await rpc_client.ollama_list_models()
    return {"models": models}


@router.get("/api/cluster/shard-plan")
async def shard_plan_preview(model: str = "qwen3.5", params: str = "8B"):
    """Preview how layers would be distributed."""
    from coordinator.main import known_nodes

    local = get_local_capacity()
    nodes = [local]
    plan = plan_shards(nodes, model, params)
    return plan.to_dict()


@router.get("/api/cluster/workers")
async def cluster_workers():
    """List all RPC workers and their endpoints."""
    from coordinator.main import rpc_workers, known_nodes

    workers = []
    for name, endpoint in rpc_workers.items():
        nd = known_nodes.get(name, {})
        props = nd.get("properties", {})
        workers.append({
            "name": name,
            "endpoint": endpoint,
            "address": nd.get("address", "?"),
            "gpu": props.get("gpu", "Unknown"),
            "vram_mb": int(props.get("vram", 0)),
            "ram_mb": int(props.get("ram", 0)),
        })
    return {"workers": workers, "total": len(workers)}


# ── Prometheus metrics endpoint ──────────────────────────────────────────────

@router.get("/metrics")
async def prometheus_metrics():
    return Response(
        content=hive_metrics.get_metrics_text(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
