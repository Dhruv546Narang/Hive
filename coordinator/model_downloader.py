"""
Hive Model Downloader
Downloads GGUF models from Hugging Face into ~/.hive/models/.
Supports registry lookup (by friendly name) and direct HF repo URLs.
"""

import os
import sys
import json
import httpx
from pathlib import Path
from typing import Optional, List

MODELS_DIR = Path.home() / ".hive" / "models"
REGISTRY_PATH = Path(__file__).parent.parent / "models" / "registry.json"


def _load_registry() -> list:
    """Load the model registry."""
    if REGISTRY_PATH.exists():
        with open(REGISTRY_PATH) as f:
            return json.load(f)
    return []


def get_registry() -> list:
    return _load_registry()


def find_model(query: str) -> Optional[dict]:
    """Find a model in the registry by ID or partial name match."""
    registry = _load_registry()
    q = query.lower().strip()

    # Exact ID match
    for m in registry:
        if m["id"] == q:
            return m

    # Partial match
    for m in registry:
        if q in m["id"] or q in m["name"].lower():
            return m

    return None


def list_downloaded() -> List[dict]:
    """List all downloaded GGUF files."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    models = []
    for f in MODELS_DIR.iterdir():
        if f.suffix == ".gguf":
            size_gb = f.stat().st_size / (1024**3)
            models.append({
                "filename": f.name,
                "path": str(f),
                "size_gb": round(size_gb, 1),
            })
    return models


def is_downloaded(filename: str) -> bool:
    """Check if a model file already exists."""
    return (MODELS_DIR / filename).exists()


def get_model_path(filename: str) -> Path:
    """Get the full path for a model file."""
    return MODELS_DIR / filename


def _hf_download_url(repo: str, filename: str) -> str:
    """Build the HuggingFace download URL."""
    return f"https://huggingface.co/{repo}/resolve/main/{filename}"


async def download_model(
    repo: str,
    filename: str,
    on_progress=None,
    on_status=None,
) -> Path:
    """Download a GGUF model from Hugging Face.

    Args:
        repo: HF repo like "Qwen/Qwen2.5-7B-Instruct-GGUF"
        filename: GGUF file like "qwen2.5-7b-instruct-q4_k_m.gguf"
        on_progress: callback(downloaded_bytes, total_bytes)
        on_status: callback(status_message)

    Returns:
        Path to the downloaded file.
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    dest = MODELS_DIR / filename

    if dest.exists():
        if on_status:
            on_status(f"Model already exists: {dest}")
        return dest

    url = _hf_download_url(repo, filename)
    temp_dest = dest.with_suffix(".gguf.part")

    if on_status:
        on_status(f"Downloading {filename} from {repo}...")

    # Resume support: check if partial download exists
    resume_pos = 0
    if temp_dest.exists():
        resume_pos = temp_dest.stat().st_size
        if on_status:
            on_status(f"Resuming from {resume_pos / 1024**3:.1f} GB...")

    headers = {}
    if resume_pos > 0:
        headers["Range"] = f"bytes={resume_pos}-"

    async with httpx.AsyncClient(follow_redirects=True) as client:
        async with client.stream("GET", url, timeout=600.0, headers=headers) as resp:
            if resp.status_code == 416:
                # Range not satisfiable — file is complete
                temp_dest.rename(dest)
                return dest

            if resp.status_code not in (200, 206):
                raise RuntimeError(
                    f"Download failed: HTTP {resp.status_code} for {url}"
                )

            # Get total size
            if resp.status_code == 206:
                # Partial content — parse Content-Range
                cr = resp.headers.get("content-range", "")
                if "/" in cr:
                    total = int(cr.split("/")[-1])
                else:
                    total = resume_pos + int(resp.headers.get("content-length", 0))
            else:
                total = int(resp.headers.get("content-length", 0))
                resume_pos = 0  # Full download, reset

            mode = "ab" if resume_pos > 0 else "wb"
            downloaded = resume_pos

            with open(temp_dest, mode) as f:
                async for chunk in resp.aiter_bytes(65536):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress and total > 0:
                        on_progress(downloaded, total)

    # Rename to final path
    temp_dest.rename(dest)

    if on_status:
        on_status(f"Downloaded: {dest}")

    return dest


async def pull_model(
    query: str,
    on_progress=None,
    on_status=None,
) -> Optional[Path]:
    """Pull a model by registry ID or HF repo path.

    Examples:
        pull_model("qwen2.5-7b")           # registry lookup
        pull_model("Qwen/Qwen2.5-7B-...")   # direct HF repo
    """
    # Check if it's a direct HF repo/filename
    if "/" in query and not find_model(query):
        # Treat as HF repo — try to list files
        parts = query.split("/")
        if len(parts) >= 2:
            repo = "/".join(parts[:2])
            filename = parts[2] if len(parts) > 2 else None

            if not filename:
                # List GGUF files in the repo
                if on_status:
                    on_status(f"Looking up GGUF files in {repo}...")
                files = await list_hf_gguf_files(repo)
                if not files:
                    if on_status:
                        on_status(f"No GGUF files found in {repo}")
                    return None
                # Pick the Q4_K_M variant if available
                filename = _pick_best_quant(files)
                if on_status:
                    on_status(f"Selected: {filename}")

            return await download_model(
                repo, filename,
                on_progress=on_progress,
                on_status=on_status,
            )

    # Registry lookup
    model = find_model(query)
    if not model:
        if on_status:
            on_status(f"Model '{query}' not found in registry. Try: hive models")
        return None

    return await download_model(
        model["repo"],
        model["filename"],
        on_progress=on_progress,
        on_status=on_status,
    )


async def list_hf_gguf_files(repo: str) -> List[str]:
    """List GGUF files in a HuggingFace repo."""
    api_url = f"https://huggingface.co/api/models/{repo}"
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            r = await client.get(api_url, timeout=15.0)
            r.raise_for_status()
            data = r.json()
            siblings = data.get("siblings", [])
            return [
                s["rfilename"] for s in siblings
                if s.get("rfilename", "").endswith(".gguf")
            ]
    except Exception:
        return []


def _pick_best_quant(files: List[str]) -> str:
    """Pick the best quantization from available files."""
    # Preference order
    prefs = ["Q4_K_M", "Q4_K_S", "Q5_K_M", "Q4_0", "Q8_0"]
    for pref in prefs:
        for f in files:
            if pref.lower() in f.lower():
                return f
    # Fallback: smallest file
    return files[0]
