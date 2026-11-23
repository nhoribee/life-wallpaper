"""データの形。設定の JSON（`config/*.json`）と、画像の大きさ。"""

from dataclasses import dataclass
from typing import TypedDict

import numpy as np
import numpy.typing as npt

# 盤面（0 = 死、1 = 生）と、モチーフの番号の盤面
Grid = npt.NDArray[np.uint8]
# セルごとの回数（生まれた回数、生きていた回数）
Heat = npt.NDArray[np.uint32]
# 画像（高さ、幅、RGB）
Rgb = npt.NDArray[np.uint8]


@dataclass(frozen=True)
class Resolution:
    """作る画像の大きさ。

    Attributes:
        label: ファイル名に入れる呼び名（`macbook`、`3024x1964` など）。
        width: 幅（ピクセル）。
        height: 高さ（ピクセル）。
    """

    label: str
    width: int
    height: int


@dataclass(frozen=True)
class Display:
    """接続中のディスプレイ1つ。

    Attributes:
        display_id: 画面の番号（NSScreen の `NSScreenNumber`）。壁紙を設定する画面を、この番号で選ぶ。
        name: 画面の名前（「Built-in Retina Display」など）。
        width: 幅（物理ピクセル。NSScreen の frame の幅に backingScaleFactor を掛けた値）。
        height: 高さ（物理ピクセル）。
        scale: backingScaleFactor（Retina の画面は 2）。
        current_image: いま表示している壁紙のパス。壁紙が無い、または取れなければ None。
        current_image_known: いまの壁紙を調べられたか。False なら、表示中の画像が分からない。
    """

    display_id: int
    name: str
    width: int
    height: int
    scale: float
    current_image: str | None
    current_image_known: bool = True


class Placement(TypedDict, total=False):
    """決まった位置に置く種のパターン1つ。"""

    name: str
    position: str | list[int]
    rotate: int
    mirror: bool


class Scatter(TypedDict, total=False):
    """盤面の全体にばら撒く種のパターン1種類。`per_10k` は1万セルあたりの個数。"""

    name: str
    per_10k: float
    count: int


class GifConfig(TypedDict, total=False):
    """GIF の設定。"""

    generations: int
    stride: int
    duration_ms: int
    max_width: int
    trail: float
    hold_last_ms: int


class VideoConfig(TypedDict, total=False):
    """動画の設定。ライフゲームは `generations` と `stride`、1次元は `duration_s` と `columns_per_frame` を使う。"""

    generations: int
    stride: int
    fps: int
    max_width: int
    trail: float
    duration_s: int
    columns_per_frame: int


class LifeConfig(TypedDict, total=False):
    """ライフゲームの設定（`config/NN_*.json`）。"""

    name: str
    cell_size: int
    mode: str
    steps: int
    random_density: float
    color_by_motif: bool
    motif_auto_stable: bool
    motif_colors: dict[str, list[int]]
    palette: str
    bg_color: list[int]
    fg_color: list[int]
    use_log: bool
    clip_percentile: float
    patterns: list[Placement]
    scatter: list[Scatter]
    gif: GifConfig
    video: VideoConfig


class EcaConfig(TypedDict, total=False):
    """1次元のセルオートマトンの設定（`config/eca*.json`）。`rule` は Wolfram のルールの番号。"""

    name: str
    rule: int
    cell_size: int
    init_density: float
    init_seeds: int
    burn_in: int
    bg_color: list[int]
    fg_color: list[int]
    video: VideoConfig
