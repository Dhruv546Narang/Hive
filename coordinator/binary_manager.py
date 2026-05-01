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

# Binaries we need (rpc-server has no llama- prefix in releases)
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
    """Query GitHub API for the latest release download URLs.
    Returns (tag_name, main_binary_url, cuda_dll_url_or_None).
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

    # Find the matching main binary asset (must start with 'llama-')
    candidates = []
    cuda_dll_url = None
    for asset in assets:
        name = asset.get("name", "")
        url = asset.get("browser_download_url", "")
        if pattern in name and name.endswith(ext) and name.startswith("llama-"):
            candidates.append((name, url))
        # Also find the CUDA runtime DLLs zip
        if name.startswith("cudart-") and name.endswith(ext) and pattern.replace("bin-", "") in name:
            cuda_dll_url = url

    if not candidates:
        # Fallback: try Vulkan (works without CUDA toolkit)
        fallback_pattern = pattern.replace("cuda-12", "vulkan")
        for asset in assets:
            name = asset.get("name", "")
            url = asset.get("browser_download_url", "")
            if fallback_pattern in name and name.endswith(ext) and name.startswith("llama-"):
                candidates.append((name, url))
        cuda_dll_url = None  # No CUDA DLLs needed for Vulkan

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

    return tag, best[1], cuda_dll_url


async def _download_file(url: str, dest: Path, on_progress=None):
    """Download a file with progress callback."""
    if dest.exists():
        return
    async with httpx.AsyncClient(follow_redirects=True) as client:
        async with client.stream("GET", url, timeout=300.0) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes(8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_progress and total > 0:
                        on_progress(downloaded, total)


def _extract_archive(archive_path: Path, extract_dir: Path):
    """Extract zip or tar.gz."""
    name = archive_path.name
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(extract_dir)
    elif name.endswith(".tar.gz"):
        with tarfile.open(archive_path, "r:gz") as tf:
            tf.extractall(extract_dir)


def _copy_from_extract(extract_dir: Path) -> list:
    """Copy required binaries and DLLs from extract dir to BIN_DIR."""
    found = []
    for root, dirs, files in os.walk(extract_dir):
        for fname in files:
            base = fname.replace(".exe", "")
            if base in REQUIRED_BINS:
                src = Path(root) / fname
                dst = BIN_DIR / fname
                shutil.copy2(src, dst)
                if platform.system() != "Windows":
                    os.chmod(dst, 0o755)
                found.append(base)
                print(f"[BinaryManager] Installed: {fname}")
            elif fname.endswith((".dll", ".so", ".dylib")):
                src = Path(root) / fname
                dst = BIN_DIR / fname
                if not dst.exists():
                    shutil.copy2(src, dst)
    return found


async def download_and_extract(
    url: str,
    tag: str,
    cuda_dll_url: str = None,
    on_progress=None,
    on_status=None,
) -> Path:
    """Download release archive(s) and extract binaries to BIN_DIR."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Download main binary archive
    archive_name = url.split("/")[-1]
    archive_path = CACHE_DIR / archive_name
    await _download_file(url, archive_path, on_progress=on_progress)

    # Download CUDA DLLs separately if needed
    if cuda_dll_url:
        cuda_name = cuda_dll_url.split("/")[-1]
        cuda_path = CACHE_DIR / cuda_name
        if not cuda_path.exists():
            if on_status:
                on_status("Downloading CUDA runtime DLLs...")
            await _download_file(cuda_dll_url, cuda_path)

    # Extract main archive
    extract_dir = CACHE_DIR / "extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir()

    _extract_archive(archive_path, extract_dir)
    found = _copy_from_extract(extract_dir)

    # Extract CUDA DLLs if downloaded
    if cuda_dll_url:
        cuda_name = cuda_dll_url.split("/")[-1]
        cuda_path = CACHE_DIR / cuda_name
        if cuda_path.exists():
            cuda_extract = CACHE_DIR / "extract_cuda"
            if cuda_extract.exists():
                shutil.rmtree(cuda_extract)
            cuda_extract.mkdir()
            _extract_archive(cuda_path, cuda_extract)
            _copy_from_extract(cuda_extract)
            shutil.rmtree(cuda_extract, ignore_errors=True)

    # Cleanup
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

    tag, url, cuda_url = await fetch_latest_release_url()

    if on_status:
        on_status(f"Downloading llama.cpp {tag}...")

    await download_and_extract(url, tag, cuda_dll_url=cuda_url, on_progress=on_progress, on_status=on_status)

    if on_status:
        on_status(f"llama.cpp {tag} installed to {BIN_DIR}")

    return BIN_DIR
