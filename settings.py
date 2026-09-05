"""
settings.py
-----------
Tiny local settings file (settings.json, next to main.py) so preferences
like the chosen theme survive between runs. Deliberately minimal --
no external dependencies, just JSON on disk.
"""

import json
import os

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

DEFAULTS = {"theme": "auto"}  # "auto" | "light" | "dark"


def load_settings():
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(DEFAULTS)
        merged.update(data)
        return merged
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_settings(settings):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass
