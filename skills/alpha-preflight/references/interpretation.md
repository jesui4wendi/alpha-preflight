# Reading the report

## What is measured

Alpha is inspected after file decoding and EXIF orientation. RGBA and LA alpha, indexed PNG transparency, and RGB transparency keys are recognized. `encoded_alpha_or_transparency` records whether the file supplied an alpha/transparency representation; it does not mean any pixel is actually transparent.

- Alpha `0`: fully transparent.
- Alpha `1–254`: semitransparent.
- Alpha `255`: opaque.
- `empty`: every pixel is fully transparent.
- `opaque`: every pixel is opaque.
- `transparent`: at least one pixel is nonopaque and at least one is visible; this includes a uniformly translucent image.

`visible_bbox` is `[left, top, right, bottom]` in the oriented image, with right and bottom exclusive. It includes any alpha greater than zero. Faint antialiasing can reduce the apparent margin. Empty images have no bounding box or margins.

## Edge hints

The inspector measures a one-pixel boundary of content with alpha above 16. Only boundary pixels with alpha `17–239` contribute to the soft-edge sample. A light candidate has all RGB channels at least 245; a dark candidate has all RGB channels at most 10. A hint requires at least 20 sampled pixels, at least 12 candidate pixels, and candidate coverage of at least 25% of the sample.

These are simple, explicit heuristics. They can flag intentional light/dark outlines. They can miss opaque fringes, coloured halos, fine hair, very faint edges, and assets with fewer qualifying pixels. A hint is not a probability or a defect score. The edge zoom highlights a qualifying pixel when one exists; otherwise it uses a central detail. Inspect the overview as well.

## Painted-grid hints

Only fully opaque images are scanned. Each corner patch is at most 128 pixels per side and at most one quarter of the image width/height. Candidate square sizes are 4, 6, 8, 12, 16, 24, and 32 pixels, only when the patch is large enough for three squares.

A patch must be predominantly neutral grey. Repeated pixels two squares apart must be similar, while pixels one square apart must differ in both horizontal and vertical directions. At least two corners must match to emit a hint. Foreground artwork covering the corners, rotated grids, unusual square sizes, compressed/irregular patterns, or low contrast can make the heuristic miss a painted grid. Intentional tile designs can trigger it.

Missing transparency remains an exact measurement even when the painted-grid hint does not fire.

## Colour and previews

Alpha measurements use decoded source pixels. Readable embedded colour profiles are converted to sRGB for previews and edge-colour hints; untagged images are assumed sRGB. If conversion fails, the report says so and falls back to decoded colours. This is an 8-bit inspection tool, not an HDR or print-proofing workflow. Animated images and 16-bit PNGs are rejected rather than silently reducing them.

Overview previews are limited to 480 pixels on the longest side. Detail previews enlarge a source region using nearest-neighbour sampling. Generated preview PNGs omit source metadata and clear RGB values for fully transparent pixels. HTML embeds those previews and uses CSS background controls; it has no scripts or remote resources. The report still contains visible artwork.

## JSON contract

The top-level keys are `schema_version`, `tool`, `tool_version`, `summary`, and `files`. Schema version 1 provides one record per discovered, deduplicated input. Records have `label`, `status`, and `diagnostics`; successful decodes also include dimensions, format, source mode, SHA-256, alpha facts, edge statistics, checkerboard evidence, preview colour handling, and zoom coordinates.

Statuses are `no_flags`, `review`, or `error`. Every diagnostic has `code`, `kind` (`fact` or `hint`), and a human-readable `message`. Automate against codes and measurements rather than English wording. Error records omit measurements they could not establish. Labels identify the input without embedding absolute source paths; same-named inputs receive a numeric suffix in discovery order. Use fingerprints for exact source matching.
