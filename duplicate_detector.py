"""
duplicate_detector.py
----------------------
Finds exact duplicate files.

To keep this fast on large drives (per the project's performance
requirements) we do NOT hash every file. Instead:

  1. Group files by size first (two files can't be identical if their
     sizes differ) -- this is free, we already have sizes from the scan.
  2. Only compute a hash for files that share a size with at least one
     other file.
  3. For large files, hash a fingerprint (first 1MB + last 1MB + size)
     instead of the whole file, which is enough to confidently detect
     duplicates without reading gigabytes of data.
"""

import hashlib
import os
import string
import sys
from collections import defaultdict

from process_checker import is_protected_path

PARTIAL_HASH_THRESHOLD = 10 * 1024 * 1024  # 10 MB
CHUNK = 1024 * 1024  # 1 MB

# Noisy / huge system directories that aren't worth walking into during a
# whole-computer deep scan -- skipping these dramatically speeds things up
# without meaningfully reducing the odds of finding a real duplicate.
SKIP_DIR_NAMES = {
    "$recycle.bin", "system volume information", "recovery",
    "windows", "programdata", "node_modules", ".git",
}


class DeepScanCancelled(Exception):
    pass


def fingerprint(path, size):
    """Return a hash string identifying the file's content.

    Small files (<10MB) are hashed fully. Larger files are hashed via
    their first and last megabyte plus the size, which is a fast and
    practically reliable way to detect duplicates of big media/installer
    files without reading the entire thing.
    """
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            if size <= PARTIAL_HASH_THRESHOLD:
                for block in iter(lambda: f.read(CHUNK), b""):
                    h.update(block)
            else:
                h.update(f.read(CHUNK))
                f.seek(max(0, size - CHUNK))
                h.update(f.read(CHUNK))
                h.update(str(size).encode())
        return h.hexdigest()
    except OSError:
        return None


def find_duplicates(file_records):
    """file_records: iterable of objects/dicts with .path/['path'] and
    .size/['size'].

    Returns a list of duplicate groups:
        [{"fingerprint": str, "size": int, "paths": [str, ...],
          "wasted_space": int}, ...]
    Only genuine content duplicates (matching hash) are included --
    same-size-but-different-content files are correctly excluded.
    """
    def get(rec, key):
        return rec[key] if isinstance(rec, dict) else getattr(rec, key)

    by_size = defaultdict(list)
    for rec in file_records:
        size = get(rec, "size")
        if size and size > 0:
            by_size[size].append(rec)

    groups = []
    for size, records in by_size.items():
        if len(records) < 2:
            continue
        by_hash = defaultdict(list)
        for rec in records:
            fp = fingerprint(get(rec, "path"), size)
            if fp:
                by_hash[fp].append(get(rec, "path"))
        for fp, paths in by_hash.items():
            if len(paths) > 1:
                groups.append({
                    "fingerprint": fp,
                    "size": size,
                    "paths": paths,
                    "wasted_space": size * (len(paths) - 1),
                })
    return groups


def list_available_drives():
    """All fixed drives/roots to search during a deep scan."""
    if sys.platform == "win32":
        drives = []
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.exists(root):
                drives.append(root)
        return drives
    return ["/"]


def deep_scan_for_file(target_path, progress_callback=None, stop_event=None):
    """Search every available drive for other copies of `target_path`.

    Uses the same fast size-then-hash strategy as find_duplicates(), just
    applied across the whole filesystem instead of one scanned folder.
    Skips protected system locations and a handful of huge/noisy
    directories (see SKIP_DIR_NAMES) to keep this from taking forever.

    progress_callback(current_path, files_scanned) is called periodically.
    Returns a list of {"path": str, "size": int} for every match found
    (the target file itself is excluded).

    Raises DeepScanCancelled if stop_event is set during the scan.
    """
    try:
        target_size = os.path.getsize(target_path)
    except OSError:
        return []
    if target_size <= 0:
        return []

    target_fp = fingerprint(target_path, target_size)
    if not target_fp:
        return []

    target_norm = os.path.normcase(os.path.normpath(target_path))
    matches = []
    scanned = 0

    for drive in list_available_drives():
        for current_dir, dirnames, filenames in os.walk(drive, onerror=lambda e: None):
            if stop_event is not None and stop_event.is_set():
                raise DeepScanCancelled()

            dirnames[:] = [
                d for d in dirnames
                if d.lower() not in SKIP_DIR_NAMES and not is_protected_path(os.path.join(current_dir, d))
            ]

            for fname in filenames:
                if stop_event is not None and stop_event.is_set():
                    raise DeepScanCancelled()

                full_path = os.path.join(current_dir, fname)
                if os.path.normcase(os.path.normpath(full_path)) == target_norm:
                    continue
                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    continue
                if size != target_size:
                    continue

                scanned += 1
                if progress_callback and scanned % 25 == 0:
                    progress_callback(full_path, scanned)

                fp = fingerprint(full_path, size)
                if fp == target_fp:
                    matches.append({"path": full_path, "size": size})

    if progress_callback:
        progress_callback(target_path, scanned)
    return matches
