from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageCms, ImageDraw, PngImagePlugin

SCRIPT = Path(__file__).resolve().parents[1] / "skills/alpha-preflight/scripts/inspect_alpha.py"
spec = importlib.util.spec_from_file_location("inspect_alpha", SCRIPT)
inspector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspector)


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def image(self, name="asset.png", color=(70, 170, 100, 255)):
        image = Image.new("RGBA", (64, 48))
        ImageDraw.Draw(image).rectangle((10, 8, 49, 39), fill=color)
        path = self.root / name
        image.save(path)
        return path

    def run_cli(self, inputs, output="report", extra=()):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return inspector.main([*(str(path) for path in inputs), "--out", str(self.root / output), *extra])

    def test_transparent_counts_and_margins(self):
        result, _ = inspector.inspect_file(self.image())
        self.assertEqual(result["status"], "no_flags")
        self.assertEqual(result["alpha"]["opaque_pixels"], 40 * 32)
        self.assertEqual(result["alpha"]["transparent_pixels"], 64 * 48 - 40 * 32)
        self.assertEqual(result["alpha"]["visible_bbox"], [10, 8, 50, 40])
        self.assertEqual(result["alpha"]["margins_px"], {"left": 10, "top": 8, "right": 14, "bottom": 8})

    def test_alpha_channel_is_not_proof_of_transparency(self):
        path = self.root / "opaque.png"
        Image.new("RGBA", (32, 32), (40, 120, 60, 255)).save(path)
        result, _ = inspector.inspect_file(path)
        self.assertTrue(result["alpha"]["encoded_alpha_or_transparency"])
        self.assertEqual(result["alpha"]["state"], "opaque")
        self.assertIn("no_transparent_pixels", [item["code"] for item in result["diagnostics"]])

    def test_palette_transparency(self):
        image = Image.new("P", (40, 40), 0)
        image.putpalette([0, 0, 0, 50, 170, 80] + [0, 0, 0] * 254)
        ImageDraw.Draw(image).rectangle((10, 10, 29, 29), fill=1)
        path = self.root / "palette.png"
        image.save(path, transparency=0)
        result, _ = inspector.inspect_file(path)
        self.assertEqual(result["alpha"]["transparent_pixels"], 1200)
        self.assertEqual(result["status"], "no_flags")

    def test_rgb_transparency_key(self):
        image = Image.new("RGB", (32, 32), (255, 0, 255))
        ImageDraw.Draw(image).rectangle((8, 8, 23, 23), fill=(40, 150, 80))
        path = self.root / "key.png"
        image.save(path, transparency=(255, 0, 255))
        result, _ = inspector.inspect_file(path)
        self.assertEqual(result["alpha"]["transparent_pixels"], 768)

    def test_empty_image_has_no_bounds(self):
        path = self.root / "empty.png"
        Image.new("RGBA", (24, 24), (100, 50, 150, 0)).save(path)
        result, visual = inspector.inspect_file(path)
        self.assertEqual(result["alpha"]["state"], "empty")
        self.assertIsNone(result["alpha"]["visible_bbox"])
        self.assertEqual(result["diagnostics"][0]["code"], "empty_image")
        with Image.open(io.BytesIO(base64.b64decode(visual["overview"].split(",", 1)[1]))) as preview:
            self.assertEqual(preview.getpixel((0, 0)), (0, 0, 0, 0))

    def test_canvas_contact_is_reported(self):
        path = self.root / "clipped.png"
        image = Image.new("RGBA", (40, 40))
        ImageDraw.Draw(image).rectangle((0, 10, 20, 29), fill=(40, 180, 90, 255))
        image.save(path)
        result, _ = inspector.inspect_file(path)
        self.assertEqual(result["alpha"]["touches_canvas"], ["left"])

    def test_uniform_translucency_is_counted(self):
        result, _ = inspector.inspect_file(self.image(color=(70, 170, 100, 128)))
        self.assertEqual(result["alpha"]["semitransparent_pixels"], 40 * 32)
        self.assertEqual(result["alpha"]["opaque_pixels"], 0)

    def test_white_boundary_is_a_hint_not_a_defect_verdict(self):
        image = Image.new("RGBA", (64, 64))
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, 53, 53), fill=(255, 255, 255, 128))
        draw.rectangle((11, 11, 52, 52), fill=(60, 170, 100, 255))
        path = self.root / "outline.png"
        image.save(path)
        result, _ = inspector.inspect_file(path)
        hint = next(item for item in result["diagnostics"] if item["code"] == "light_soft_edge")
        self.assertEqual(hint["kind"], "hint")
        self.assertIn("intentional", hint["message"])

    def test_checkerboard_is_a_hint_and_solid_white_is_not(self):
        image = Image.new("RGB", (128, 128))
        draw = ImageDraw.Draw(image)
        for y in range(0, 128, 8):
            for x in range(0, 128, 8):
                draw.rectangle((x, y, x + 7, y + 7), fill=(220, 220, 220) if (x // 8 + y // 8) % 2 else (250, 250, 250))
        path = self.root / "grid.png"
        image.save(path)
        result, _ = inspector.inspect_file(path)
        hints = [item for item in result["diagnostics"] if item["code"] == "checkerboard_like_border"]
        self.assertEqual(hints[0]["kind"], "hint")
        self.assertEqual(len(result["checkerboard"]["matched_corners"]), 4)
        Image.new("RGB", (128, 128), "white").save(path)
        result, _ = inspector.inspect_file(path)
        self.assertFalse(result["checkerboard"]["matched_corners"])

    def test_grid_behind_foreground_is_still_detected(self):
        image = Image.new("RGB", (256, 256))
        draw = ImageDraw.Draw(image)
        for y in range(0, 256, 8):
            for x in range(0, 256, 8):
                draw.rectangle((x, y, x + 7, y + 7), fill=(225, 225, 225) if (x // 8 + y // 8) % 2 else (250, 250, 250))
        draw.rounded_rectangle((82, 82, 173, 173), radius=20, fill=(50, 150, 90))
        path = self.root / "painted-grid-with-subject.png"
        image.save(path)
        result, _ = inspector.inspect_file(path)
        self.assertIn("checkerboard_like_border", [item["code"] for item in result["diagnostics"]])

    def test_exif_orientation_is_applied_before_measurements(self):
        image = Image.new("RGB", (40, 20), "green")
        exif = Image.Exif()
        exif[274] = 6
        path = self.root / "rotated.jpg"
        image.save(path, exif=exif)
        result, _ = inspector.inspect_file(path)
        self.assertEqual((result["width"], result["height"]), (20, 40))

    def test_profiles_are_converted_and_bad_profiles_are_reported(self):
        path = self.image()
        with Image.open(path) as source:
            image = source.copy()
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        image.save(path, icc_profile=profile)
        result, _ = inspector.inspect_file(path)
        self.assertEqual(result["preview_colour"], "converted_to_srgb")
        image.save(path, icc_profile=b"broken-profile")
        result, _ = inspector.inspect_file(path)
        self.assertEqual(result["status"], "review")
        self.assertEqual(result["preview_colour"], "profile_unreadable")

    def test_metadata_is_not_embedded_in_previews(self):
        path = self.image()
        with Image.open(path) as source:
            image = source.copy()
        info = PngImagePlugin.PngInfo()
        info.add_text("Author", "private-example-name")
        image.save(path, pnginfo=info)
        _, visual = inspector.inspect_file(path)
        with Image.open(io.BytesIO(base64.b64decode(visual["overview"].split(",", 1)[1]))) as preview:
            self.assertNotIn("Author", preview.info)

    def test_animation_is_not_silently_reduced_to_first_frame(self):
        path = self.root / "animated.png"
        Image.new("RGBA", (24, 24), "red").save(path, save_all=True, append_images=[Image.new("RGBA", (24, 24), "blue")], duration=100, loop=0)
        result, _ = inspector.inspect_file(path)
        self.assertEqual(result["status"], "error")
        self.assertIn("Animated", result["diagnostics"][0]["message"])

    def test_static_webp(self):
        path = self.image()
        target = self.root / "asset.webp"
        with Image.open(path) as image:
            image.save(target, lossless=True)
        result, _ = inspector.inspect_file(target)
        self.assertEqual(result["format"], "WEBP")
        self.assertEqual(result["alpha"]["visible_bbox"], [10, 8, 50, 40])

    def test_sixteen_bit_png_is_not_silently_quantized(self):
        path = self.root / "sixteen-bit.png"
        Image.new("I;16", (32, 32), 1).save(path)
        result, _ = inspector.inspect_file(path)
        self.assertEqual(result["status"], "error")
        self.assertIn("16-bit", result["diagnostics"][0]["message"])

    def test_bad_file_does_not_abort_batch_and_originals_are_unchanged(self):
        good = self.image()
        bad = self.root / "broken.png"
        bad.write_bytes(b"not-an-image")
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (good, bad)}
        self.assertEqual(self.run_cli([good, bad]), 1)
        report = json.loads((self.root / "report/report.json").read_text())
        self.assertEqual(report["summary"], {"total": 2, "no_flags": 1, "review": 0, "error": 1})
        for path, digest in before.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_review_exit_code_is_opt_in(self):
        path = self.root / "opaque.png"
        Image.new("RGB", (32, 32), "red").save(path)
        self.assertEqual(self.run_cli([path], "normal"), 0)
        self.assertEqual(self.run_cli([path], "strict", ["--fail-on-review"]), 2)

    def test_existing_output_is_preserved(self):
        path = self.image()
        output = self.root / "report"
        output.mkdir()
        sentinel = output / "index.html"
        sentinel.write_text("previous-report")
        with self.assertRaises(SystemExit) as failure:
            self.run_cli([path])
        self.assertEqual(failure.exception.code, 2)
        self.assertEqual(sentinel.read_text(), "previous-report")

    def test_scan_skips_hidden_directories_and_duplicate_inputs(self):
        path = self.image()
        hidden = self.root / ".hidden"
        hidden.mkdir()
        self.image(".hidden/ignored.png")
        found = inspector.gather_inputs([self.root, path], self.root / "report")
        self.assertEqual(len(found), 1)

    def test_same_named_files_have_distinct_report_labels(self):
        first = self.image()
        (self.root / "other").mkdir()
        second = self.image("other/asset.png", color=(150, 70, 100, 255))
        found = inspector.gather_inputs([first, second], self.root / "report")
        self.assertEqual(len(found), 2)
        self.assertNotEqual(found[0][1], found[1][1])

    def test_html_escapes_labels_and_has_no_scripts_or_network_assets(self):
        result, visual = inspector.inspect_file(self.image(), '<img src=x onerror="alert(1)">.png')
        report = inspector.render_html([result], [visual], {"total": 1, "no_flags": 1, "review": 0, "error": 0})
        self.assertIn("&lt;img", report)
        self.assertNotIn('<img src=x', report)
        self.assertNotIn("<script", report)
        self.assertNotIn('src="http', report)
        self.assertNotIn(str(self.root), report)


if __name__ == "__main__":
    unittest.main()
