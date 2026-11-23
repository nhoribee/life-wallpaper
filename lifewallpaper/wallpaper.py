"""ライフゲームの静止画。設定と seed から盤面を動かし、画面の大きさの画像にして保存する。"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from lifewallpaper.config import ConfigError
from lifewallpaper.life import accumulate_heat, advance, build_initial_state
from lifewallpaper.models import LifeConfig, Resolution, Rgb
from lifewallpaper.motifs import accumulate_heat_by_motif, classify_final, motif_lut
from lifewallpaper.render import (
    fit_to_resolution,
    render_heatmap,
    render_heatmap_classified,
    render_snapshot,
    render_snapshot_classified,
    save_image,
)

DEFAULT_CELL_SIZE = 8
DEFAULT_BG_COLOR = [10, 10, 12]


@dataclass(frozen=True)
class Still:
    """描いた静止画と、盤面の大きさ。"""

    rgb: Rgb
    rows: int
    cols: int


def grid_shape(resolution: Resolution, cell_size: int) -> tuple[int, int]:
    """画面の大きさとセルの大きさから、盤面の行と列の数を返す（端数は切り捨てる）。

    Raises:
        ConfigError: 解像度がセルの大きさより小さく、盤面が1行1列に満たない。
    """
    rows, cols = resolution.height // cell_size, resolution.width // cell_size
    if rows < 1 or cols < 1:
        raise ConfigError(
            f"解像度（{resolution.width}x{resolution.height}）が、セルの大きさ（{cell_size}）より小さい"
        )
    return rows, cols


def render_still(config: LifeConfig, resolution: Resolution, seed: int) -> Still:
    """設定と seed から盤面を動かし、画面の大きさの画像を描く。ファイルには書かない。

    設定の `mode` が `snapshot` なら最後の盤面を、そのほか（`activity`、`survival`、`heatmap`）なら
    セルごとの回数を描く。`color_by_motif` が真なら、モチーフごとに色を分ける。
    """
    cell_size = config.get("cell_size", DEFAULT_CELL_SIZE)
    rows, cols = grid_shape(resolution, cell_size)

    rng = np.random.default_rng(seed)
    grid = build_initial_state(rows, cols, config, rng)

    steps = config.get("steps", 100)
    mode = config.get("mode", "snapshot")
    is_snapshot = mode == "snapshot"
    bg_color = tuple(config.get("bg_color", DEFAULT_BG_COLOR))
    use_log = config.get("use_log", True)
    clip_percentile = config.get("clip_percentile", 99.0)

    # 静止画では、color_by_motif を書かない設定は色分けしない（GIF と動画は色分けする）
    if config.get("color_by_motif", False):
        lut = motif_lut(config.get("motif_colors", {}), bg_color)
        auto_stable = config.get("motif_auto_stable", True)
        if is_snapshot:
            rgb = render_snapshot_classified(
                classify_final(grid, steps, auto_stable), cell_size, lut
            )
        else:
            stack = accumulate_heat_by_motif(grid, steps, mode, auto_stable)
            rgb = render_heatmap_classified(
                stack, cell_size, bg_color, lut, use_log, clip_percentile
            )
    elif is_snapshot:
        fg_color = tuple(config.get("fg_color", [200, 200, 200]))
        rgb = render_snapshot(advance(grid, steps), cell_size, bg_color, fg_color)
    else:
        heat = accumulate_heat(grid, steps, mode)
        palette = config.get("palette", "ember")
        rgb = render_heatmap(heat, cell_size, palette, use_log, clip_percentile)

    rgb = fit_to_resolution(rgb, resolution, bg_color, fill_with_edge=not is_snapshot)
    return Still(rgb, rows, cols)


def generate_still(
    config: LifeConfig, resolution: Resolution, seed: int, output_dir: Path, fmt: str = "png"
) -> Path:
    """静止画を作り、画像と、作り直すためのメタデータ（seed と設定）の JSON を保存する。

    Args:
        config: ライフゲームの設定。
        resolution: 画像の大きさ。
        seed: 乱数の seed。同じ設定と seed からは、同じ画像ができる。
        output_dir: 保存先のフォルダ。無ければ作る。
        fmt: 画像の形式（`png` か `webp`。どちらも劣化なし）。

    Returns:
        保存した画像のパス（`<設定の name>_<解像度の呼び名>_s<seed>.<fmt>`）。
    """
    still = render_still(config, resolution, seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{config.get('name', 'life')}_{resolution.label}_s{seed}"
    image_path = output_dir / f"{stem}.{fmt}"
    save_image(still.rgb, image_path)
    metadata = {
        "seed": seed,
        "resolution": resolution.label,
        "grid_rows": still.rows,
        "grid_cols": still.cols,
        "config": config,
    }
    (output_dir / f"{stem}.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return image_path
