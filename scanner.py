"""
scanner.py
----------
Recursively walks a folder and collects raw file-system metadata.

Design notes:
  * A quick first pass (cheap `os.scandir`, no per-file `stat()`) counts
    how many entries exist so the UI can show a real percentage instead
    of a spinner. On very large trees this first pass is still much
    cheaper than the full stat-collecting pass.
  * The second pass collects full metadata for every file and folder,
    calling `progress_callback` periodically so the UI thread can update
    without freezing.
  * This module only collects raw facts (name, size, timestamps, ...).
    It does NOT decide what is a "bundle" or what is "junk" -- that is
    bundle_detector.py and analyzer.py's job.
"""

import os
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileRecord:
    path: str
    name: str
    extension: str
    size: int
    created: float
    modified: float
    accessed: float
    parent: str


@dataclass
class ScanResult:
    root: str
    files: list = field(default_factory=list)   # list[FileRecord]
    folder_count: int = 0
    file_count: int = 0
    total_size: int = 0
    scan_time: float = 0.0


class ScanCancelled(Exception):
    pass


def _quick_count(root_path, stop_event=None):
    """Fast pass: count files/folders without calling stat() on each one."""
    files = 0
    folders = 0
    for _current, dirs, filenames in os.walk(root_path, onerror=lambda e: None):
        if stop_event is not None and stop_event.is_set():
            raise ScanCancelled()
        folders += 1
        files += len(filenames)
    return files, folders


def scan_folder(root_path, progress_callback=None, stop_event=None):
    """Recursively scan `root_path`.

    progress_callback(current_path, files_done, folders_done, percent) is
    called periodically (not on every single file, to keep it cheap).

    Returns a ScanResult.
    """
    start = time.time()
    root_path = str(Path(root_path))

    total_files, total_folders = _quick_count(root_path, stop_event)
    total_units = max(total_files + total_folders, 1)

    result = ScanResult(root=root_path)
    done_units = 0
    last_report = 0.0

    for current_dir, dirnames, filenames in os.walk(root_path, onerror=lambda e: None):
        if stop_event is not None and stop_event.is_set():
            raise ScanCancelled()

        result.folder_count += 1
        done_units += 1

        for fname in filenames:
            if stop_event is not None and stop_event.is_set():
                raise ScanCancelled()
            full_path = os.path.join(current_dir, fname)
            try:
                st = os.stat(full_path, follow_symlinks=False)
            except (OSError, PermissionError):
                continue

            record = FileRecord(
                path=full_path,
                name=fname,
                extension=os.path.splitext(fname)[1].lower(),
                size=st.st_size,
                created=getattr(st, "st_ctime", st.st_mtime),
                modified=st.st_mtime,
                accessed=st.st_atime,
                parent=current_dir,
            )
            result.files.append(record)
            result.file_count += 1
            result.total_size += st.st_size
            done_units += 1

            now = time.time()
            if progress_callback and (now - last_report > 0.05):
                percent = min(100, int(done_units / total_units * 100))
                progress_callback(full_path, result.file_count, result.folder_count, percent)
                last_report = now

    if progress_callback:
        progress_callback(root_path, result.file_count, result.folder_count, 100)

    result.scan_time = time.time() - start
    return result


def human_size(num_bytes):
    """Format a byte count as a human-readable string, e.g. '384 MB'."""
    if num_bytes is None:
        return "0 B"
    num = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(num)} {unit}"
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"
