"""Draw deterministic inspection fixtures; no model or remote assets needed."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def badge() -> Image.Image:
    scale = 4
    image = Image.new("RGBA", (256 * scale, 256 * scale))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((48 * scale, 48 * scale, 208 * scale, 208 * scale), radius=45 * scale, fill=(55, 128, 98, 255))
    # A small, simple leaf mark gives the preview a useful interior reference.
    draw.ellipse((88 * scale, 78 * scale, 155 * scale, 159 * scale), fill=(222, 185, 104, 255))
    draw.line((108 * scale, 156 * scale, 145 * scale, 101 * scale), fill=(55, 128, 98, 255), width=5 * scale)
    return image.resize((256, 256), Image.Resampling.LANCZOS)


def make_samples(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    clean = badge()
    clean.save(output / "01-clean-alpha.png")
    white = Image.new("RGBA", clean.size, "white")
    Image.alpha_composite(white, clean).save(output / "02-opaque-with-alpha-channel.png")
    grid = Image.new("RGBA", clean.size, "white")
    draw = ImageDraw.Draw(grid)
    for y in range(0, 256, 8):
        for x in range(0, 256, 8):
            draw.rectangle((x, y, x + 7, y + 7), fill=(225, 225, 225, 255) if (x // 8 + y // 8) % 2 else (250, 250, 250, 255))
    # Keep the corners exposed so the grid heuristic has something to inspect.
    center = clean.resize((144, 144), Image.Resampling.LANCZOS)
    grid.alpha_composite(center, (56, 56))
    grid.save(output / "03-painted-grid.png")
    fringe = clean.copy()
    alpha = fringe.getchannel("A")
    white_fringe = Image.new("RGBA", fringe.size, "white")
    white_fringe.putalpha(alpha)
    fringe = Image.composite(fringe, white_fringe, alpha.point(lambda value: 255 if value >= 240 else 0))
    fringe.save(output / "04-light-soft-edge.png")
    clipped = Image.new("RGBA", (256, 256))
    clipped.alpha_composite(clean, (-55, 0))
    clipped.save(output / "05-canvas-contact.png")
    Image.new("RGBA", (256, 256)).save(output / "06-empty-alpha.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path, help="New directory for six generated sample files.")
    make_samples(parser.parse_args().out)
