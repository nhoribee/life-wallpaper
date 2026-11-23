"""ライフゲームの GIF と動画。世代ごとの盤面を、コマにして書き出す。"""

import logging
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import numpy.typing as npt
from PIL import Image

from lifewallpaper import ffmpeg
from lifewallpaper.life import build_initial_state, step
from lifewallpaper.models import Grid, LifeConfig, Resolution, Rgb
from lifewallpaper.motifs import MOTIF_ORDER, classify, motif_lut
from lifewallpaper.render import scale_up
from lifewallpaper.wallpaper import DEFAULT_BG_COLOR, DEFAULT_CELL_SIZE, grid_shape

logger = logging.getLogger(__name__)

_PROGRESS_EVERY = 300  # 動画で、何世代ごとに進み具合を知らせるか


def _color_lut(config: LifeConfig) -> npt.NDArray[np.float64]:
    """モチーフの番号（色分けしないときは 0 と 1）から RGB を引く表を返す。"""
    bg_color = tuple(config.get("bg_color", DEFAULT_BG_COLOR))
    # GIF と動画では、color_by_motif を書かない設定も色分けする（静止画は色分けしない）
    if config.get("color_by_motif", True):
        return motif_lut(config.get("motif_colors", {}), bg_color)
    fg_color = config.get("fg_color", [200, 220, 200])
    return np.array([list(bg_color)] + [fg_color] * len(MOTIF_ORDER), dtype=np.float64)


def _frames(
    config: LifeConfig,
    rows: int,
    cols: int,
    seed: int,
    generations: int,
    stride: int,
    trail_decay: float,
) -> Iterator[tuple[int, Rgb]]:
    """最初の盤面と、`stride` 世代ごとの盤面を、（世代、1セル1ピクセルの画像）で順に返す。

    `trail_decay` が 0 より大きいと、死んだセルを、最後に生きていたときの色のまま少しずつ暗くする。
    """
    rng = np.random.default_rng(seed)
    grid = build_initial_state(rows, cols, config, rng)
    background = np.array(config.get("bg_color", DEFAULT_BG_COLOR), dtype=np.float64)
    lut = _color_lut(config)
    color_by_motif = config.get("color_by_motif", True)
    auto_stable = config.get("motif_auto_stable", True)

    def motif_map_of(board: Grid) -> Grid:
        return classify(board, auto_stable) if color_by_motif else board.astype(np.uint8)

    last_motif = motif_map_of(grid).copy()
    trail = (grid > 0).astype(np.float64)

    def frame() -> Rgb:
        rgb = background + trail[:, :, None] * (lut[last_motif] - background)
        image: Rgb = rgb.astype(np.uint8)
        return image

    yield 0, frame()
    for generation in range(1, generations + 1):
        grid = step(grid)
        alive = grid > 0
        last_motif = np.where(alive, motif_map_of(grid), last_motif)
        if trail_decay > 0:
            trail = np.maximum(alive.astype(np.float64), trail * trail_decay)
        else:
            trail = alive.astype(np.float64)
        if generation % stride == 0:
            yield generation, frame()


def render_gif(config: LifeConfig, resolution: Resolution, seed: int, output_dir: Path) -> Path:
    """盤面の移り変わりを GIF にして保存する。

    大きさは、設定の `gif.max_width` に収まるよう、1セルを整数倍に拡大して決める。

    Returns:
        保存した GIF のパス（`<設定の name>_<解像度の呼び名>_s<seed>.gif`）。
    """
    gif = config.get("gif", {})
    duration_ms = gif.get("duration_ms", 70)
    rows, cols = grid_shape(resolution, config.get("cell_size", DEFAULT_CELL_SIZE))
    gif_cell = max(1, gif.get("max_width", 1280) // cols)

    frames = [
        Image.fromarray(scale_up(rgb, gif_cell)).convert(
            "P", palette=Image.Palette.ADAPTIVE, colors=256, dither=Image.Dither.NONE
        )
        for _, rgb in _frames(
            config,
            rows,
            cols,
            seed,
            generations=gif.get("generations", 240),
            stride=gif.get("stride", 1),
            trail_decay=gif.get("trail", 0.0),
        )
    ]
    durations = [duration_ms] * len(frames)
    durations[-1] = max(duration_ms, gif.get("hold_last_ms", 1200))

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{config.get('name', 'life')}_{resolution.label}_s{seed}.gif"
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    logger.info("GIF のコマ: %d", len(frames))
    return path


def render_video(config: LifeConfig, resolution: Resolution, seed: int, output_dir: Path) -> Path:
    """盤面の長い移り変わりを MP4 にして保存する（ffmpeg が要る）。

    設定の `gif` を下敷きにして、`video` で上書きした値を使う。

    Returns:
        保存した動画のパス（`<設定の name>_<解像度の呼び名>_s<seed>.mp4`）。

    Raises:
        lifewallpaper.ffmpeg.FfmpegError: ffmpeg が無い、または書き出しに失敗した。
    """
    gif = config.get("gif", {})
    video = config.get("video", {})
    generations = video.get("generations", gif.get("generations", 1200))
    stride = video.get("stride", gif.get("stride", 1))
    fps = video.get("fps", 30)
    max_width = video.get("max_width", gif.get("max_width", 1280))
    trail_decay = video.get("trail", gif.get("trail", 0.0))

    rows, cols = grid_shape(resolution, config.get("cell_size", DEFAULT_CELL_SIZE))
    video_cell = max(1, max_width // cols)
    # yuv420p は、幅と高さが偶数でなければならない
    width = cols * video_cell // 2 * 2
    height = rows * video_cell // 2 * 2

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{config.get('name', 'life')}_{resolution.label}_s{seed}.mp4"
    with ffmpeg.open_encoder(path, width, height, fps) as encoder:
        for generation, rgb in _frames(config, rows, cols, seed, generations, stride, trail_decay):
            encoder.write(scale_up(rgb, video_cell)[:height, :width].tobytes())
            if generation and generation % _PROGRESS_EVERY == 0:
                logger.info("  世代 %d/%d", generation, generations)
    frame_count = generations // stride + 1
    logger.info("動画のコマ: %d（%.0f 秒）", frame_count, frame_count / fps)
    return path
