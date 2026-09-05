"""
analyzer.py
-----------
Ties everything together:

  scan -> build bundle/folder tree -> find duplicates -> for every
  actionable node: check memory, check running status, ask ai_analyzer
  for a score -> persist result back into memory -> hand a fully
  annotated tree + summary stats to the UI.

"Actionable" nodes are: files, bundle roots, and normal folders (which
are also individually recommendable, in addition to recursing into their
children). Bundle-internal children (see bundle_detector._mini_children)
are informational only and are not scored individually -- deleting a
bundle always means deleting the whole thing.
"""

import os
import time

import bundle_detector
import duplicate_detector
from process_checker import ProcessChecker, is_protected_path
from scanner import ScanCancelled


class Analyzer:
    def __init__(self, memory, ai_analyzer):
        self.memory = memory
        self.ai_analyzer = ai_analyzer
        self.process_checker = ProcessChecker()

    @staticmethod
    def _check_cancelled(stop_event):
        if stop_event is not None and stop_event.is_set():
            raise ScanCancelled()

    def analyze_folder(self, root_path, progress_callback=None, stop_event=None):
        """Full pipeline for a freshly scanned root folder.

        Returns (tree: list[node], summary: dict).
        Raises ScanCancelled if stop_event is set at any point.
        """
        self.process_checker.refresh()
        self.memory.mark_all_missing(root_path)

        if progress_callback:
            progress_callback("Building file/bundle structure...", 0)
        tree = bundle_detector.build_tree(root_path)
        self._check_cancelled(stop_event)

        if progress_callback:
            progress_callback("Looking for duplicate files...", 0)
        duplicate_paths = self._collect_duplicate_paths(tree)
        self._check_cancelled(stop_event)

        total_nodes = self._count_actionable(tree)
        state = {"done": 0}

        def visit(node):
            self._check_cancelled(stop_event)
            self._score_node(node, duplicate_paths)
            state["done"] += 1
            if progress_callback and total_nodes:
                pct = int(state["done"] / total_nodes * 100)
                progress_callback(f"Analyzing {node['name']}...", pct)
            if node["node_type"] == "folder":
                for child in node["children"]:
                    visit(child)

        for top_node in tree:
            visit(top_node)

        summary = self._build_summary(tree, duplicate_paths)
        return tree, summary

    # ------------------------------------------------------------------
    def _collect_duplicate_paths(self, tree):
        """Flatten all *file* nodes (recursively, excluding bundle
        internals) and run duplicate detection across them.
        """
        files = []

        def collect(node):
            if node["node_type"] == "file":
                files.append(node)
            elif node["node_type"] == "folder":
                for child in node["children"]:
                    collect(child)
            # bundles are treated as opaque units; their internals aren't
            # compared for cross-duplicate purposes.

        for top_node in tree:
            collect(top_node)

        groups = duplicate_detector.find_duplicates(files)
        duplicate_info = {}
        for group in groups:
            for path in group["paths"]:
                duplicate_info[path] = group
        return duplicate_info

    def _count_actionable(self, tree):
        count = 0
        for node in tree:
            count += 1
            if node["node_type"] == "folder":
                count += self._count_actionable(node["children"])
        return count

    def _score_node(self, node, duplicate_paths):
        if is_protected_path(node["path"]):
            node.update(importance=100, junk_probability=0, status="Keep",
                        reason="Protected system location.", why=["Protected system location."],
                        is_running=False, is_protected=True)
            return

        is_running = False
        if node["node_type"] == "bundle":
            is_running = self.process_checker.is_bundle_running(node["path"], node.get("exe_files", []))
        elif node["node_type"] == "file" and node["extension"] == ".exe":
            is_running = self.process_checker.is_file_running(node["path"])

        dup_info = duplicate_paths.get(node["path"])
        is_duplicate = dup_info is not None

        fingerprint = None
        if node["node_type"] == "file" and node["size"] > 0:
            fingerprint = dup_info["fingerprint"] if dup_info else None

        previous = self.memory.get_item_by_path(node["path"])
        related = self.memory.find_similar_elsewhere(
            node["path"], node["name"], node.get("extension", ""), node["size"], fingerprint
        )
        related_decision = None
        if related:
            related_decision = self.memory.get_last_decision_for_identity(
                node["name"], node.get("extension", ""), fingerprint
            )

        decision_bias = self.memory.get_decision_bias(node["category"], node.get("extension", ""))

        result = self.ai_analyzer.analyze(
            node, decision_bias, related=related, related_decision=related_decision,
            is_running=is_running, is_duplicate=is_duplicate,
        )

        node.update(
            importance=result["importance"],
            junk_probability=result["junk_probability"],
            status=result["status"],
            reason=result["reason"],
            why=result.get("why", []),
            ai_guess=result.get("ai_guess"),
            is_running=is_running,
            is_duplicate=is_duplicate,
            is_protected=False,
            duplicate_of=dup_info["paths"] if dup_info else None,
            duplicate_count=(len(dup_info["paths"]) - 1) if dup_info else 0,
            related_previous=related,
            fingerprint=fingerprint,
        )
        if related and related.get("still_exists") == 0:
            node["why"].append("A related item was previously seen at a different location.")

        self.memory.upsert_item({
            "path": node["path"], "name": node["name"],
            "extension": node.get("extension", ""), "node_type": node["node_type"],
            "category": node["category"], "size": node["size"],
            "created": node.get("created"), "modified": node.get("modified"),
            "accessed": node.get("accessed"), "fingerprint": fingerprint,
            "importance": node["importance"], "junk_probability": node["junk_probability"],
            "status": node["status"], "reason": node["reason"],
        })

    def _build_summary(self, tree, duplicate_paths):
        total_size = 0
        junk_size = 0
        items_found = 0
        junk_items = 0
        category_counts = {}
        wasted_dup_space = sum(g["wasted_space"] for g in
                                {id(g): g for g in duplicate_paths.values()}.values())

        def walk(node):
            nonlocal total_size, junk_size, items_found, junk_items
            items_found += 1
            total_size += node["size"]
            category_counts[node["category"]] = category_counts.get(node["category"], 0) + 1
            if node.get("status") in ("Probably unnecessary", "Likely junk"):
                junk_size += node["size"]
                junk_items += 1
            if node["node_type"] == "folder":
                for child in node["children"]:
                    walk(child)

        for top in tree:
            walk(top)

        return {
            "total_size": total_size,
            "potential_junk_size": junk_size,
            "items_found": items_found,
            "junk_items": junk_items,
            "category_counts": category_counts,
            "duplicate_wasted_space": wasted_dup_space,
            "scanned_at": time.time(),
        }
