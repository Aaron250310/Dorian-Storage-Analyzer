"""
process_checker.py
-------------------
Answers two safety-critical questions:

  1. Is this application/game bundle currently running?
  2. Is this path one of Windows' protected system locations that we
     should never scan into or recommend for deletion?

Checking "is every single file open right now" for tens of thousands of
files would be far too slow (see scanner.py's performance notes), so we
only do the (relatively cheap) running-process check for bundle roots,
which is what actually matters for safety -- we never want to recommend
deleting a game or app that is currently open.
"""

import ntpath as winpath  # This app targets Windows; use Windows path rules
                            # explicitly so protected-path checks are correct
                            # regardless of the host OS running the code.
import os

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is in requirements.txt
    psutil = None


# Locations that must never be scanned into or offered for deletion.
PROTECTED_PATH_FRAGMENTS = [
    r"c:\windows",
    r"c:\windows\system32",
    r"c:\windows\syswow64",
    r"c:\$recycle.bin",
    r"c:\boot",
    r"c:\program files\windowsapps",
    r"c:\programdata\microsoft\windows",
]


def _norm(path):
    return winpath.normcase(winpath.normpath(str(path)))


def is_protected_path(path):
    """True if `path` is (or is inside) a critical Windows system location."""
    normalized = _norm(path)
    # Never allow a drive root itself (e.g. "C:\\").
    drive, tail = winpath.splitdrive(normalized)
    if drive and tail in ("", "\\", "/"):
        return True
    for fragment in PROTECTED_PATH_FRAGMENTS:
        frag = _norm(fragment)
        if normalized == frag or normalized.startswith(frag + "\\"):
            return True
    return False


class ProcessChecker:
    """Caches the list of currently-running executable paths for the
    duration of a scan, so we don't re-query the OS for every bundle.
    """

    def __init__(self):
        self._running_exe_paths = set()
        self._running_exe_names = set()
        self.refresh()

    def refresh(self):
        self._running_exe_paths = set()
        self._running_exe_names = set()
        if psutil is None:
            return
        for proc in psutil.process_iter(["exe", "name"]):
            try:
                exe = proc.info.get("exe")
                name = proc.info.get("name")
                if exe:
                    self._running_exe_paths.add(_norm(exe))
                if name:
                    self._running_exe_names.add(name.lower())
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

    def is_bundle_running(self, bundle_path, exe_files):
        """True if any process currently running has its executable
        inside this bundle's folder, or matches one of the bundle's
        known executable filenames.
        """
        normalized_bundle = _norm(bundle_path) + "\\"
        for exe_path in self._running_exe_paths:
            if exe_path.startswith(normalized_bundle):
                return True
        exe_names = {os.path.basename(e).lower() for e in exe_files}
        return bool(exe_names & self._running_exe_names)

    def is_file_running(self, file_path):
        return _norm(file_path) in self._running_exe_paths
