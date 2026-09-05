"""
main.py
-------
Entry point. Wires together:

    scanner (raw filesystem walk + progress)
      -> analyzer (bundle detection + AI/rule-based scoring + memory)
      -> ui (Tkinter display, selection, deletion)

Run with:  python main.py
"""

import os

import scanner
import duplicate_detector
from analyzer import Analyzer
from ai_analyzer import AIAnalyzer
from deletion_manager import move_to_recycle_bin, permanently_delete
from memory import Memory
from ui import App

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "storage_memory.db")


class Controller:
    """The only thing the UI talks to. Owns all the non-UI state."""

    def __init__(self):
        self.memory = Memory(DB_PATH)
        self.ai_analyzer = AIAnalyzer(self.memory)
        self.analyzer = Analyzer(self.memory, self.ai_analyzer)

    def run_full_scan(self, folder_path, progress_callback, done_callback, error_callback,
                       cancelled_callback=None, stop_event=None):
        """Runs on a background thread (see ui.py). Reports progress via
        thread-safe callbacks and hands the final tree back to the UI.
        If `stop_event` gets set partway through, `cancelled_callback` is
        called instead of `done_callback`.
        """
        try:
            progress_callback("Scanning files...", 0)
            scanner.scan_folder(
                folder_path,
                progress_callback=lambda path, files, folders, pct: progress_callback(
                    f"Scanning ({files:,} files, {folders:,} folders): {os.path.basename(path)}", pct
                ),
                stop_event=stop_event,
            )

            def analysis_progress(message, pct):
                progress_callback(message, pct)

            tree, summary = self.analyzer.analyze_folder(
                folder_path, progress_callback=analysis_progress, stop_event=stop_event,
            )
            done_callback(tree, summary)
        except scanner.ScanCancelled:
            if cancelled_callback:
                cancelled_callback()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI as an error dialog
            error_callback(str(exc))

    def deep_scan_duplicates(self, node, progress_callback, done_callback, error_callback, stop_event):
        """Search the whole computer for other copies of a single file.
        Runs on a background thread. `done_callback` receives the match
        list, or None if the scan was cancelled.
        """
        try:
            matches = duplicate_detector.deep_scan_for_file(
                node["path"], progress_callback=progress_callback, stop_event=stop_event,
            )
            done_callback(matches)
        except duplicate_detector.DeepScanCancelled:
            done_callback(None)
        except Exception as exc:  # noqa: BLE001
            error_callback(str(exc))

    def delete_items(self, nodes, permanent=False):
        """Remove items (recycle bin by default, or permanently if
        `permanent=True`) and record the decision in memory -- including
        the item's name, category and fingerprint -- so future scans can
        recognize the same file/app if it shows up again elsewhere and
        can refer back to this decision when reasoning about it.
        Returns list of (path, ok, error).
        """
        results = permanently_delete(nodes) if permanent else move_to_recycle_bin(nodes)
        by_path = {n["path"]: n for n in nodes}
        for path, ok, _error in results:
            if ok:
                node = by_path[path]
                self.memory.record_decision(
                    path=path, name=node["name"], extension=node.get("extension", ""),
                    category=node.get("category", ""),
                    fingerprint=node.get("fingerprint"), decision="deleted",
                )
        return results


def main():
    controller = Controller()
    app = App(controller)
    app.mainloop()
    controller.memory.close()


if __name__ == "__main__":
    main()
