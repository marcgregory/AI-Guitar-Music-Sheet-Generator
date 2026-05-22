Use this. It’s clean and ready for Codex:

````md
# Compare Script Readable Reporting

Update `backend/scripts/compare_local_prod_tabs.py` so the compare output is readable, summary-first, and terminal-safe.

## Requirements

### 1. CLI options

Add:

- `--write-debug-payloads`
  - default: false
  - when enabled, save full local/prod payloads to JSON files

- `--debug-dir`
  - default: `backend/debug`
  - used only when `--write-debug-payloads` is enabled

Normal dry-run compare must not write files unless `--write-debug-payloads` is passed.

---

### 2. Replace raw snapshot output

Remove or disable the full:

```text
=== Comparison Snapshot JSON ===
```
````

dump from normal output.

Instead print:

```text
=== LOCAL ===
status:
selected_stem:
notes_count:
tablature_events_count:
selected_track_notes_count:
avg_confidence:
min_confidence:
max_confidence:
preview:

=== PROD ===
status:
selected_stem:
notes_count:
tablature_events_count:
selected_track_notes_count:
avg_confidence:
min_confidence:
max_confidence:
preview:

Differences:
- ...
```

Do not print full note arrays, tablature arrays, or escaped serialized JSON blobs in stdout by default.

---

### 3. Add safe summary helpers

Add helper functions that can be tested independently:

- `extract_event_list(value)`
  - Accept common shapes:
    - direct list
    - `{ "tablature": [...] }`
    - `{ "tabs": [...] }`
    - `{ "events": [...] }`
    - nested common result payloads if already used by the script

  - Return a list.
  - Return `[]` for unknown/empty shapes.

- `event_confidence_stats(events)`
  - Return:
    - count
    - avg confidence
    - min confidence
    - max confidence

  - Ignore events without numeric confidence.
  - Avoid divide-by-zero.

- `preview_events(events, limit=3)`
  - Return only a tiny preview.
  - Include stable fields only:
    - string
    - fret
    - startTime
    - duration
    - confidence

- `canonical_json(value)`
  - Stable JSON string using sorted keys.
  - Used for equality/difference checks.

- `count_differing_events(local_events, prod_events)`
  - Compare events by canonical JSON.
  - Report how many event positions differ.
  - Also account for length mismatch.

---

### 4. Difference reporting

Under `Differences:`, report concise lines like:

```text
- notes_data length differs: local=1842 prod=1733
- tablature_data length differs: local=1799 prod=1701
- notes_data differing event positions: 241
- tablature_data differing event positions: 198
- selected_stem differs: local=bass prod=other
```

If no meaningful differences:

```text
Differences:
- none
```

---

### 5. Optional debug payload files

When `--write-debug-payloads` is passed:

Write:

```text
backend/debug/local_tabs.json
backend/debug/prod_tabs.json
```

Each file should contain the full payload/snapshot for inspection.

Print only:

```text
Saved:
- backend/debug/local_tabs.json
- backend/debug/prod_tabs.json
```

Do not print the full content.

---

### 6. Tests

Add focused tests in:

```text
backend/tests/test_compare_local_prod_tabs.py
```

Test:

- `extract_event_list` supports direct lists and common object shapes.
- confidence stats handle empty lists and missing confidence.
- `preview_events` truncates to the requested limit.
- `print_comparison` prints counts and avg confidence.
- `print_comparison` reports length mismatch and differing event counts.
- `print_comparison` does not dump long serialized arrays.
- debug payload writing creates:
  - `local_tabs.json`
  - `prod_tabs.json`
    and preserves full payload content.

Run:

```bash
python -m pytest backend/tests/test_compare_local_prod_tabs.py
```

## Constraints

- Do not change cleanup/regeneration behavior.
- Do not enable prod mutation.
- Do not touch unrelated files such as `backend/app/core/config.py` or `skill.md`.
- Keep dry-run behavior as the default.

```

```

- Event comparison is deterministic and position-aware only; do not add fuzzy timestamp tolerance, sorting, or musical similarity matching in this task.
