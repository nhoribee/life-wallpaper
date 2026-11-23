"""モチーフの認識。盤面のセルの群を、既知のモチーフの辞書と照らして色分けする。

各世代のセルの群を、既知のモチーフの辞書（すべての位相と、回転と反転の8通り）と照らす。
一致した群はそのモチーフの色、辞書に無いが単独で安定する群は stable の色、
そのほかの塊は chaos の色で塗る。
"""

from functools import cache

import numpy as np
import numpy.typing as npt

from lifewallpaper.life import step
from lifewallpaper.models import Grid, Heat

# 群の署名（高さ、幅、切り出したビットマップ）
Signature = tuple[int, int, bytes]

MOTIF_DEFS: dict[str, list[str]] = {
    "block": ["OO", "OO"],
    "beehive": [".OO.", "O..O", ".OO."],
    "loaf": [".OO.", "O..O", ".O.O", "..O."],
    "boat": ["OO.", "O.O", ".O."],
    "tub": [".O.", "O.O", ".O."],
    "pond": [".OO.", "O..O", "O..O", ".OO."],
    "ship": ["OO.", "O.O", ".OO"],
    "long-boat": ["OO..", "O.O.", ".O.O", "..O."],
    "barge": [".O..", "O.O.", ".O.O", "..O."],
    "snake": ["OO.O", "O.OO"],
    "eater": ["OO..", "O...", ".OOO", "...O"],
    "ship-tie": ["....OO", "...O.O", "...OO.", ".OO...", "O.O...", "OO...."],
    "long-ship": ["..OO", ".O.O", "O.O.", "OO.."],
    "mango": ["..OO.", ".O..O", "O..O.", ".OO.."],
    "blinker": ["OOO"],
    "toad": [".OOO", "OOO."],
    "beacon": ["OO..", "OO..", "..OO", "..OO"],
    "clock": ["..O.", "O.O.", ".O.O", ".O.."],
    "pulsar": [
        "..OOO...OOO..",
        ".............",
        "O....O.O....O",
        "O....O.O....O",
        "O....O.O....O",
        "..OOO...OOO..",
        ".............",
        "..OOO...OOO..",
        "O....O.O....O",
        "O....O.O....O",
        "O....O.O....O",
        ".............",
        "..OOO...OOO..",
    ],
    "pentadecathlon": ["..O....O..", "OO.OOOO.OO", "..O....O.."],
    "glider": [".O.", "..O", "OOO"],
    "lwss": ["O..O.", "....O", "O...O", ".OOOO"],
    "mwss": ["..O...", "O...O.", ".....O", "O....O", ".OOOOO"],
    "hwss": ["..OO...", "O....O.", "......O", "O.....O", ".OOOOOO"],
}

CHAOS = "chaos"
STABLE = "stable"  # 辞書に無いが、単独で置くと形が変わらない、または周期的に戻る塊
# モチーフの番号: 0 = 死、1 = chaos、2〜 = 既知のモチーフ、末尾 = stable
MOTIF_ORDER = [CHAOS, *MOTIF_DEFS, STABLE]
MOTIF_ID = {name: index + 1 for index, name in enumerate(MOTIF_ORDER)}

MOTIF_COLORS: dict[str, list[int]] = {
    "chaos": [100, 105, 120],
    "block": [96, 140, 235],
    "beehive": [235, 190, 90],
    "loaf": [210, 150, 100],
    "boat": [90, 200, 185],
    "tub": [140, 185, 240],
    "pond": [95, 220, 220],
    "ship": [175, 145, 235],
    "long-boat": [110, 175, 215],
    "barge": [150, 205, 255],
    "snake": [195, 180, 120],
    "eater": [130, 150, 170],
    "ship-tie": [255, 140, 180],
    "long-ship": [150, 130, 255],
    "mango": [170, 230, 90],
    "blinker": [255, 150, 60],
    "toad": [255, 115, 95],
    "beacon": [230, 95, 200],
    "clock": [200, 120, 160],
    "pulsar": [255, 220, 95],
    "pentadecathlon": [185, 115, 255],
    "glider": [95, 235, 130],
    "lwss": [70, 200, 255],
    "mwss": [50, 170, 250],
    "hwss": [40, 140, 245],
    "stable": [235, 235, 245],
}

# 距離2（Chebyshev）でつなぐ: パルサーのように隙間のある振動子も、1つの群にまとめる
_NEIGHBORS_WITHIN_2 = [(dr, dc) for dr in range(-2, 3) for dc in range(-2, 3) if (dr, dc) != (0, 0)]
_MAX_MOTIF_EXTENT = 20  # これより大きい塊は、既知のモチーフではない
_SIGNATURE_BOARD = 48  # 辞書を作るときに、モチーフを単独で動かす盤面の1辺
_SIGNATURE_GENERATIONS = 33  # いちばん長い周期（pentadecathlon の15）の2倍と余裕
_STABLE_MAX_PERIOD = 30
_STABLE_PAD = _STABLE_MAX_PERIOD + 2  # 周期のあいだに、盤面の端を回り込まない余白

_stable_cache: dict[Signature, bool] = {}


def _group_cells(grid: Grid) -> list[list[int]]:
    """生きているセルを距離2でつないで群にし、群ごとのセルの番号（平らにした位置）を返す。"""
    rows, cols = grid.shape
    flat = grid.ravel().tolist()
    visited = bytearray(rows * cols)
    groups: list[list[int]] = []
    for start in np.flatnonzero(grid.ravel()).tolist():
        if visited[start]:
            continue
        stack = [start]
        visited[start] = 1
        group: list[int] = []
        while stack:
            cell = stack.pop()
            group.append(cell)
            row, col = divmod(cell, cols)
            for dr, dc in _NEIGHBORS_WITHIN_2:
                other = ((row + dr) % rows) * cols + ((col + dc) % cols)
                if flat[other] and not visited[other]:
                    visited[other] = 1
                    stack.append(other)
        groups.append(group)
    return groups


def _signature(group: list[int], rows: int, cols: int) -> Signature | None:
    """群を囲む四角で切り出したビットマップを返す。盤面の端をまたぐ群は、座標を折り返す。

    大きすぎる群（1辺が `_MAX_MOTIF_EXTENT` を超える）は None を返す。
    """
    rs = [cell // cols for cell in group]
    cs = [cell % cols for cell in group]
    if max(rs) - min(rs) > rows // 2:
        rs = [r + rows if r < rows // 2 else r for r in rs]
    if max(cs) - min(cs) > cols // 2:
        cs = [c + cols if c < cols // 2 else c for c in cs]
    top, left = min(rs), min(cs)
    height = max(rs) - top + 1
    width = max(cs) - left + 1
    if height > _MAX_MOTIF_EXTENT or width > _MAX_MOTIF_EXTENT:
        return None
    bits = bytearray(height * width)
    for r, c in zip(rs, cs, strict=True):
        bits[(r - top) * width + (c - left)] = 1
    return (height, width, bytes(bits))


def _signature_variants(signature: Signature) -> list[Signature]:
    """署名を、回転と反転の8通りにして返す。"""
    height, width, bits = signature
    bitmap = np.frombuffer(bits, dtype=np.uint8).reshape(height, width)
    variants: list[Signature] = []
    for quarter_turns in range(4):
        rotated = np.rot90(bitmap, quarter_turns)
        for variant in (rotated, np.flip(rotated, 0)):
            variants.append((variant.shape[0], variant.shape[1], variant.tobytes()))
    return variants


@cache
def motif_signatures() -> dict[Signature, int]:
    """既知のモチーフを単独で動かし、すべての位相と8通りの向きの署名の辞書を作る。"""
    signatures: dict[Signature, int] = {}
    for name, art in MOTIF_DEFS.items():
        board: Grid = np.zeros((_SIGNATURE_BOARD, _SIGNATURE_BOARD), dtype=np.uint8)
        for r, line in enumerate(art):
            for c, char in enumerate(line):
                if char == "O":
                    board[16 + r, 16 + c] = 1
        for _ in range(_SIGNATURE_GENERATIONS):
            for group in _group_cells(board):
                signature = _signature(group, _SIGNATURE_BOARD, _SIGNATURE_BOARD)
                if signature is None:
                    continue
                for variant in _signature_variants(signature):
                    signatures.setdefault(variant, MOTIF_ID[name])
            board = step(board)
    return signatures


def _split_touching(group: list[int], rows: int, cols: int) -> list[list[int]]:
    """距離2でつないだ群を、隣り合う（8近傍の）セルどうしのパーツに分ける。"""
    cells = set(group)
    seen: set[int] = set()
    parts: list[list[int]] = []
    for start in group:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        part: list[int] = []
        while stack:
            cell = stack.pop()
            part.append(cell)
            row, col = divmod(cell, cols)
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    other = ((row + dr) % rows) * cols + ((col + dc) % cols)
                    if other in cells and other not in seen:
                        seen.add(other)
                        stack.append(other)
        parts.append(part)
    return parts


def _is_stable(signature: Signature) -> bool:
    """群を単独で置き、30世代のうちに元の形と位置へ戻るか（静物か振動子か）を返す。"""
    key = min(_signature_variants(signature))
    if key not in _stable_cache:
        height, width, bits = signature
        pad = _STABLE_PAD
        start: Grid = np.zeros((height + 2 * pad, width + 2 * pad), dtype=np.uint8)
        start[pad : pad + height, pad : pad + width] = np.frombuffer(bits, dtype=np.uint8).reshape(
            height, width
        )
        current = start
        returned = False
        for _ in range(_STABLE_MAX_PERIOD):
            current = step(current)
            if not current.any():
                break
            if np.array_equal(current, start):
                returned = True
                break
        _stable_cache[key] = returned
    return _stable_cache[key]


def _known_motifs(
    parts: list[list[int]], signatures: dict[Signature, int], rows: int, cols: int
) -> list[int] | None:
    """パーツごとのモチーフの番号を返す。辞書に無いパーツが1つでもあれば None を返す。"""
    motifs: list[int] = []
    for part in parts:
        signature = _signature(part, rows, cols)
        motif = signatures.get(signature) if signature else None
        if motif is None:
            return None
        motifs.append(motif)
    return motifs


def classify(grid: Grid, auto_stable: bool = True) -> Grid:
    """盤面と同じ形の、モチーフの番号の盤面を返す（0 = 死、1 = chaos、2〜 = 既知、末尾 = stable）。

    判定の順は次のとおり。
    1. 群の全体が辞書と一致する
    2. 隣り合うセルどうしのパーツに分けて、すべてのパーツが辞書と一致する
       （近くに並んだ既知のモチーフの合体。信号機など）
    3. 単独で安定する群は stable
    4. そのほかは chaos
    """
    signatures = motif_signatures()
    rows, cols = grid.shape
    motif_map: Grid = np.zeros(rows * cols, dtype=np.uint8)
    chaos = MOTIF_ID[CHAOS]
    stable = MOTIF_ID[STABLE]
    for group in _group_cells(grid):
        signature = _signature(group, rows, cols)
        motif = signatures.get(signature) if signature else None
        if motif:
            motif_map[group] = motif
            continue
        parts = _split_touching(group, rows, cols)
        part_motifs = _known_motifs(parts, signatures, rows, cols) if len(parts) >= 2 else None
        if part_motifs is not None:
            for part, part_motif in zip(parts, part_motifs, strict=True):
                motif_map[part] = part_motif
            continue
        is_stable = auto_stable and signature is not None and _is_stable(signature)
        motif_map[group] = stable if is_stable else chaos
    return motif_map.reshape(rows, cols)


def motif_lut(
    overrides: dict[str, list[int]], bg_color: tuple[int, ...]
) -> npt.NDArray[np.float64]:
    """モチーフの番号から RGB を引く表を返す。0番は背景の色。

    Args:
        overrides: 設定の `motif_colors`。モチーフの名前ごとに、色を上書きする。
        bg_color: 背景の色。
    """
    lut = [list(bg_color)]
    for name in MOTIF_ORDER:
        lut.append(list(overrides.get(name, MOTIF_COLORS[name])))
    return np.array(lut, dtype=np.float64)


def classify_final(grid: Grid, steps: int, auto_stable: bool = True) -> Grid:
    """盤面を `steps` 世代進め、最後の盤面のモチーフの番号の盤面を返す。"""
    for _ in range(steps):
        grid = step(grid)
    return classify(grid, auto_stable)


def accumulate_heat_by_motif(
    grid: Grid, steps: int, mode: str, auto_stable: bool = True
) -> npt.NDArray[np.uint32]:
    """`steps` 世代のあいだの、セルごとの回数を、モチーフの番号ごとに分けて返す。

    Args:
        grid: 最初の盤面。
        steps: 進める世代の数。
        mode: `activity` なら生まれた回数、そのほかなら生きていた回数。
        auto_stable: 辞書に無い安定した塊を、stable として見分けるか。

    Returns:
        形が（モチーフの番号の数、行、列）の配列。
    """
    stack: Heat = np.zeros((len(MOTIF_ORDER) + 1, *grid.shape), dtype=np.uint32)
    for _ in range(steps):
        new = step(grid)
        motif_map = classify(new, auto_stable)
        event = (new == 1) & (grid == 0) if mode == "activity" else new == 1
        for motif in np.unique(motif_map):
            if motif == 0:
                continue
            stack[motif] += event & (motif_map == motif)
        grid = new
    return stack
