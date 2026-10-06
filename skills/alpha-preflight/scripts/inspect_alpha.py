#!/usr/bin/env python3
"""Inspect static image transparency and write an offline visual report."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
import os
import sys
import warnings
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageFilter, ImageOps, UnidentifiedImageError
except ImportError:
    raise SystemExit("Pillow is required. Install the adjacent skill's requirements.txt in your Python environment.")

VERSION = "1.0.0"
EXTENSIONS = {".png", ".webp", ".jpg", ".jpeg"}
MAX_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def issue(code: str, kind: str, message: str) -> dict:
    return {"code": code, "kind": kind, "message": message}


def count_mask(mask: Image.Image) -> int:
    return mask.histogram()[255]


def alpha_facts(rgba: Image.Image, encoded_alpha: bool) -> dict:
    alpha = rgba.getchannel("A")
    histogram = alpha.histogram()
    total = rgba.width * rgba.height
    transparent, opaque = histogram[0], histogram[255]
    semitransparent = total - transparent - opaque
    bbox = alpha.getbbox()
    if transparent == total:
        state = "empty"
    elif opaque == total:
        state = "opaque"
    else:
        state = "transparent"
    margins = None
    touches = []
    if bbox:
        left, top, right, bottom = bbox
        margins = {"left": left, "top": top, "right": rgba.width - right, "bottom": rgba.height - bottom}
        touches = [side for side, margin in margins.items() if margin == 0]
    return {
        "state": state,
        "encoded_alpha_or_transparency": encoded_alpha,
        "pixel_count": total,
        "transparent_pixels": transparent,
        "semitransparent_pixels": semitransparent,
        "opaque_pixels": opaque,
        "transparent_percent": round(100 * transparent / total, 4),
        "semitransparent_percent": round(100 * semitransparent / total, 4),
        "visible_bbox": list(bbox) if bbox else None,
        "margins_px": margins,
        "touches_canvas": touches,
    }


def edge_hints(rgba: Image.Image) -> tuple[dict, Image.Image]:
    """Measure neutral bright/dark soft boundary pixels; not a halo verdict."""
    alpha = rgba.getchannel("A")
    visible = alpha.point(lambda value: 255 if value > 16 else 0)
    padded = ImageOps.expand(visible, border=1, fill=0)
    eroded = padded.filter(ImageFilter.MinFilter(3)).crop((1, 1, rgba.width + 1, rgba.height + 1))
    boundary = ImageChops.subtract(visible, eroded)
    soft = alpha.point(lambda value: 255 if 16 < value < 240 else 0)
    boundary = ImageChops.multiply(boundary, soft)
    red, green, blue, _ = rgba.split()
    minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    bright = ImageChops.multiply(boundary, minimum.point(lambda value: 255 if value >= 245 else 0))
    dark = ImageChops.multiply(boundary, maximum.point(lambda value: 255 if value <= 10 else 0))
    samples = count_mask(boundary)
    bright_count, dark_count = count_mask(bright), count_mask(dark)
    candidates = []
    for name, count in (("light", bright_count), ("dark", dark_count)):
        if count >= 12 and samples >= 20 and count / samples >= 0.25:
            candidates.append(name)
    focus = bright if "light" in candidates else dark if "dark" in candidates else boundary
    return {
        "soft_boundary_pixels": samples,
        "light_neutral_pixels": bright_count,
        "dark_neutral_pixels": dark_count,
        "review_candidates": candidates,
        "definition": "One-pixel visible boundary, alpha 17–239; light RGB >=245, dark RGB <=10.",
    }, focus


def checkerboard_hints(rgba: Image.Image) -> dict:
    """Look for grayscale half-period inversions in at least two opaque corners."""
    if rgba.getchannel("A").getextrema() != (255, 255):
        return {"tested": False, "matched_corners": [], "candidate_tile_sizes_px": []}
    # Small corner patches avoid treating the foreground as background texture.
    size = min(128, rgba.width // 4, rgba.height // 4)
    if size < 16:
        return {"tested": False, "matched_corners": [], "candidate_tile_sizes_px": []}
    origins = {
        "top_left": (0, 0), "top_right": (rgba.width - size, 0),
        "bottom_left": (0, rgba.height - size), "bottom_right": (rgba.width - size, rgba.height - size),
    }
    matches, tile_sizes = [], set()
    for name, (left, top) in origins.items():
        patch = rgba.crop((left, top, left + size, top + size)).convert("RGB")
        pixels = patch.load()
        samples = [pixels[x, y] for y in range(0, size, 4) for x in range(0, size, 4)]
        neutral_fraction = sum(max(pixel) - min(pixel) <= 8 for pixel in samples) / len(samples)
        if neutral_fraction < 0.9:
            continue
        luma = patch.convert("L").load()
        for tile in (4, 6, 8, 12, 16, 24, 32):
            if size < 3 * tile:
                continue
            same_x = same_y = flip_x = flip_y = 0
            count = 0
            for y in range(0, size - 2 * tile, 3):
                for x in range(0, size - 2 * tile, 3):
                    value = luma[x, y]
                    same_x += abs(value - luma[x + 2 * tile, y])
                    same_y += abs(value - luma[x, y + 2 * tile])
                    flip_x += abs(value - luma[x + tile, y])
                    flip_y += abs(value - luma[x, y + tile])
                    count += 1
            if count and max(same_x, same_y) / count <= 3 and min(flip_x, flip_y) / count >= 12:
                matches.append(name)
                tile_sizes.add(tile)
                break
    return {"tested": True, "matched_corners": matches, "candidate_tile_sizes_px": sorted(tile_sizes)}


def preview_color(image: Image.Image, profile: bytes | None) -> tuple[Image.Image, str, list[dict]]:
    rgba = image.convert("RGBA")
    if not profile:
        return rgba, "assumed_srgb", []
    try:
        from PIL import ImageCms
    except ImportError:
        return rgba, "profile_unreadable", [issue("profile_unreadable", "fact", "Colour profile support is unavailable; preview colours may differ.")]
    try:
        source_profile = ImageCms.ImageCmsProfile(io.BytesIO(profile))
        target_profile = ImageCms.createProfile("sRGB")
        # Use the source's native colour mode so CMYK profiles remain valid.
        color_source = image.convert("CMYK") if image.mode == "CMYK" else image.convert("RGB")
        converted = ImageCms.profileToProfile(color_source, source_profile, target_profile, outputMode="RGB")
        converted.putalpha(rgba.getchannel("A"))
        return converted, "converted_to_srgb", []
    except (OSError, ValueError, TypeError, ImageCms.PyCMSError):
        return rgba, "profile_unreadable", [issue("profile_unreadable", "fact", "The embedded colour profile could not be converted; preview colours may differ.")]


def png_data_uri(image: Image.Image) -> str:
    # Fresh image strips metadata; zero-alpha RGB is not needed by the report.
    alpha = image.getchannel("A")
    visible = alpha.point(lambda value: 255 if value else 0)
    cleaned = Image.composite(image, Image.new("RGBA", image.size, (0, 0, 0, 0)), visible)
    clean = Image.new("RGBA", cleaned.size)
    clean.paste(cleaned)
    stream = io.BytesIO()
    clean.save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def previews(rgba: Image.Image, focus: Image.Image) -> dict:
    overview = rgba.copy()
    overview.thumbnail((480, 480), Image.Resampling.LANCZOS)
    bbox = focus.getbbox()
    if bbox:
        # The left edge of the first nonempty row is an actual mask pixel.
        row_bbox = focus.crop((0, bbox[1], rgba.width, bbox[1] + 1)).getbbox()
        x, y = row_bbox[0], bbox[1]
    else:
        x, y = rgba.width // 2, rgba.height // 2
    side = min(64, rgba.width, rgba.height)
    left = min(max(x - side // 2, 0), rgba.width - side)
    top = min(max(y - side // 2, 0), rgba.height - side)
    region = (left, top, left + side, top + side)
    zoom = rgba.crop(region).resize((256, 256), Image.Resampling.NEAREST)
    return {"overview": png_data_uri(overview), "zoom": png_data_uri(zoom), "zoom_region": list(region)}


def inspect_file(path: Path, label: str | None = None) -> tuple[dict, dict]:
    result = {"label": label or path.name, "status": "error", "diagnostics": []}
    try:
        original_hash = sha256(path)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as source:
                if source.format not in {"PNG", "WEBP", "JPEG"}:
                    raise ValueError("Only static PNG, WebP, and JPEG files are supported.")
                if getattr(source, "n_frames", 1) != 1:
                    raise ValueError("Animated images are not supported; export a single still first.")
                if source.width * source.height > MAX_PIXELS:
                    raise ValueError("Image exceeds the 40 megapixel limit.")
                image_format, mode = source.format, source.mode
                if image_format == "PNG":
                    with path.open("rb") as stream:
                        header = stream.read(25)
                    if len(header) == 25 and header[12:16] == b"IHDR" and header[24] == 16:
                        raise ValueError("16-bit PNGs are unsupported; export an 8-bit copy for inspection.")
                encoded_alpha = "A" in source.getbands() or "transparency" in source.info
                profile = source.info.get("icc_profile")
                source.load()
                image = ImageOps.exif_transpose(source)
                rgba = image.convert("RGBA")
                facts = alpha_facts(rgba, encoded_alpha)
                display, color_mode, diagnostics = preview_color(image, profile)
        edge, focus = edge_hints(display)
        checker = checkerboard_hints(display)
        if facts["state"] == "empty":
            diagnostics.append(issue("empty_image", "fact", "Every pixel is fully transparent; there is no visible content."))
        elif facts["state"] == "opaque":
            diagnostics.append(issue("no_transparent_pixels", "fact", "No pixel is transparent, even if the file contains an alpha channel."))
        if facts["touches_canvas"]:
            diagnostics.append(issue("canvas_contact", "fact", "Visible content touches the canvas: " + ", ".join(facts["touches_canvas"]) + ". This may be intentional."))
        for candidate in edge["review_candidates"]:
            diagnostics.append(issue(candidate + "_soft_edge", "hint", candidate.title() + " neutral pixels occur along the soft boundary. Check them on opposite backgrounds; intentional outlines can produce the same hint."))
        if len(checker["matched_corners"]) >= 2:
            diagnostics.append(issue("checkerboard_like_border", "hint", "At least two opaque corners contain a repeating grayscale grid. This may be a painted transparency preview or an intentional pattern."))
        if sha256(path) != original_hash:
            raise ValueError("Input changed during inspection. Retry with a stable copy.")
        visual = previews(display, focus)
        result.update({
            "status": "review" if diagnostics else "no_flags",
            "sha256": original_hash, "format": image_format, "source_mode": mode,
            "width": rgba.width, "height": rgba.height, "preview_colour": color_mode,
            "alpha": facts, "edge": edge, "checkerboard": checker,
            "zoom_region": visual["zoom_region"], "diagnostics": diagnostics,
        })
        return result, visual
    except ValueError as exc:
        result["diagnostics"] = [issue("unsupported_input", "fact", str(exc))]
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        result["diagnostics"] = [issue("pixel_limit", "fact", "Image exceeds the 40 megapixel limit.")]
    except (OSError, UnidentifiedImageError, SyntaxError) as exc:
        result["diagnostics"] = [issue("decode_error", "fact", "Could not decode this file (" + type(exc).__name__ + ").")]
    return result, {}


def gather_inputs(inputs: list[Path], output: Path) -> list[tuple[Path, str]]:
    found, seen, labels = [], set(), set()
    for supplied in inputs:
        if not supplied.exists():
            raise ValueError("Input does not exist: " + str(supplied))
        if supplied.is_file():
            candidates = [(supplied, supplied.name)]
        else:
            candidates = []
            for directory, dirs, files in os.walk(supplied, followlinks=False):
                dirs[:] = sorted(name for name in dirs if not name.startswith(".") and not (Path(directory) / name).is_symlink() and (Path(directory) / name).resolve() != output)
                for name in sorted(files):
                    path = Path(directory) / name
                    if path.suffix.lower() in EXTENSIONS and not path.is_symlink():
                        candidates.append((path, supplied.name + "/" + path.relative_to(supplied).as_posix()))
        for path, label in candidates:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                base_label, suffix = label, 2
                while label in labels:
                    label = f"{base_label} [{suffix}]"
                    suffix += 1
                labels.add(label)
                found.append((path, label))
    if not found:
        raise ValueError("No supported images found. Directory scans include PNG, WebP, JPEG; hidden folders and symlinks are skipped.")
    return found


CSS = """
:root{color-scheme:light;--ink:#18251e;--paper:#f4f1e9;--line:#d5d8ce;--green:#38614b;--orange:#875125}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,-apple-system,sans-serif}
main{max-width:1120px;margin:auto;padding:48px 28px}header{border-bottom:1px solid var(--line);padding-bottom:28px}.eyebrow{font:12px/1.4 ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--green)}h1{font-size:clamp(32px,5vw,52px);letter-spacing:-.045em;line-height:1.1;margin:14px 0}h2{font-size:19px;margin:0;overflow-wrap:anywhere}p{margin:10px 0}.intro{max-width:680px;color:#536055}.summary{display:flex;flex-wrap:wrap;gap:24px;margin:24px 0 8px}.summary b{display:block;font-size:26px;line-height:1.2}.summary span{font-size:12px;color:#536055}
.bg-choice{position:absolute;opacity:0;width:1px;height:1px}.controls{position:sticky;top:0;z-index:2;padding:14px 0;background:var(--paper);border-bottom:1px solid var(--line);display:flex;align-items:center;gap:8px;flex-wrap:wrap}.controls label{cursor:pointer;padding:7px 15px;border:1px solid var(--line);border-radius:4px;font-size:13px}.controls span{font-size:12px;margin-right:12px}.bg-choice:focus-visible~.controls{outline:2px solid var(--green);outline-offset:2px}
#bg-grid:checked~.controls label[for=bg-grid],#bg-light:checked~.controls label[for=bg-light],#bg-dark:checked~.controls label[for=bg-dark],#bg-color:checked~.controls label[for=bg-color]{background:var(--ink);color:white;border-color:var(--ink)}
.asset{padding:28px 0;border-bottom:1px solid var(--line)}.asset-header{display:flex;align-items:start;justify-content:space-between;gap:16px;margin-bottom:16px}.tag{font:11px/1.3 ui-monospace,monospace;border:1px solid var(--line);padding:5px 9px;white-space:nowrap;border-radius:3px}.tag.review{border-color:#c4a58a;color:var(--orange)}.tag.error{border-color:#b06b5c;color:#873c2f}.view-pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}.view-pair figure{margin:0}.surface{height:280px;display:grid;place-items:center;overflow:hidden;border:1px solid #bcc6bc;background-color:#fff;background-image:linear-gradient(45deg,#e4e9e3 25%,transparent 25%),linear-gradient(-45deg,#e4e9e3 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#e4e9e3 75%),linear-gradient(-45deg,transparent 75%,#e4e9e3 75%);background-size:24px 24px;background-position:0 0,0 12px,12px -12px,-12px 0}.surface img{max-width:94%;max-height:94%;object-fit:contain}.surface.zoom img{image-rendering:pixelated;max-height:85%;max-width:85%}
#bg-light:checked~.gallery .surface{background:#fff}#bg-dark:checked~.gallery .surface{background:#15201a}#bg-color:checked~.gallery .surface{background:#ddb969}figcaption{font:12px/1.5 ui-monospace,monospace;color:#536055;margin-top:7px}.facts{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}.fact{border-top:1px solid var(--line);padding-top:8px}.fact small{display:block;font-size:11px;color:#647066}.fact strong{font:14px/1.5 ui-monospace,monospace;font-weight:500}.notes{list-style:none;padding:0;margin:0}.notes li{margin:7px 0;font-size:13px;max-width:920px}.kind{display:inline-block;min-width:38px;font:10px/1.5 ui-monospace,monospace;text-transform:uppercase;color:var(--green)}.kind.hint{color:var(--orange)}details{font-size:12px;margin-top:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:11px/1.6 ui-monospace,monospace;color:#536055}.empty-notes{font-size:13px;color:#536055}footer{font-size:12px;color:#647066;margin-top:28px}footer p{max-width:900px}
@media(max-width:650px){main{padding:28px 16px}.view-pair{grid-template-columns:1fr}.surface{height:250px}.facts{grid-template-columns:repeat(2,1fr)}.summary{gap:18px}.asset-header{flex-direction:column;gap:8px}}
"""


def render_html(records: list[dict], visuals: list[dict], summary: dict) -> str:
    cards = []
    labels = {"no_flags": "No automatic flags", "review": "Review", "error": "Unreadable / unsupported"}
    for number, (record, visual) in enumerate(zip(records, visuals), 1):
        escaped_label = html.escape(record["label"])
        view = facts = ""
        if visual:
            region = ", ".join(str(value) for value in record["zoom_region"])
            view = f'<div class="view-pair"><figure><div class="surface"><img src="{visual["overview"]}" alt="Overview of {escaped_label}"></div><figcaption>Fit view · preview only</figcaption></figure><figure><div class="surface zoom"><img src="{visual["zoom"]}" alt="Pixel detail of {escaped_label}"></div><figcaption>Pixel detail · source region [{region}]</figcaption></figure></div>'
            alpha = record["alpha"]
            fact_pairs = [("Canvas", f'{record["width"]} × {record["height"]}'), ("Fully transparent", f'{alpha["transparent_percent"]:g}%'), ("Semitransparent", f'{alpha["semitransparent_percent"]:g}%'), ("Visible content", alpha["state"])]
            facts = '<div class="facts">' + "".join(f'<div class="fact"><small>{key}</small><strong>{value}</strong></div>' for key, value in fact_pairs) + '</div>'
        notes = "".join(f'<li><span class="kind {item["kind"]}">{item["kind"]}</span> {html.escape(item["message"])}</li>' for item in record["diagnostics"])
        notes = '<ul class="notes">' + notes + '</ul>' if notes else '<p class="empty-notes">No automatic flags. Check the image on dark and light backgrounds before delivery.</p>'
        details = html.escape(json.dumps(record, indent=2, ensure_ascii=False))
        cards.append(f'<article class="asset"><div class="asset-header"><h2>{number:02d} / {escaped_label}</h2><span class="tag {record["status"]}">{labels[record["status"]]}</span></div>{view}{facts}{notes}<details><summary>Measurements &amp; source fingerprint</summary><pre>{details}</pre></details></article>')
    counters = "".join(f'<div><b>{summary[key]}</b><span>{label}</span></div>' for key, label in [("total", "files"), ("no_flags", "no automatic flags"), ("review", "to review"), ("error", "input errors")])
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>Alpha Preflight · Inspection report</title><style>{CSS}</style></head>
<body><main><header><div class="eyebrow">Alpha Preflight / v{VERSION}</div><h1>Look at the edges.</h1><p class="intro">Transparency facts and visual review, in one place. Change the background to see what the file will look like in use.</p><div class="summary">{counters}</div></header>
<input class="bg-choice" id="bg-grid" type="radio" name="background" checked><input class="bg-choice" id="bg-light" type="radio" name="background"><input class="bg-choice" id="bg-dark" type="radio" name="background"><input class="bg-choice" id="bg-color" type="radio" name="background"><nav class="controls" aria-label="Preview background"><span>Preview background</span><label for="bg-grid">Grid</label><label for="bg-light">Light</label><label for="bg-dark">Dark</label><label for="bg-color">Ochre</label></nav>
<section class="gallery">{"".join(cards)}</section><footer><p>Facts are measured from the file. Hints are candidate patterns, not defect verdicts; intentional outlines and tiled artwork can trigger them. No flags does not certify visual quality. Source files were read, not changed.</p><p>Preview pixels are 8-bit sRGB (untagged files are assumed sRGB). Source colour profiles are converted when readable. Reports embed reduced previews with no source metadata or network requests. They still contain your images; share them only when appropriate.</p></footer></main></body></html>'''


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, nargs="+", help="Image files or folders; folders are scanned recursively.")
    parser.add_argument("--out", type=Path, required=True, help="A new report directory (existing directories are never overwritten).")
    parser.add_argument("--fail-on-review", action="store_true", help="Exit 2 if any file needs review; input errors always exit 1.")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args(argv)
    output = args.out.resolve()
    if output.exists():
        parser.error("Output already exists; choose a new directory.")
    try:
        inputs = gather_inputs(args.inputs, output)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    if len(inputs) > 100:
        parser.error("Limit is 100 images per report; split the input into smaller batches.")
    records, visuals = [], []
    for path, label in inputs:
        record, visual = inspect_file(path, label)
        records.append(record)
        visuals.append(visual)
    summary = {"total": len(records), **{status: sum(record["status"] == status for record in records) for status in ("no_flags", "review", "error")}}
    report = {"schema_version": 1, "tool": "alpha-preflight", "tool_version": VERSION, "summary": summary, "files": records}
    try:
        output.mkdir(parents=True, exist_ok=False)
        (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (output / "index.html").write_text(render_html(records, visuals, summary), encoding="utf-8")
    except OSError as exc:
        print("Could not write the report: " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps({"report": str(output / "index.html"), "json": str(output / "report.json"), **summary}, ensure_ascii=False))
    return 1 if summary["error"] else 2 if args.fail_on_review and summary["review"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
