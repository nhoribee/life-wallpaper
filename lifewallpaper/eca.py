"""1次元のセルオートマトン（Wolfram の256のルール）の静止画と動画。

横が時間（左から右）、縦が空間で、上下はつながっている。ルールは設定の `rule` で選ぶ。
"""

import json
import logging
from pathlib import Path

import numpy as np

from lifewallpaper import ffmpeg
from lifewallpaper.models import EcaConfig, Grid, Resolution, Rgb
from lifewallpaper.render import save_image, scale_up
from lifewallpaper.wallpaper import DEFAULT_BG_COLOR, DEFAULT_CELL_SIZE, grid_shape

logger = logging.getLogger(__name__)

_DEFAULT_FG_COLOR = [200, 220, 200]
_PROGRESS_EVERY_SECONDS = 30  # 動画で、何秒ぶんごとに進み具合を知らせるか


def rule_table(rule: int) -> Grid:
    """ルールの番号を、（左、自分、右）の8通りの並びから次の状態を引く表にする。"""
    return np.array([(rule >> index) & 1 for index in range(8)], dtype=np.uint8)


def step_1d(state: Grid, table: Grid) -> Grid:
    """1列の状態を、1ステップ進める。"""
    left = np.roll(state, 1)
    right = np.roll(state, -1)
    advanced: Grid = table[left * 4 + state * 2 + right]
    return advanced


def initial_state(rows: int, config: EcaConfig, rng: np.random.Generator) -> Grid:
    """最初の1列を作る。密度、種の数のどちらも無ければ、中央の1セルだけを生かす。"""
    state: Grid = np.zeros(rows, dtype=np.uint8)
    density = config.get("init_density", 0)
    seeds = config.get("init_seeds", 0)
    if density > 0:
        state = (rng.random(rows) < density).astype(np.uint8)
    elif seeds > 0:
        state[rng.integers(0, rows, seeds)] = 1
    else:
        state[rows // 2] = 1
    return state


def evolve(state: Grid, steps: int, table: Grid, burn_in: int = 0) -> tuple[Grid, Grid]:
    """`burn_in` ステップを捨ててから、`steps` ステップぶんの列を並べた盤面と、次の1列を返す。"""
    for _ in range(burn_in):
        state = step_1d(state, table)
    columns: Grid = np.zeros((state.shape[0], steps), dtype=np.uint8)
    for time in range(steps):
        columns[:, time] = state
        state = step_1d(state, table)
    return columns, state


def _colors(config: EcaConfig) -> tuple[Rgb, Rgb]:
    background = np.array(config.get("bg_color", DEFAULT_BG_COLOR), dtype=np.uint8)
    foreground = np.array(config.get("fg_color", _DEFAULT_FG_COLOR), dtype=np.uint8)
    return background, foreground


def _paint(grid: Grid, background: Rgb, foreground: Rgb) -> Rgb:
    image: Rgb = np.where(grid[:, :, None] == 1, foreground, background)
    return image


def generate_still(config: EcaConfig, resolution: Resolution, seed: int, output_dir: Path) -> Path:
    """静止画を作り、画像と、作り直すためのメタデータ（seed と設定）の JSON を保存する。

    画像の大きさは、解像度をセルの大きさで割った端数を切り捨てた大きさになる。

    Returns:
        保存した画像のパス（`<設定の name>_<解像度の呼び名>_s<seed>.png`）。
    """
    cell_size = config.get("cell_size", DEFAULT_CELL_SIZE)
    rows, steps = grid_shape(resolution, cell_size)

    table = rule_table(config["rule"])
    rng = np.random.default_rng(seed)
    state = initial_state(rows, config, rng)
    grid, _ = evolve(state, steps, table, config.get("burn_in", 0))
    rgb = scale_up(_paint(grid, *_colors(config)), cell_size)

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{config.get('name', 'eca')}_{resolution.label}_s{seed}"
    image_path = output_dir / f"{stem}.png"
    save_image(rgb, image_path)
    metadata = {
        "seed": seed,
        "resolution": resolution.label,
        "rows": rows,
        "steps": steps,
        "config": config,
    }
    (output_dir / f"{stem}.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return image_path


def render_video(config: EcaConfig, resolution: Resolution, seed: int, output_dir: Path) -> Path:
    """右の端から新しいステップが流れ込む、横スクロールの MP4 を保存する（ffmpeg が要る）。

    Returns:
        保存した動画のパス（`<設定の name>_<解像度の呼び名>_s<seed>.mp4`）。

    Raises:
        lifewallpaper.ffmpeg.FfmpegError: ffmpeg が無い、または書き出しに失敗した。
    """
    video = config.get("video", {})
    fps = video.get("fps", 30)
    duration_s = video.get("duration_s", 120)
    columns_per_frame = video.get("columns_per_frame", 1)

    cell_size = config.get("cell_size", DEFAULT_CELL_SIZE)
    rows, window = grid_shape(resolution, cell_size)
    video_cell = max(1, video.get("max_width", 1280) // window)
    # yuv420p は、幅と高さが偶数でなければならない
    width = window * video_cell // 2 * 2
    height = rows * video_cell // 2 * 2

    table = rule_table(config["rule"])
    rng = np.random.default_rng(seed)
    state = initial_state(rows, config, rng)
    buffer, state = evolve(state, window, table, config.get("burn_in", 0))
    background, foreground = _colors(config)

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{config.get('name', 'eca')}_{resolution.label}_s{seed}.mp4"
    frame_count = fps * duration_s
    with ffmpeg.open_encoder(path, width, height, fps) as encoder:
        for frame in range(frame_count):
            image = _paint(buffer, background, foreground)
            encoder.write(scale_up(image, video_cell)[:height, :width].tobytes())
            for _ in range(columns_per_frame):
                buffer = np.roll(buffer, -1, axis=1)
                buffer[:, -1] = state
                state = step_1d(state, table)
            if (frame + 1) % (fps * _PROGRESS_EVERY_SECONDS) == 0:
                logger.info("  %d 秒/%d 秒", (frame + 1) // fps, duration_s)
    logger.info("動画のコマ: %d（%d 秒）", frame_count, duration_s)
    return path
