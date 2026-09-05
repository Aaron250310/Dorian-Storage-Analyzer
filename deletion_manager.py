"""
deletion_manager.py
--------------------
The only module allowed to actually remove anything.

Two removal modes are supported:

  * "trash" (default, and the one the UI recommends): moves the item to
    the Windows Recycle Bin via send2trash. Fully reversible.
  * "permanent": actually removes the file/folder from disk with
    os.remove / shutil.rmtree. NOT reversible. The UI requires a second,
    more explicit confirmation before this path is ever used.

Both modes run through the same `can_delete` safety check first
(protected paths, currently-running items, unknown items), and every
call here should already have passed through an explicit user
confirmation in the UI.
"""

import os
import shutil

from process_checker import is_protected_path

try:
    from send2trash import send2trash
except ImportError:  # pragma: no cover
    send2trash = None


class DeletionError(Exception):
    pass


def can_delete(node):
    """Pre-flight safety check for a single node. Returns (ok, reason)."""
    if is_protected_path(node["path"]):
        return False, "This is a protected system location and cannot be deleted."
    if node.get("is_running"):
        return False, "This is currently running and cannot be safely deleted."
    if node.get("category") == "Unknown" and node.get("status") not in (
        "Probably unnecessary", "Likely junk",
    ):
        return False, "Not enough information to safely recommend deleting this."
    return True, None


def move_to_recycle_bin(nodes):
    """Move each node's path to the Recycle Bin.

    Returns a list of (path, success: bool, error: str|None).
    """
    if send2trash is None:
        return [(n["path"], False, "send2trash is not installed (see requirements.txt).")
                for n in nodes]

    results = []
    for node in nodes:
        ok, reason = can_delete(node)
        if not ok:
            results.append((node["path"], False, reason))
            continue
        try:
            send2trash(node["path"])
            results.append((node["path"], True, None))
        except Exception as exc:  # noqa: BLE001 - surface any OS error to the UI
            results.append((node["path"], False, str(exc)))
    return results


def permanently_delete(nodes):
    """Permanently remove each node's path from disk. NOT reversible --
    the caller (ui.py) must have already obtained an explicit,
    unambiguous confirmation from the user before calling this.

    Returns a list of (path, success: bool, error: str|None).
    """
    results = []
    for node in nodes:
        ok, reason = can_delete(node)
        if not ok:
            results.append((node["path"], False, reason))
            continue
        path = node["path"]
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            results.append((path, True, None))
        except Exception as exc:  # noqa: BLE001 - surface any OS error to the UI
            results.append((path, False, str(exc)))
    return results
