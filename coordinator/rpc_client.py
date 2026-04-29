"""
Hive RPC Client
Wraps communication with llama.cpp rpc-server workers.
In single-node / Ollama-proxy mode this is a thin pass-through
to the local Ollama OpenAI-compatible API.
"""

import httpx
import json
import time
from typing import AsyncGenerator, Optional, Dict, Any
from coordinator.config import settings
from coordinator import metrics as hive_metrics


OLLAMA_BASE = "http://localhost:11434"


async def ollama_health_check() -> bool:
    """Check whether Ollama is reachable."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{OLLAMA_BASE}/", timeout=3.0)
            return r.status_code == 200
    except Exception:
        return False


async def ollama_list_models() -> list:
    """Query Ollama for locally-installed models."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{OLLAMA_BASE}/api/tags", timeout=5.0)
            if r.status_code == 200:
                data = r.json()
                return data.get("models", [])
    except Exception:
        pass
    return []


async def ollama_model_info(model_name: str) -> Optional[dict]:
    """Get details for a specific Ollama model."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{OLLAMA_BASE}/api/show",
                json={"name": model_name},
                timeout=10.0,
            )
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return None


async def ollama_running_models() -> list:
    """Get currently loaded/running models in Ollama."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{OLLAMA_BASE}/api/ps", timeout=5.0)
            if r.status_code == 200:
                data = r.json()
                return data.get("models", [])
    except Exception:
        pass
    return []


async def chat_completion(
    model: str,
    messages: list,
    stream: bool = False,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> Dict[str, Any]:
    """
    Send a non-streaming chat completion via Ollama's OpenAI compat endpoint.
    Returns the full response dict.
    """
    url = f"{OLLAMA_BASE}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content} if hasattr(m, 'role') else m for m in messages],
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "keep_alive": "30m",
    }

    start = time.time()
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload, timeout=120.0)
        r.raise_for_status()
        data = r.json()
    elapsed = time.time() - start

    # Estimate token count from response text length
    content = ""
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        pass
    token_estimate = max(1, len(content.split()))
    hive_metrics.record_inference(token_estimate, elapsed)

    return data


async def chat_completion_stream(
    model: str,
    messages: list,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> AsyncGenerator[bytes, None]:
    """
    Stream a chat completion via Ollama's OpenAI compat endpoint.
    Yields raw SSE bytes as they arrive.
    """
    url = f"{OLLAMA_BASE}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content} if hasattr(m, 'role') else m for m in messages],
        "stream": True,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "keep_alive": "30m",
    }

    start = time.time()
    token_count = 0

    async with httpx.AsyncClient() as client:
        async with client.stream("POST", url, json=payload, timeout=120.0) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                token_count += 1
                yield chunk

    elapsed = time.time() - start
    hive_metrics.record_inference(token_count, elapsed)
