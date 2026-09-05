"""
bundle_detector.py
-------------------
Decides, for every folder in the tree, whether it represents a single
application/game "bundle" (and should be treated as ONE item) or whether
it is just a normal folder full of unrelated files (whose contents should
each be analysed individually).

This is the piece that stops the analyzer from showing 500 separate
"junk" rows for the internal files of a single installed game.

The output is a nested tree of dicts (see `build_tree`) that the rest of
the app (analyzer.py, ui.py) walks over. Each node looks like:

    {
        "path": str,
        "name": str,
        "node_type": "file" | "bundle" | "folder",
        "category": str,          # e.g. "Game", "Document", ...
        "extension": str,         # files only
        "size": int,
        "created": float, "modified": float, "accessed": float,
        "why_bundle": [str, ...], # evidence used for the bundle decision
        "children": [node, ...],  # informational for bundles, actionable for folders
        "exe_files": [str, ...],  # bundles only -- used for "is it running" checks
    }
"""

import os

# --- Signature files/folders that strongly suggest a game/app bundle -----

UNITY_MARKERS = {"UnityPlayer.dll", "UnityCrashHandler64.exe", "MonoBleedingEdge"}
UNREAL_MARKERS = {"Engine", "Binaries", "Saved"}
ELECTRON_MARKERS = {"resources", "chrome_100_percent.pak", "icudtl.dat"}
DEV_PROJECT_MARKERS = {
    ".git", "package.json", "requirements.txt", "pyproject.toml",
    ".csproj", ".sln", "Cargo.toml", "go.mod", "node_modules",
}
CACHE_NAME_HINTS = {"cache", "temp", "tmp", "__pycache__", "logs", "crashdumps"}
INSTALLER_NAME_HINTS = {"setup", "install", "installer"}
INSTALLER_EXTENSIONS = {".msi", ".msix"}

EXECUTABLE_EXT = {".exe"}
LIBRARY_EXT = {".dll"}


def _lower_names(entries):
    return {e.name.lower() for e in entries}


def classify_folder(path, files, dirs):
    """Look at the immediate contents of a folder and decide whether the
    folder as a whole is a bundle, and if so what kind.

    Returns (is_bundle: bool, category: str, why: list[str], exe_files: list[str])
    """
    file_names = [f.name for f in files]
    file_names_lower = {n.lower() for n in file_names}
    dir_names_lower = {d.name.lower() for d in dirs}
    why = []

    exe_files = [f.name for f in files if f.name.lower().endswith(".exe")]
    dll_files = [f.name for f in files if f.name.lower().endswith(".dll")]

    folder_basename = os.path.basename(path.rstrip("\\/"))

    # --- Development project -------------------------------------------------
    dev_hits = DEV_PROJECT_MARKERS & (file_names_lower | dir_names_lower)
    if dev_hits:
        why.append(f"Contains project markers: {', '.join(sorted(dev_hits))}")
        return True, "Development project", why, exe_files

    # --- Unity game -------------------------------------------------------
    has_data_folder = any(d.name.endswith("_Data") for d in dirs)
    if has_data_folder and exe_files:
        why.append("Has a *_Data folder alongside an .exe (Unity engine layout)")
        return True, "Game", why, exe_files
    if UNITY_MARKERS & (file_names_lower | dir_names_lower):
        why.append("Contains Unity engine files (UnityPlayer.dll / MonoBleedingEdge)")
        return True, "Game", why, exe_files

    # --- Unreal Engine game ------------------------------------------------
    if len(UNREAL_MARKERS & dir_names_lower) >= 2:
        why.append("Has Engine/Binaries/Saved folders (Unreal Engine layout)")
        return True, "Game", why, exe_files

    # --- Electron desktop app ----------------------------------------------
    if exe_files and (ELECTRON_MARKERS & (file_names_lower | dir_names_lower)):
        why.append("Looks like an Electron-based desktop app (resources/*.pak)")
        return True, "Application", why, exe_files

    # --- Generic application: exe + supporting dlls together ---------------
    if exe_files and dll_files:
        why.append(f"Contains {len(exe_files)} executable(s) and {len(dll_files)} library file(s) together")
        return True, "Application", why, exe_files

    # --- Just an executable and little else --------------------------------
    if exe_files and len(files) <= 3 and not dirs:
        why.append("A small folder built around a single executable")
        return True, "Application", why, exe_files

    # --- Installer bundle (extracted installer files) -----------------------
    name_lower = folder_basename.lower()
    if any(h in name_lower for h in INSTALLER_NAME_HINTS) and (exe_files or files):
        why.append(f"Folder name suggests an installer ('{folder_basename}')")
        return True, "Installer", why, exe_files

    # --- Cache / temp data --------------------------------------------------
    if name_lower in CACHE_NAME_HINTS or any(h == name_lower for h in CACHE_NAME_HINTS):
        why.append(f"Folder name suggests cache/temporary data ('{folder_basename}')")
        return True, "Cache / temporary data", why, exe_files

    return False, None, why, exe_files


def classify_single_file(name, extension):
    """Rough category for a lone file, used when it's not part of a bundle."""
    ext = extension.lower()
    name_lower = name.lower()

    if ext in INSTALLER_EXTENSIONS or any(h in name_lower for h in INSTALLER_NAME_HINTS):
        return "Installer"
    if ext in {".zip", ".rar", ".7z", ".tar", ".gz"}:
        return "Archive"
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".mp4", ".mov", ".mp3", ".wav"}:
        return "Media"
    if ext in {".doc", ".docx", ".pdf", ".txt", ".xlsx", ".pptx", ".md"}:
        return "Documents"
    if ext in {".ini", ".cfg", ".conf", ".json", ".yaml", ".yml", ".xml"}:
        return "Configuration"
    if ext in {".log", ".tmp", ".bak", ".dmp"}:
        return "Cache / temporary data"
    if ext in {".exe", ".msi"}:
        return "Application"
    return "Unknown"


def _dir_totals(path):
    """Total size and file count of everything under `path` (for bundles)."""
    total_size = 0
    total_files = 0
    for current, _dirs, filenames in os.walk(path, onerror=lambda e: None):
        for fname in filenames:
            try:
                total_size += os.path.getsize(os.path.join(current, fname))
                total_files += 1
            except OSError:
                continue
    return total_size, total_files


def _mini_children(path, max_children=25):
    """A shallow, informational-only listing of a bundle's immediate
    contents, used purely for the "Expand" view in the UI -- these
    children are NOT individually actionable/deletable.
    """
    children = []
    try:
        with os.scandir(path) as it:
            for entry in sorted(it, key=lambda e: e.name.lower())[:max_children]:
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    size, _ = _dir_totals(entry.path)
                    children.append({
                        "path": entry.path, "name": entry.name, "node_type": "info",
                        "size": size, "children": [],
                    })
                else:
                    children.append({
                        "path": entry.path, "name": entry.name, "node_type": "info",
                        "size": st.st_size, "children": [],
                    })
    except OSError:
        pass
    return children


def build_tree(root_path, stop_event=None):
    """Build the actionable display tree for `root_path`.

    The ROOT itself is never an item -- its direct children become the
    top-level rows in the UI. Each child is classified recursively.
    """
    return [_analyze_entry(p) for p in _list_children(root_path)] if os.path.isdir(root_path) else []


def _list_children(path):
    try:
        with os.scandir(path) as it:
            return sorted(it, key=lambda e: e.name.lower())
    except OSError:
        return []


def _analyze_entry(entry):
    if entry.is_file(follow_symlinks=False):
        try:
            st = entry.stat(follow_symlinks=False)
        except OSError:
            return None
        ext = os.path.splitext(entry.name)[1].lower()
        return {
            "path": entry.path, "name": entry.name, "node_type": "file",
            "category": classify_single_file(entry.name, ext),
            "extension": ext, "size": st.st_size,
            "created": getattr(st, "st_ctime", st.st_mtime),
            "modified": st.st_mtime, "accessed": st.st_atime,
            "why_bundle": [], "children": [], "exe_files": [],
        }

    # Directory
    try:
        with os.scandir(entry.path) as it:
            children_entries = list(it)
    except OSError:
        return None
    files = [e for e in children_entries if e.is_file(follow_symlinks=False)]
    dirs = [e for e in children_entries if e.is_dir(follow_symlinks=False)]

    is_bundle, category, why, exe_files = classify_folder(entry.path, files, dirs)

    try:
        st = entry.stat(follow_symlinks=False)
        created = getattr(st, "st_ctime", st.st_mtime)
        modified = st.st_mtime
        accessed = st.st_atime
    except OSError:
        created = modified = accessed = 0

    if is_bundle:
        size, file_count = _dir_totals(entry.path)
        return {
            "path": entry.path, "name": entry.name, "node_type": "bundle",
            "category": category, "extension": "", "size": size,
            "file_count": file_count,
            "created": created, "modified": modified, "accessed": accessed,
            "why_bundle": why, "children": _mini_children(entry.path),
            "exe_files": [os.path.join(entry.path, e) for e in exe_files],
        }

    # Normal folder: recurse into children, each becomes its own actionable item
    child_nodes = [n for n in (_analyze_entry(c) for c in sorted(children_entries, key=lambda e: e.name.lower())) if n]
    size = sum(c["size"] for c in child_nodes)
    return {
        "path": entry.path, "name": entry.name, "node_type": "folder",
        "category": "Collection of files", "extension": "", "size": size,
        "created": created, "modified": modified, "accessed": accessed,
        "why_bundle": why, "children": child_nodes, "exe_files": [],
    }
