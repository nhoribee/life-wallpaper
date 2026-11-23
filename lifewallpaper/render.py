"""盤面を画像にする。色の階調、セルの拡大、画面の大きさへの合わせ込み、ファイルへの保存。"""

from pathlib import Path

import numpy as np
import numpy.typing as npt
from PIL import Image

from lifewallpaper.models import Grid, Heat, Resolution, Rgb

# 回数の少ないセルから多いセルへの色の階調（位置 0〜1 と RGB）
PALETTES: dict[str, list[tuple[float, tuple[int, int, int]]]] = {
    "ember": [
        (0.0, (10, 10, 12)),
        (0.3, (120, 20, 10)),
        (0.6, (220, 100, 20)),
        (1.0, (255, 230, 200)),
    ],
    "cyanotype": [
        (0.0, (8, 10, 25)),
        (0.3, (15, 50, 120)),
        (0.6, (30, 130, 200)),
        (1.0, (180, 220, 240)),
    ],
    "phosphor": [
        (0.0, (8, 12, 8)),
        (0.3, (10, 80, 40)),
        (0.6, (30, 180, 100)),
        (1.0, (180, 240, 200)),
    ],
    "mono": [
        (0.0, (15, 15, 18)),
        (0.3, (60, 60, 65)),
        (0.6, (140, 140, 145)),
        (1.0, (235, 235, 230)),
    ],
}


def scale_up(image: Rgb, cell_size: int) -> Rgb:
    """1セルを `cell_size` ピクセル四方に拡大する。"""
    return np.repeat(np.repeat(image, cell_size, axis=0), cell_size, axis=1)


def apply_palette(normalized: npt.NDArray[np.float64], palette_name: str) -> Rgb:
    """0〜1 の値を、階調の色にする。"""
    stops = PALETTES[palette_name]
    height, width = normalized.shape
    result: Rgb = np.zeros((height, width, 3), dtype=np.uint8)

    for index in range(len(stops) - 1):
        low, low_color = stops[index]
        high, high_color = stops[index + 1]
        mask = (normalized >= low) & (normalized < high)
        if index == len(stops) - 2:
            mask |= normalized == high
        fraction = np.where(mask, (normalized - low) / (high - low + 1e-10), 0)
        for channel in range(3):
            blended = low_color[channel] + fraction * (high_color[channel] - low_color[channel])
            result[:, :, channel] = np.where(mask, blended.astype(np.uint8), result[:, :, channel])

    return result


def render_snapshot(
    grid: Grid, cell_size: int, bg_color: tuple[int, ...], fg_color: tuple[int, ...]
) -> Rgb:
    """盤面を、生きているセルの色と背景の色の2色で描く。"""
    height, width = grid.shape
    image: Rgb = np.full((height, width, 3), bg_color, dtype=np.uint8)
    alive = grid == 1
    for channel in range(3):
        image[:, :, channel] = np.where(alive, fg_color[channel], bg_color[channel])
    return scale_up(image, cell_size)


def render_snapshot_classified(
    motif_map: Grid, cell_size: int, lut: npt.NDArray[np.float64]
) -> Rgb:
    """モチーフの番号の盤面を、モチーフごとの色で描く。"""
    return scale_up(lut.astype(np.uint8)[motif_map], cell_size)


def normalize_heat(total: Heat, use_log: bool, clip_percentile: float) -> npt.NDArray[np.float64]:
    """回数を 0〜1 にそろえる。上位の外れ値は `clip_percentile` で頭打ちにする。"""
    heat = total.astype(np.float64)
    if use_log:
        heat = np.log1p(heat)
    clip_value = np.percentile(heat[heat > 0], clip_percentile) if np.any(heat > 0) else 1.0
    heat = np.clip(heat, 0, clip_value)
    peak = heat.max()
    if peak > 0:
        heat /= peak
    return heat


def render_heatmap(
    heat: Heat,
    cell_size: int,
    palette_name: str,
    use_log: bool = True,
    clip_percentile: float = 99.0,
) -> Rgb:
    """セルごとの回数を、階調の色で描く。"""
    normalized = normalize_heat(heat, use_log, clip_percentile)
    return scale_up(apply_palette(normalized, palette_name), cell_size)


def render_heatmap_classified(
    stack: npt.NDArray[np.uint32],
    cell_size: int,
    bg_color: tuple[int, ...],
    lut: npt.NDArray[np.float64],
    use_log: bool = True,
    clip_percentile: float = 99.0,
) -> Rgb:
    """モチーフごとの回数を、いちばん多いモチーフの色で描く。回数の多いセルほど明るくする。"""
    total: Heat = stack.sum(axis=0, dtype=np.uint32)
    strength = normalize_heat(total, use_log, clip_percentile)
    dominant = stack.argmax(axis=0)
    dominant = np.where(total > 0, dominant, 0)

    base = lut[dominant]
    background = np.array(bg_color, dtype=np.float64)

    # 背景の色からモチーフの色へ寄せ、いちばん回数の多いセルは白へ持ち上げる
    rgb = background + strength[:, :, None] * (base - background)
    hot = np.clip((strength - 0.8) / 0.2, 0, 1)[:, :, None]
    rgb = rgb + hot * 0.6 * (255.0 - rgb)
    return scale_up(rgb.astype(np.uint8), cell_size)


def fit_to_resolution(
    rgb: Rgb, resolution: Resolution, bg_color: tuple[int, ...], fill_with_edge: bool
) -> Rgb:
    """画像を、画面の大きさにぴったり合わせる。

    解像度がセルの大きさで割り切れないと、右と下に数ピクセルの端数が残る。
    端数が残ると macOS が壁紙をわずかに拡大し、セルの縁がにじむので、埋める。

    Args:
        rgb: セルを拡大したあとの画像。
        resolution: 画面の大きさ。
        bg_color: 背景の色。
        fill_with_edge: True なら端のピクセルを延ばして埋め、False なら背景の色で埋める。
    """
    height, width = resolution.height, resolution.width
    if rgb.shape[:2] == (height, width):
        return rgb
    if fill_with_edge:
        padding = ((0, height - rgb.shape[0]), (0, width - rgb.shape[1]), (0, 0))
        return np.pad(rgb, padding, mode="edge")
    canvas: Rgb = np.empty((height, width, 3), dtype=rgb.dtype)
    canvas[:] = bg_color
    canvas[: rgb.shape[0], : rgb.shape[1]] = rgb
    return canvas


def save_image(rgb: Rgb, path: Path) -> None:
    """画像を、劣化なしで保存する。

    色の数が256以下の PNG は、同じ色のままパレットつきの PNG（PNG-8、ディザなし）にする。
    縁がにじまず、ファイルがずっと小さくなる。
    """
    image = Image.fromarray(rgb)
    if path.suffix == ".webp":
        image.save(path, lossless=True, quality=100, method=6)
        return
    colors = image.getcolors(maxcolors=256)
    if colors:
        image = image.convert(
            "P", palette=Image.Palette.ADAPTIVE, colors=len(colors), dither=Image.Dither.NONE
        )
    image.save(path, optimize=True)
