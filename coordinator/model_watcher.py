"""
Hive Model Watcher
Uses watchdog to monitor ~/hive/models/ for new GGUF files.
Maintains a live inventory of locally-available models.
"""

import os
import threading
import time
from typing import List, Set, Callable, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileDeletedEvent


class GGUFHandler(FileSystemEventHandler):
    """Watches for .gguf file additions/removals."""

    def __init__(self, on_change: Callable[[], None]):
        super().__init__()
        self.on_change = on_change

    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith(".gguf"):
            print(f"[ModelWatcher] New GGUF detected: {os.path.basename(event.src_path)}")
            self.on_change()

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.lower().endswith(".gguf"):
            print(f"[ModelWatcher] GGUF removed: {os.path.basename(event.src_path)}")
            self.on_change()

    def on_moved(self, event):
        if not event.is_directory:
            if event.dest_path.lower().endswith(".gguf"):
                print(f"[ModelWatcher] GGUF moved in: {os.path.basename(event.dest_path)}")
                self.on_change()
            elif event.src_path.lower().endswith(".gguf"):
                print(f"[ModelWatcher] GGUF moved out: {os.path.basename(event.src_path)}")
                self.on_change()


class ModelWatcher:
    def __init__(self, model_dir: str):
        self.model_dir = os.path.expanduser(model_dir)
        self._gguf_files: List[str] = []
        self._observer: Optional[Observer] = None
        self._lock = threading.Lock()

        # Ensure directory exists
        os.makedirs(self.model_dir, exist_ok=True)

        # Initial scan
        self._scan()

    def _scan(self):
        """Scan the model directory for GGUF files."""
        with self._lock:
            self._gguf_files = []
            if os.path.isdir(self.model_dir):
                for fname in os.listdir(self.model_dir):
                    if fname.lower().endswith(".gguf"):
                        self._gguf_files.append(
                            os.path.join(self.model_dir, fname)
                        )
            print(f"[ModelWatcher] Found {len(self._gguf_files)} GGUF file(s) in {self.model_dir}")

    @property
    def gguf_files(self) -> List[str]:
        with self._lock:
            return list(self._gguf_files)

    def start(self):
        """Start the filesystem watcher."""
        handler = GGUFHandler(on_change=self._scan)
        self._observer = Observer()
        self._observer.schedule(handler, self.model_dir, recursive=False)
        self._observer.daemon = True
        self._observer.start()
        print(f"[ModelWatcher] Watching {self.model_dir} for GGUF changes...")

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            print("[ModelWatcher] Stopped.")
