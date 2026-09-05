"""
ai_analyzer.py
--------------
Produces the "Importance score", "Junk probability", "Status" and human
readable "Reason" for a scanned item.

Two engines are available:

  * A fast, fully local, rule-based engine (`_rule_based_score`). This is
    used for everything by default, and for every item whose signals are
    already clear-cut (e.g. an old installer, or an actively used
    document) -- there's no reason to spend an API call on something we
    can already reason about confidently.

  * An optional real AI engine, used ONLY for genuinely ambiguous /
    "Unknown" items, and only when an ANTHROPIC_API_KEY is configured
    (see .env.example). Only lightweight metadata is ever sent -- never
    file contents.

If no API key is present, or the API call fails for any reason (offline,
rate-limited, etc.), the app transparently falls back to the rule-based
engine so it keeps working.
"""

import json
import os
import time

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover - python-dotenv is optional
    pass


API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = os.environ.get("AI_MODEL", "claude-haiku-4-5-20251001")
DAY = 86400.0

SYSTEM_PROMPT = (
    "You are Dorian, a careful, conservative storage-analysis assistant helping a user "
    "decide what is safe to remove from their computer. You will be given only "
    "metadata about a file or folder (never its contents). Respond with ONLY a "
    "JSON object, no other text, no markdown fences, with exactly these keys: "
    '{"importance": <0-100 int>, "junk_probability": <0-100 int>, '
    '"status": one of "Keep"|"Review"|"Probably unnecessary"|"Likely junk", '
    '"reason": "<one or two short plain-language sentences>", '
    '"likely_type": "<your best one-sentence guess of what this file/folder actually '
    'is or belongs to, based on its name/extension/location -- e.g. '
    '\'Possibly a save-game or config file for an installed game\'>"}. '
    "Never assume old means useless -- personal documents, source code, and "
    "save files can be old and still important. When genuinely unsure, prefer "
    "a lower junk_probability and status \"Review\" rather than guessing."
)

EXTENSION_GUESSES = {
    ".dat": "A generic data file -- likely used internally by an application.",
    ".db": "A database file, possibly used by an installed application to store its data.",
    ".ini": "A configuration file for an application.",
    ".cfg": "A configuration file for an application.",
    ".lock": "A lock file created temporarily while a program is running.",
    ".log": "A log file -- usually safe to remove once the related program isn't actively debugging.",
    ".bak": "A backup copy of another file.",
    ".old": "An old/renamed backup of another file.",
    ".sav": "Possibly a save-game file.",
    ".part": "An incomplete/interrupted download.",
    ".crdownload": "An incomplete Chrome download.",
    ".tmp": "A temporary file, usually safe to remove.",
    "": "A file with no extension -- could be a config file, a Unix-style binary, or app data.",
}


def guess_unknown_type(item):
    """A short, local, offline guess at what an unrecognized item might be,
    used when we don't have enough information to categorize it confidently
    and no AI call is made (or the AI call didn't return one).
    """
    ext = (item.get("extension") or "").lower()
    name = (item.get("name") or "").lower()
    if ext in EXTENSION_GUESSES:
        return EXTENSION_GUESSES[ext]
    if "backup" in name:
        return "The name suggests this is a backup copy of something else."
    if "temp" in name or "tmp" in name:
        return "The name suggests this is temporary data."
    if item.get("node_type") == "folder":
        return "A folder with a mix of file types that doesn't match a known application pattern."
    return f"An uncommon file type ('{ext or 'no extension'}') that doesn't match a known pattern."


class AIAnalyzer:
    def __init__(self, memory):
        self.memory = memory
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.ai_available = bool(self.api_key and requests is not None)

    # ------------------------------------------------------------------
    def analyze(self, item: dict, decision_bias: dict, related: dict = None,
                related_decision: dict = None, is_running: bool = False,
                is_duplicate: bool = False):
        """Return dict with importance, junk_probability, status, reason, why."""
        rule_result = self._rule_based_score(
            item, decision_bias, related, related_decision, is_running, is_duplicate
        )

        needs_ai = (
            self.ai_available
            and item.get("category") in (None, "Unknown", "Collection of files")
            and not is_running
        )
        if needs_ai:
            ai_result = self._call_ai(item, decision_bias, related, related_decision, is_duplicate)
            if ai_result:
                ai_result["why"] = rule_result["why"] + ["Refined by Dorian for an ambiguous item."]
                if not ai_result.get("ai_guess"):
                    ai_result["ai_guess"] = rule_result.get("ai_guess")
                return ai_result

        return rule_result

    # ------------------------------------------------------------------
    def _rule_based_score(self, item, decision_bias, related, related_decision,
                           is_running, is_duplicate):
        importance = 50
        junk = 20
        why = []
        category = item.get("category") or "Unknown"
        now = time.time()
        age_accessed_days = max(0, (now - (item.get("accessed") or now)) / DAY)
        age_modified_days = max(0, (now - (item.get("modified") or now)) / DAY)
        size = item.get("size", 0)

        if is_running:
            why.append("The application/game appears to be running right now.")
            return {
                "importance": 95, "junk_probability": 1, "status": "Keep",
                "reason": "This is currently running, so it should not be removed.",
                "why": why,
            }

        category_adjust = {
            "Cache / temporary data": (-30, 45, "Looks like cache or temporary data."),
            "Installer": (-15, 35, "Looks like a leftover installer file."),
            "Development project": (25, -15, "Looks like a programming/development project."),
            "Documents": (15, -10, "Looks like a personal document."),
            "Game": (10, -5, "Looks like an installed game."),
            "Application": (8, -5, "Looks like an installed application."),
            "Media": (5, -5, "Looks like a personal photo/video/audio file."),
            "Archive": (-5, 10, "Looks like a compressed archive."),
            "Configuration": (5, -5, "Looks like a configuration file used by an application."),
            "Collection of files": (0, 0, "A mixed folder of unrelated files."),
            "Unknown": (0, 5, "Could not confidently determine what this is."),
        }
        imp_adj, junk_adj, reason_bit = category_adjust.get(category, (0, 5, "Uncategorized item."))
        importance += imp_adj
        junk += junk_adj
        why.append(reason_bit)

        # Recency signals
        if age_accessed_days < 14:
            importance += 15
            junk -= 15
            why.append("Accessed within the last two weeks.")
        elif age_accessed_days > 365:
            importance -= 20
            junk += 25
            why.append(f"Not accessed for over a year ({int(age_accessed_days)} days).")
        elif age_accessed_days > 180:
            importance -= 10
            junk += 12
            why.append(f"Not accessed for {int(age_accessed_days)} days.")

        # Size: large + old + installer/cache is a strong junk signal
        if size > 1 * 1024 * 1024 * 1024 and category in ("Installer", "Cache / temporary data", "Archive"):
            if age_accessed_days > 90:
                junk += 15
                why.append("Large, old, and not the kind of file that's normally kept long-term.")

        # Duplicate
        if is_duplicate:
            junk += 20
            importance -= 10
            why.append("A duplicate copy of this file exists elsewhere.")

        # Related item seen elsewhere before
        if related and related_decision:
            if related_decision.get("decision") == "deleted":
                junk += 20
                importance -= 10
                why.append("A very similar item was previously identified and deleted by you.")
            elif related_decision.get("decision") == "kept":
                junk -= 15
                importance += 10
                why.append("A very similar item was previously kept by you.")

        # Learned bias from decision history for this category/extension
        total_decisions = sum(decision_bias.values()) if decision_bias else 0
        if total_decisions >= 3:
            delete_ratio = decision_bias.get("deleted", 0) / total_decisions
            keep_ratio = decision_bias.get("kept", 0) / total_decisions
            if delete_ratio >= 0.7:
                junk += 15
                importance -= 8
                why.append("You have usually deleted similar items in the past.")
            elif keep_ratio >= 0.7:
                junk -= 15
                importance += 10
                why.append("You have usually kept similar items in the past, even when old.")

        importance = max(0, min(100, importance))
        junk = max(0, min(100, junk))

        status = self._status_from_junk(junk)
        reason = self._compose_reason(category, why)

        ai_guess = None
        if category == "Unknown":
            ai_guess = guess_unknown_type(item)
            why.append(f"Best guess: {ai_guess}")

        return {
            "importance": importance, "junk_probability": junk,
            "status": status, "reason": reason, "why": why, "ai_guess": ai_guess,
        }

    @staticmethod
    def _status_from_junk(junk):
        if junk < 20:
            return "Keep"
        if junk < 45:
            return "Review"
        if junk < 70:
            return "Probably unnecessary"
        return "Likely junk"

    @staticmethod
    def _compose_reason(category, why_points):
        lead = {
            "Cache / temporary data": "This appears to be temporary or cache data.",
            "Installer": "This appears to be a leftover installer.",
            "Development project": "This appears to be a programming project.",
            "Game": "This appears to be an installed game.",
            "Application": "This appears to be an installed application.",
            "Documents": "This appears to be a personal document.",
        }.get(category, "This item was analysed based on its type, age and usage.")
        extra = " ".join(why_points[1:3]) if len(why_points) > 1 else ""
        return f"{lead} {extra}".strip()

    # ------------------------------------------------------------------
    def _call_ai(self, item, decision_bias, related, related_decision, is_duplicate):
        """Send minimal metadata to the Anthropic API for an ambiguous item."""
        if not self.ai_available:
            return None

        metadata = {
            "name": item.get("name"),
            "extension": item.get("extension"),
            "type": item.get("node_type"),
            "detected_category": item.get("category"),
            "size_bytes": item.get("size"),
            "days_since_accessed": round(max(0, (time.time() - (item.get("accessed") or time.time())) / DAY), 1),
            "days_since_modified": round(max(0, (time.time() - (item.get("modified") or time.time())) / DAY), 1),
            "is_duplicate_of_another_file": is_duplicate,
            "previously_seen_elsewhere": bool(related),
            "previous_user_decision_on_similar_item": (related_decision or {}).get("decision"),
            "decision_history_for_this_category": decision_bias,
        }

        try:
            resp = requests.post(
                API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": DEFAULT_MODEL,
                    "max_tokens": 300,
                    "system": SYSTEM_PROMPT,
                    "messages": [
                        {"role": "user", "content": json.dumps(metadata)}
                    ],
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            text = "".join(
                block.get("text", "") for block in data.get("content", [])
                if block.get("type") == "text"
            )
            text = text.strip().strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
            parsed = json.loads(text)
            importance = int(max(0, min(100, parsed["importance"])))
            junk = int(max(0, min(100, parsed["junk_probability"])))
            status = parsed.get("status") or self._status_from_junk(junk)
            reason = parsed.get("reason") or "Dorian's analysis of this item."
            return {
                "importance": importance, "junk_probability": junk,
                "status": status, "reason": reason,
                "ai_guess": parsed.get("likely_type"),
            }
        except Exception:
            # Any failure (offline, bad key, malformed response, rate limit)
            # -> silently fall back to the rule-based result the caller
            # already computed.
            return None
