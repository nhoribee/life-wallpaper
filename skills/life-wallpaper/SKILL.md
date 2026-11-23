---
name: life-wallpaper
description: >-
  Generate a Conway's Game of Life wallpaper for each connected display at its native
  resolution and set it as that display's desktop picture (macOS). Use when the user asks to
  "refresh / update the wallpaper", "new life wallpaper", or "life-wallpaper".
---

This skill only calls the bundled CLI and reports the result. Display detection, rendering,
setting the desktop picture and pruning old images are all done by the CLI.

`<root>` below is the plugin root: `${CLAUDE_PLUGIN_ROOT}` when installed as a plugin,
otherwise two folders above this SKILL.md.

## Steps

1. Turn the request into arguments (table below). With no specific request, pass none.
2. Run `"<root>/run.sh" apply <args>` (about 3–10 seconds per display). Quote the path, pass
   each argument as its own word, and use only the values in the table below: numbers for
   `--seed` / `--keep`, and for `--config` only a file name that `ls "<root>/config/"` lists.
3. Report stdout as a table: one line per display with name, resolution, seed, seconds,
   whether it was applied, and the image path. Branch on the exit code:
   - 0: every display was set (with `--dry-run`, every image was generated)
   - 1: if per-display lines exist, report which displays failed and why (the others were
     changed). If none exist, listing displays or loading the config failed; report stderr.
   - 2: argument error; re-check the arguments.

| Request | Arguments |
|---|---|
| (nothing specific) | none. Pattern `10_motif_field_hires_t1500`, random seed per display |
| "use seed 42" | `--seed 42` (same seed on every display) |
| "generate only", "don't set it" | `--dry-run` (also keeps old images) |
| "a different pattern" | `--config <name listed by ls "<root>/config/">` |
| "t150" (150 generations, finer cells) | `--config 09_motif_field_hires` |
| "keep more" | `--keep <count>` (default 5) |

## Gotchas

- Requires macOS and [uv](https://docs.astral.sh/uv/). The first run creates a virtualenv.
- Only the Space currently shown on each display changes. Images set on other Spaces are
  deleted once they fall outside `--keep`, and those Spaces fall back to the macOS default.
- There is no "undo". The same config and seed reproduce the same image, so look up the
  previous seed in the JSON next to each image and pass it with `--seed` (only possible when
  all displays used the same seed).
- Images are written to `~/Pictures/life-wallpaper/desktop/` (override the parent folder with
  the `LIFE_WALLPAPER_HOME` environment variable).
