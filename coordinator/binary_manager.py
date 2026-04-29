"""
Hive Binary Manager
Auto-downloads llama.cpp pre-built binaries (rpc-server, llama-server)
from GitHub releases. Stores them in ~/.hive/bin/.
"""

import os
import sys
import platform
import zipfile
import tarfile
import shutil
import httpx
from pathlib import Path
from typing import Optional

HIVE_HOME = Path.home() / ".hive"
BIN_DIR = HIVE_HOME / "bin"
CACHE_DIR = HIVE_HOME / "cache"

GITHUB_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"

# Binaries we need
REQUIRED_BINS = ["rpc-server", "llama-server", "llama-cli"]


def _get_platform_asset_pattern() -> str:
    """Return the release asset filename pattern for this OS/arch."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        if "arm" in machine or "aarch64" in machine:
            return "bin-win-cpu-arm64"
        # Prefer CUDA for NVIDIA GPUs
        return "bin-win-cuda-12"  # will match cuda-12.x

    elif system == "linux":
        if "aarch64" in machine or "arm" in machine:
            return "bin-ubuntu-arm64"
        return "bin-ubuntu-x64"

    elif system == "darwin":
        if "arm" in machine or "aarch64" in machine:
            return "bin-macos-arm64"
        return "bin-macos-x64"

    return "bin-ubuntu-x64"  # fallback


def _get_ext() -> str:
    return ".zip" if platform.system() == "Windows" else ".tar.gz"


def _bin_name(name: str) -> str:
    """Add .exe on Windows."""
    if platform.system() == "Windows":
        return name + ".exe"
    return name


def get_binary_path(name: str) -> Path:
    """Get path to a llama.cpp binary."""
    return BIN_DIR / _bin_name(name)


def binaries_exist() -> bool:
    """Check if all required binaries are downloaded."""
    return all(get_binary_path(b).exists() for b in REQUIRED_BINS)


def get_installed_version() -> Optional[str]:
    """Read the installed version tag."""
    ver_file = BIN_DIR / ".version"
    if ver_file.exists():
        return ver_file.read_text().strip()
    return None


def _save_version(tag: str):
    ver_file = BIN_DIR / ".version"
    ver_file.write_text(tag)


async def fetch_latest_release_url() -> tuple:
    """Query GitHub API for the latest release download URL.
    Returns (tag_name, download_url).
    """
    pattern = _get_platform_asset_pattern()
    ext = _get_ext()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.get(GITHUB_API, timeout=15.0, headers={
            "Accept": "application/vnd.github+json"
        })
        r.raise_for_status()
        data = r.json()

    tag = data.get("tag_name", "unknown")
    assets = data.get("assets", [])

    # Find the matching asset
    candidates = []
    for asset in assets:
        name = asset.get("name", "")
        url = asset.get("browser_download_url", "")
        if pattern in name and name.endswith(ext):
            candidates.append((name, url))

    if not candidates:
        # Fallback: try Vulkan (works without CUDA toolkit)
        fallback = "vulkan" if "cuda" in pattern else pattern
        for asset in assets:
            name = asset.get("name", "")
            url = asset.get("browser_download_url", "")
            if fallback in name and name.endswith(ext):
                candidates.append((name, url))

    if not candidates:
        raise RuntimeError(
            f"No matching release asset for pattern '{pattern}' + '{ext}'. "
            f"Available: {[a['name'] for a in assets[:10]]}"
        )

    # Prefer CUDA over Vulkan over CPU
    best = candidates[0]
    for name, url in candidates:
        if "cuda" in name.lower():
            best = (name, url)
            break

    return tag, best[1]


async def download_and_extract(
    url: str,
    tag: str,
    on_progress=None,
) -> Path:
    """Download a release archive and extract binaries to BIN_DIR."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    archive_name = url.split("/")[-1]
    archive_path = CACHE_DIR / archive_name

    # Download
    if not archive_path.exists():
        async with httpx.AsyncClient(follow_redirects=True) as client:
            async with client.stream("GET", url, timeout=300.0) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(archive_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if on_progress and total > 0:
                            on_progress(downloaded, total)

    # Extract
    extract_dir = CACHE_DIR / "extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir()

    if archive_name.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(extract_dir)
    elif archive_name.endswith(".tar.gz"):
        with tarfile.open(archive_path, "r:gz") as tf:
            tf.extractall(extract_dir)

    # Find and copy binaries
    found = []
    for root, dirs, files in os.walk(extract_dir):
        for fname in files:
            base = fname.replace(".exe", "")
            if base in REQUIRED_BINS:
                src = Path(root) / fname
                dst = BIN_DIR / fname
                shutil.copy2(src, dst)
                # Make executable on Unix
                if platform.system() != "Windows":
                    os.chmod(dst, 0o755)
                found.append(base)

    # Also copy DLLs/shared libs (CUDA runtime, etc.)
    for root, dirs, files in os.walk(extract_dir):
        for fname in files:
            if fname.endswith((".dll", ".so", ".dylib")):
                src = Path(root) / fname
                dst = BIN_DIR / fname
                if not dst.exists():
                    shutil.copy2(src, dst)

    # Cleanup extract dir
    shutil.rmtree(extract_dir, ignore_errors=True)

    _save_version(tag)

    missing = [b for b in REQUIRED_BINS if b not in found]
    if missing:
        print(f"[BinaryManager] Warning: missing binaries: {missing}")

    return BIN_DIR


async def ensure_binaries(on_progress=None, on_status=None) -> Path:
    """Ensure llama.cpp binaries are available. Downloads if needed.
    Returns the bin directory path.
    """
    if binaries_exist():
        ver = get_installed_version() or "unknown"
        if on_status:
            on_status(f"llama.cpp binaries ready ({ver})")
        return BIN_DIR

    if on_status:
        on_status("Fetching latest llama.cpp release info...")

    tag, url = await fetch_latest_release_url()

    if on_status:
        on_status(f"Downloading llama.cpp {tag}...")

    await download_and_extract(url, tag, on_progress=on_progress)

    if on_status:
        on_status(f"llama.cpp {tag} installed to {BIN_DIR}")

    return BIN_DIR
