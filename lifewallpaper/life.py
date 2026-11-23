"""ライフゲーム（Conway）の盤面。種のパターン、最初の盤面、世代の進め方。

盤面は上下と左右がつながっている（トーラス）。
"""

import numpy as np

from lifewallpaper.config import ConfigError
from lifewallpaper.models import Grid, Heat, LifeConfig

_GOSPER_GLIDER_GUN_CELLS = [
    (5, 1),
    (5, 2),
    (6, 1),
    (6, 2),
    (3, 13),
    (3, 14),
    (4, 12),
    (4, 16),
    (5, 11),
    (5, 17),
    (6, 11),
    (6, 15),
    (6, 17),
    (6, 18),
    (7, 11),
    (7, 17),
    (8, 12),
    (8, 16),
    (9, 13),
    (9, 14),
    (1, 25),
    (2, 23),
    (2, 25),
    (3, 21),
    (3, 22),
    (4, 21),
    (4, 22),
    (5, 21),
    (5, 22),
    (6, 23),
    (6, 25),
    (7, 25),
    (3, 35),
    (3, 36),
    (4, 35),
    (4, 36),
]


def _gosper_glider_gun() -> Grid:
    gun = np.zeros((11, 38), dtype=np.uint8)
    for row, col in _GOSPER_GLIDER_GUN_CELLS:
        gun[row, col] = 1
    return gun


# 種のパターン。設定の `patterns` と `scatter` の `name` で選ぶ
PRESETS: dict[str, Grid] = {
    "glider": np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], dtype=np.uint8),
    "r-pentomino": np.array([[0, 1, 1], [1, 1, 0], [0, 1, 0]], dtype=np.uint8),
    "acorn": np.array(
        [[0, 1, 0, 0, 0, 0, 0], [0, 0, 0, 1, 0, 0, 0], [1, 1, 0, 0, 1, 1, 1]], dtype=np.uint8
    ),
    "pulsar": np.array(
        [
            [0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
            [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
            [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
            [0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0],
            [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
            [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
            [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0],
        ],
        dtype=np.uint8,
    ),
    "pentadecathlon": np.array(
        [
            [0, 0, 1, 0, 0, 0, 0, 1, 0, 0],
            [1, 1, 0, 1, 1, 1, 1, 0, 1, 1],
            [0, 0, 1, 0, 0, 0, 0, 1, 0, 0],
        ],
        dtype=np.uint8,
    ),
    "gosper-glider-gun": _gosper_glider_gun(),
}


def neighbor_sum(grid: Grid) -> Grid:
    """各セルの、まわり8セルの生きている数を返す。"""
    up = np.roll(grid, 1, 0)
    down = np.roll(grid, -1, 0)
    total: Grid = (
        up
        + down
        + np.roll(grid, 1, 1)
        + np.roll(grid, -1, 1)
        + np.roll(up, 1, 1)
        + np.roll(up, -1, 1)
        + np.roll(down, 1, 1)
        + np.roll(down, -1, 1)
    )
    return total


def step(grid: Grid) -> Grid:
    """盤面を1世代進める。"""
    neighbors = neighbor_sum(grid)
    alive: Grid = ((neighbors == 3) | (grid & (neighbors == 2))).astype(np.uint8)
    return alive


def advance(grid: Grid, steps: int) -> Grid:
    """盤面を `steps` 世代進めて返す。"""
    for _ in range(steps):
        grid = step(grid)
    return grid


def accumulate_heat(grid: Grid, steps: int, mode: str) -> Heat:
    """`steps` 世代のあいだの、セルごとの回数を返す。

    Args:
        grid: 最初の盤面。
        steps: 進める世代の数。
        mode: `activity` なら生まれた回数、そのほか（`survival`、`heatmap`）なら生きていた回数。
    """
    heat: Heat = np.zeros(grid.shape, dtype=np.uint32)
    for _ in range(steps):
        new = step(grid)
        if mode == "activity":
            heat += (new == 1) & (grid == 0)
        else:
            heat += new
        grid = new
    return heat


def stamp_pattern(grid: Grid, pattern: Grid, row: int, col: int) -> None:
    """盤面の（row, col）を左上にして、パターンの生きているセルを書き込む（端は回り込む）。"""
    rows, cols = grid.shape
    for r, c in zip(*np.nonzero(pattern), strict=True):
        grid[(row + int(r)) % rows, (col + int(c)) % cols] = 1


def placement_origin(
    pattern: Grid, position: str | list[int], rows: int, cols: int
) -> tuple[int, int]:
    """設定の `position` から、パターンを置く左上のセルを返す。知らない値は左上の角にする。"""
    height, width = pattern.shape
    if isinstance(position, list):
        return position[0], position[1]
    if position == "center":
        return rows // 2 - height // 2, cols // 2 - width // 2
    if position == "top-left":
        return 5, 5
    if position == "top-right":
        return 5, cols - width - 5
    if position == "bottom-left":
        return rows - height - 5, 5
    if position == "bottom-right":
        return rows - height - 5, cols - width - 5
    return 0, 0


def _preset(name: str) -> Grid:
    if name not in PRESETS:
        known = "、".join(PRESETS)
        raise ConfigError(f"知らない種のパターン: {name}（使える名前: {known}）")
    return PRESETS[name]


def build_initial_state(rows: int, cols: int, config: LifeConfig, rng: np.random.Generator) -> Grid:
    """設定と乱数から、最初の盤面を作る。

    乱数を引く順（ランダムな密度、ばら撒きの向き、反転、位置）は、同じ seed で同じ盤面になるよう、
    変えない。

    Raises:
        ConfigError: 設定の `patterns` か `scatter` に、知らない種のパターンの名前がある。
    """
    grid: Grid = np.zeros((rows, cols), dtype=np.uint8)

    density = config.get("random_density", 0.0)
    if density > 0:
        grid = (rng.random((rows, cols)) < density).astype(np.uint8)

    for placement in config.get("patterns", []):
        pattern = _preset(placement["name"]).copy()
        rotate = placement.get("rotate", 0)
        if rotate:
            pattern = np.rot90(pattern, -rotate)
        if placement.get("mirror"):
            pattern = np.flip(pattern, 0)
        row, col = placement_origin(pattern, placement.get("position", "center"), rows, cols)
        stamp_pattern(grid, pattern, row, col)

    # scatter: 種のパターンを、ランダムな位置と向きで盤面の全体にばら撒く。
    # count は個数、per_10k は1万セルあたりの個数（解像度が変わっても密度が同じになる）
    for scatter in config.get("scatter", []):
        base = _preset(scatter["name"])
        if "per_10k" in scatter:
            count = max(1, round(scatter["per_10k"] * rows * cols / 10000))
        else:
            count = scatter.get("count", 1)
        for _ in range(count):
            pattern = np.rot90(base, -int(rng.integers(4)))
            if rng.random() < 0.5:
                pattern = np.flip(pattern, 0)
            row = int(rng.integers(rows))
            col = int(rng.integers(cols))
            stamp_pattern(grid, pattern, row, col)

    return grid
