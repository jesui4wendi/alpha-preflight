# Validation notes

Local validation completed on macOS with Python 3.13 and Pillow 12.3.0.

- 22 behavioural tests pass, including actual pixel counts, palette/key transparency, opaque alpha, empty content, canvas contact, foreground-over-grid detection, neutral soft-edge hints, EXIF orientation, profile conversion/fallback, static WebP, unsupported animation and 16-bit input, damaged-file batch handling, original-file preservation, metadata-free previews, duplicate input handling, and existing-output preservation.
- Skill Creator's format validator passes. Codex UI metadata is valid YAML and references the packaged skill.
- The standalone skill ZIP was extracted outside the repository and its own script generated the six-sample report. No repository-only resource was needed.
- Browser review verified light/dark switching, keyboard selection, image display, and the visible light-edge hint. A narrow browser layout also keeps the background controls and previews usable.
- The committed demonstration is produced from the six script-drawn fixtures. It yields one file with no automatic flags, five files to review, and zero input errors. These counts describe the intentionally mixed sample set, not accuracy on a representative dataset.

The GitHub Actions workflow passed on Ubuntu and Windows with Python 3.10 and 3.13 for commit `1c8a4b794a85bb0908d3bf8d1498981af9419bae`: [run 37403279519](https://github.com/jesui4wendi/alpha-preflight/actions/runs/37403279519). All 23 published files were downloaded and matched the local files byte-for-byte. Large production datasets, all colour profiles, print workflows, and real-world halo recall have not been validated. The report exposes the heuristic evidence and does not claim a quality certification.
