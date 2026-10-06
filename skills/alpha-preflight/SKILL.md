---
name: alpha-preflight
description: Inspect PNG and WebP cutouts, stickers, icons, or AI-generated assets before delivery. Measure actual transparency, flag empty or canvas-touching content, and produce offline background previews with soft-edge and painted-grid hints. Use for 透明素材验收、PNG假透明、白边黑边检查. Requires local Python; inspection preserves the originals.
license: MIT
---

# Alpha Preflight

Inspect the user's specified files before they place them on a webpage, slide, or design. Deliver evidence they can see and measurements they can use.

## Run the inspection

1. Identify the supplied images or folder. Ask for the input if it is missing; do not scan unrelated personal directories. Supported inputs are static, 8-bit PNG, WebP, and JPEG. A JPEG can be inspected as an opaque comparison. Animated files and 16-bit PNGs are reported as unsupported.
2. Locate `scripts/inspect_alpha.py` relative to this skill. Use Python 3.10 or newer with Pillow. If Pillow is missing, install this skill's `requirements.txt` into a project or temporary virtual environment; do not change the global Python environment.
3. Run the bundled inspector with the exact input paths and a **new** output directory. Quote paths containing spaces. It creates `index.html` and `report.json`, never overwrites an existing output directory, and never alters source files.

```sh
python /path/to/alpha-preflight/scripts/inspect_alpha.py "/path/to/assets" --out "/path/to/new-report"
```

Folders are scanned recursively, with hidden directories and symlinks skipped. The report covers at most 100 images, each up to 40 megapixels. Use smaller batches when necessary.

## Read the evidence

Read `report.json`, then inspect `index.html` on light and dark backgrounds. The HTML is self-contained: opening it needs no server, account, API key, or network connection. Open it in the host's file/browser preview when available; otherwise provide its file link. The previews include a magnified region whose original coordinates are recorded.

- **Facts:** transparent/semitransparent pixel counts, visible bounding box and margins, canvas contact, empty images, unreadable inputs, and source SHA-256 fingerprints.
- **Hints:** neutral bright or dark soft boundary pixels and repeating grayscale corner patterns. These are candidates for inspection, not confirmed defects. An intentional outline or checkerboard design can produce the same result.
- **No automatic flags:** only means the implemented checks found nothing to flag. Do not certify an asset as visually perfect, free of halos, or ready for every background.

Read [references/interpretation.md](references/interpretation.md) when a hint is ambiguous, the user asks about thresholds, or the JSON will feed another workflow.

## Deliver

Summarize measured problems first, then uncertain hints with the relevant filenames and visual evidence. Distinguish missing transparency from an alpha channel containing only opaque pixels. Mention that contact with the canvas can be intentional. List any files that could not be inspected; never silently omit them.

Return links to the HTML and JSON report in the user's language. Reports contain reduced copies of the input artwork, even though embedded metadata and fully hidden RGB are removed from previews. Keep reports local unless the user asks to share them.

This workflow performs inspection. If the user requests a repair, agree on the affected area and use an appropriate image-editing tool, save a separate file, and inspect that new result. Never remove white or black pixels from an asset merely because a hint fired.

## Command outcomes

Normal inspection exits `0` when a report is written without input errors, even if review hints exist. Input/decode/write errors exit `1`; a partial batch report still lists each input error. `--fail-on-review` exits `2` when a report contains review flags and no input errors. Argument errors also exit `2` and produce no report. These outcomes describe inspection, not visual approval.
