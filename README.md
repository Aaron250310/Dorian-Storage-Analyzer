# Dorian — AI Storage Analyzer

**Dorian** is a desktop app (Windows, Python + Tkinter) that scans a
folder, figures out what's actually in it — including recognizing whole
apps/games as single bundles instead of hundreds of loose files —
remembers what it's seen before, learns from your past delete/keep
decisions, and lets you safely send unwanted items to the Recycle Bin.

It is deliberately **not** a "delete anything old" cleaner. Dorian
explains its reasoning for every recommendation and never deletes
anything without your explicit confirmation.

"Dorian" is the name of the analysis engine you'll see referenced
throughout the app (in "Why?" explanations, best-guess text, and the
Activity Log) — whether it's answering from the local rule-based engine
or, if you've configured an API key, the real AI model.

## Features

- Recursive folder scan with a live progress bar (no UI freezing) and a
  **Cancel Scan** button if you change your mind partway through.
- Detects application/game **bundles** (Unity, Unreal, Electron, generic
  exe+dll folders, dev projects) and treats them as one item instead of
  flooding you with their internal files.
- Importance score (0–100) and Junk probability (0–100%) for every item,
  with a plain-language "Why?" explanation and a "Details" view.
- **Duplicate counts shown directly in the list** (e.g. "♻ 2 other
  copies") for files that share content with something else found in the
  same scan.
- **Deep Scan**: right-click any file → "Find Duplicates Across
  Computer" to search every drive on your PC for other copies of that
  exact file (not just within the scanned folder). Results open in a
  checklist where you can keep the original and remove just the extra
  copies, remove everything including the original, or any custom mix —
  then send them to the Recycle Bin or delete permanently. Cancellable
  mid-scan.
- **Bulk selection**: Select All / Deselect All / Select Recommended, on
  top of individual checkboxes.
- **Right-click any item** to Show it in File Explorer (highlighted) or
  Open it directly with its default app.
- Two ways to remove things: the default **Move to Recycle Bin**
  (reversible), or an explicit **Permanently Delete** option — gated
  behind its own red warning dialog and an "I understand this can't be
  undone" checkbox.
- When an item **can't be selected** (protected system path, currently
  running, or genuinely "not enough information"), clicking its checkbox
  explains exactly why — and for unknown items, shows the AI's best guess
  at what the file/folder actually is.
- A collapsible **Activity Log** below the scan bar showing what's
  happening right now and a running history of completed operations
  (scans, analysis, deep scans, each delete attempt) with success/failure
  status.
- **Theme**: automatically matches your OS (light/dark) on first launch,
  detected from the Windows registry (or macOS's appearance setting) —
  and can be overridden any time from the **Theme** dropdown next to the
  scan button (Auto / Light / Dark). Your choice is remembered in
  `settings.json`.
- Detects duplicate files within a scanned folder (size pre-filter +
  content hash, so it's fast even on large drives).
- Detects whether a game/app is **currently running** and refuses to let
  you select it for deletion.
- Remembers every scan in a local SQLite database (`database/storage_memory.db`)
  and recognizes the same file/app if it shows up in a different folder
  later.
- Learns from your own delete/keep history (e.g. "you usually keep
  programming projects") as one input among several — it never
  auto-deletes based on learned behaviour.
- Sort and filter results (by size, importance, junk %, category, dates,
  duplicates, etc.).
- Protected system locations (`C:\Windows`, `System32`, drive roots, ...)
  are never offered for deletion, in the main scan or in a deep scan.
- Works fully offline with a local rule-based analysis engine. An
  Anthropic API key is optional and only used for genuinely ambiguous
  ("Unknown") items — only lightweight metadata (name, size, dates,
  category) is ever sent, never file contents.

## Project structure

```
AIStorageAnalyzer/
├── main.py                # entry point / wiring
├── scanner.py              # recursive filesystem walk + progress
├── bundle_detector.py       # app/game bundle vs normal-folder detection
├── analyzer.py              # orchestrates scanning, scoring, memory
├── ai_analyzer.py           # rule-based scoring + optional AI for ambiguous items
├── memory.py                 # SQLite persistence (scans + decisions)
├── process_checker.py        # "is this running?" + protected-path checks
├── duplicate_detector.py      # duplicate file detection
├── deletion_manager.py         # safe move-to-recycle-bin
├── ui.py                       # Tkinter interface
├── database/                    # storage_memory.db lives here (auto-created)
├── requirements.txt
├── .env.example
└── README.md
```

## Setup (Windows) — the easy way

You don't need to use the command line at all:

1. Unzip this folder anywhere (e.g. your Desktop or Documents).
2. Double-click **`Start Dorian.bat`**.
   - The first time you run it, it automatically creates a private
     Python environment (`venv/`) and installs everything the app needs
     from `requirements.txt`. This only happens once — every run after
     that starts instantly.
   - Requires Python 3.10+ to already be installed
     (get it from python.org, with "Add python.exe to PATH" checked
     during setup — a one-time system requirement the app can't install
     for you).
3. (Optional) Double-click **`Create Desktop Shortcut.bat`** once to add
   a "Dorian" shortcut to your Desktop, so you never need
   to open this folder again.
4. (Optional) If you want AI-assisted analysis for ambiguous/unknown
   items, copy `.env.example` to `.env` and add your Anthropic API key.
   Without this, the app works fully using its local rule-based engine.

## Setup (manual / command line)

```
pip install -r requirements.txt
python main.py
```

## How it works, step by step

```
Select folder
   -> Scan (background thread, live progress)
   -> Build bundle/folder tree (recognize apps/games as single units)
   -> Detect duplicates
   -> For every item: check memory, check if it's running, ask the
      AI/rule engine for a score, save the result to memory
   -> Show results (sortable, filterable, with "Why?" and "Details")
   -> You select items with the checkboxes
   -> Confirmation dialog shows exactly what will be moved and how big it is
   -> Move to Recycle Bin (never permanent delete)
```

## Design notes / trade-offs (read this before reporting a "bug")

- **Progress percentage** is based on a quick first pass that counts
  files/folders without reading their metadata, followed by the real
  scan. On extremely large drives this first pass adds a small amount of
  time but keeps the progress bar honest.
- **"Currently in use" detection** is done for application/game bundles
  (by checking running processes against the bundle's executables) and
  for standalone `.exe` files. Checking every single ordinary file for
  open file-handles would be far too slow on folders with tens of
  thousands of files and isn't necessary for the safety goal (not
  deleting something you're actively using) — see requirement 20 in the
  original spec about avoiding expensive per-file operations.
- **Duplicate detection** hashes large files using only their first and
  last megabyte plus their size, rather than the whole file, to keep
  large-folder scans fast. This is a standard trade-off for this kind of
  tool and only applies to files above 10 MB.
- **AI usage is intentionally limited.** The rule-based engine handles
  every item with clear signals (installers, cache folders, recently
  used documents, running apps, etc.). The optional AI call is reserved
  for items that are still "Unknown" after rule-based analysis, both to
  keep the app fast/offline-capable and to keep API usage (and cost) low.
- The bundle detector uses heuristics (file/folder signatures like
  `UnityPlayer.dll`, `Engine/Binaries/Saved`, `.git`, exe+dll
  combinations, etc.). It will occasionally misclassify unusual folder
  layouts — when it isn't confident, it falls back to treating the
  folder as a normal collection of files so nothing gets bundled
  (and potentially deleted) incorrectly.
- **Deep Scan is genuinely a whole-drive walk.** Searching every fixed
  drive for a duplicate of one file can take anywhere from seconds to
  tens of minutes depending on how much is on your PC — that's inherent
  to "search my whole computer," not a bug. It's cancellable at any time,
  and it skips known noisy/huge system folders (`$RECYCLE.BIN`,
  `System Volume Information`, `node_modules`, `.git`, etc.) plus every
  protected system location to keep it as fast as reasonably possible.

## Safety summary

- Nothing is ever permanently deleted — only moved to the Recycle Bin.
- Every deletion requires an explicit confirmation showing the exact
  items and total size.
- Protected Windows system paths cannot be scanned into a deletable
  recommendation or selected.
- Running applications/games cannot be selected for deletion.
- Unknown items are never pre-selected by "Select Recommended".
