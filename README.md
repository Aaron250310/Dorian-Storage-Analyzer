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
   - **First run only:** if Python isn't already on your computer, the
     script installs it automatically (via `winget` if available, or a
     direct download from python.org otherwise) — you may see a Windows
     prompt asking you to approve the installer, which is normal. Once
     it finishes, close the window and double-click `Start Dorian.bat`
     again to continue.
   - It then automatically creates a private Python environment (`venv/`)
     and installs everything the app needs from `requirements.txt`. This
     also only happens once — every run after that starts instantly.
3. (Optional) Double-click **`Create Desktop Shortcut.bat`** once to add
   a "Dorian" shortcut to your Desktop, so you never need
   to open this folder again.
4. (Optional) Want the real AI model instead of just the local rule-based
   engine? See **"Setting up AI-assisted analysis"** below.

## Setup (manual / command line)

```
pip install -r requirements.txt
python main.py
```

## Setting up AI-assisted analysis (optional)

By default, Dorian works **entirely offline** using its local rule-based
engine — no account, no API key, no internet connection needed. This
section is only for people who want Dorian to also consult a real AI
model (Claude) for the items it's genuinely unsure about (anything still
categorized "Unknown" after the rule-based pass).

**What this does and doesn't change:** even with AI enabled, most items
are still scored by the fast local rules — installers, cache folders,
documents, games, dev projects, etc. The AI is only consulted for the
ambiguous leftovers, and only lightweight metadata is ever sent to it
(file name, extension, size, dates, category) — never file contents.

### Steps

1. **Get an API key** from the [Anthropic Console](https://console.anthropic.com/):
   - Sign up or log in.
   - Go to **Settings → API Keys** and click **Create Key**.
   - Copy the key (it starts with `sk-ant-...`) — you won't be able to
     see it again after leaving the page, so save it somewhere safe.
   - Note: this requires setting up billing on your Anthropic account.
     API usage is billed per request; since Dorian only calls the AI for
     genuinely ambiguous items (not your whole drive), typical usage is
     small, but you should check current pricing at
     [anthropic.com/pricing](https://www.anthropic.com/pricing) before
     relying on it heavily.

2. **Create your `.env` file.** In the app's folder, copy `.env.example`
   to a new file named exactly `.env` (Windows may hide the file
   extension — make sure it isn't accidentally named `.env.txt`).

3. **Add your key.** Open `.env` in Notepad and replace the placeholder:
   ```
   ANTHROPIC_API_KEY=sk-ant-your-actual-key-here
   ```

4. **(Optional) Choose a different model.** By default Dorian uses
   `claude-haiku-4-5-20251001` (fast and inexpensive, well-suited to
   quick per-item classification). To use a different Claude model,
   uncomment and edit the `AI_MODEL` line in `.env`:
   ```
   AI_MODEL=claude-haiku-4-5-20251001
   ```

5. **Restart Dorian** (close it and re-run `Start Dorian.bat`) so it
   picks up the new `.env` file.

### How to tell it's working

Open the **Activity Log** (the dropdown below the scan bar) and scan a
folder with some genuinely unclear files in it. If the AI is being
consulted, you'll see items whose "Why?" explanation includes a line
like *"Refined by Dorian for an ambiguous item"* — that means the real
model was called for that specific item, rather than only the local
rules.

If something's misconfigured (bad key, no internet, rate-limited, etc.),
Dorian **fails silently back to the rule-based engine** rather than
erroring out — so the app keeps working either way, but you won't see
that "Refined by Dorian" line if the AI call didn't actually succeed.

### Keeping your key private

- `.env` is already listed in `.gitignore`, so it won't be committed if
  you push this project to GitHub — double-check `git status` never
  shows `.env` as a tracked file before pushing.
- Never paste your API key into a chat, issue, or commit message.
- If you ever suspect a key has leaked, revoke it immediately from the
  Anthropic Console and generate a new one.

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

## License

This project is **not open source**. All rights are reserved by the
copyright holder — see [`LICENSE`](LICENSE) for the full terms. You're
welcome to view the source and run the app for your own personal,
non-commercial use, but copying, modifying, redistributing, or using it
commercially requires prior permission.

## Disclaimer

Dorian is a helpful advisor, not an infallible one. Its importance/junk
scores, category guesses, bundle detection, and duplicate matching are
all best-effort — whether they come from the local rule-based engine or
the optional AI model, they **can be wrong**, especially on unusual
folder layouts or uncommon file types. Always review what's selected
before confirming a deletion; the app is designed to make that easy
(the "Why?" button, the confirmation dialogs, and defaulting to the
Recycle Bin instead of permanent deletion), but the final call is always
yours. Neither the app nor its author is responsible for data loss
resulting from acting on its recommendations.
