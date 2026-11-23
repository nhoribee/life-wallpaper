"""設定とパス。設定の JSON の読み込み、名前つきの解像度、出力の保存先。"""

import json
import os
import re
from pathlib import Path
from typing import cast

from lifewallpaper.models import EcaConfig, LifeConfig, Resolution

PACKAGE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = PACKAGE_DIR.parent / "config"
ATLAS_TEMPLATE = PACKAGE_DIR / "atlas_template.html"

# 画像、GIF、動画の出力のフォルダ、設定の一覧のページのフォルダ、apply が画面ごとに作る壁紙のフォルダ
# （どれもデータのフォルダの下。環境変数 LIFE_WALLPAPER_HOME、無ければ ~/Pictures/life-wallpaper）
DATA_ENV = "LIFE_WALLPAPER_HOME"
DEFAULT_DATA_ROOT = Path("~/Pictures/life-wallpaper")
OUTPUT_SUBDIR = "output"
ATLAS_SUBDIR = "atlas"
DESKTOP_SUBDIR = "desktop"
ATLAS_NAME = "pattern-atlas.html"

# apply が既定で使う設定。いまの内蔵の画面の壁紙と同じ模様（3px のセル、1500 世代、モチーフの色分け）
DEFAULT_APPLY_CONFIG = "10_motif_field_hires_t1500"

# 名前で選べる画像の大きさ
NAMED_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "macbook": (3024, 1964),
    "ultrawide": (3840, 1600),
    "4k": (3840, 2160),
}


# 幅x高さ の形（x は大文字でもよい）と、1辺の上限。上限は、桁の打ち間違いで巨大な画像を作らないために置く
_SIZE_FORM = re.compile(r"(\d{1,6})[xX](\d{1,6})")
MAX_SIDE = 16384


class ConfigError(ValueError):
    """設定の JSON か、渡された引数の値が読めない。"""


def parse_resolution(value: str) -> Resolution:
    """`--resolution` の値を、画像の大きさにする。

    名前（`macbook`、`ultrawide`、`4k`）か、`幅x高さ`（`1600x1000` など）を受け付ける。
    ファイル名に入れる呼び名は、名前で渡されたらその名前、`幅x高さ` で渡されたら `幅x高さ` にする。

    Raises:
        ConfigError: 知らない名前、`幅x高さ` の形でない、幅か高さが 1〜MAX_SIDE の外。
    """
    if value in NAMED_RESOLUTIONS:
        width, height = NAMED_RESOLUTIONS[value]
        return Resolution(value, width, height)
    matched = _SIZE_FORM.fullmatch(value)
    if not matched:
        known = "、".join(NAMED_RESOLUTIONS)
        raise ConfigError(f"解像度は名前（{known}）か、幅x高さ（1600x1000 など）で書く: {value}")
    return sized_resolution(int(matched.group(1)), int(matched.group(2)))


def sized_resolution(width: int, height: int) -> Resolution:
    """幅と高さ（ピクセル）から、呼び名が `幅x高さ` の画像の大きさを作る。

    Raises:
        ConfigError: 幅か高さが 1〜MAX_SIDE の外。
    """
    if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE):
        raise ConfigError(f"解像度の幅と高さは 1〜{MAX_SIDE} で書く: {width}x{height}")
    return Resolution(f"{width}x{height}", width, height)


def data_dir(subdir: str) -> Path:
    """出力の保存先（`<データのフォルダ>/<subdir>/`）を作って返す。"""
    target = data_root() / subdir
    target.mkdir(parents=True, exist_ok=True)
    return target


def data_root() -> Path:
    """データのフォルダ。環境変数 LIFE_WALLPAPER_HOME があればその値、無ければ ~/Pictures/life-wallpaper。"""
    given = os.environ.get(DATA_ENV)
    return (Path(given) if given else DEFAULT_DATA_ROOT).expanduser()


def resolve_config_path(value: str) -> Path:
    """`--config` の値を、設定のファイルのパスにする。

    `/` を含まない値は、まずこのツールの `config/` の中の同じ名前（`.json` は省いてよい）を探す。
    呼ぶ側の作業フォルダに同じ名前のファイルがあっても、同梱の設定を優先するためである。
    見つからなければ、そのままのパスとして読む。

    Raises:
        ConfigError: どちらにもファイルが無い。
    """
    if "/" not in value:
        for candidate in (CONFIG_DIR / value, CONFIG_DIR / f"{value}.json"):
            if candidate.is_file():
                return candidate
    given = Path(value).expanduser()
    if given.is_file():
        return given
    raise ConfigError(f"設定のファイルが無い: {value}（{CONFIG_DIR} の中の名前でも指定できる）")


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ConfigError(f"設定が JSON として読めない: {path}（{error}）") from error
    if not isinstance(loaded, dict):
        raise ConfigError(f"設定はオブジェクト（{{...}}）で書く: {path}")
    return loaded


# 設定の name は出力のファイル名の先頭になる。フォルダの外を指させないよう、使える文字を絞る
_NAME_FORM = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")


def _check_name(raw: dict[str, object], path: Path) -> None:
    name = raw.get("name")
    if name is not None and (not isinstance(name, str) or not _NAME_FORM.fullmatch(name)):
        raise ConfigError(f"name は英数字、`.`、`_`、`-` だけで、英数字から始めて書く: {path}")


def _check_cell_size(raw: dict[str, object], path: Path) -> None:
    cell_size = raw.get("cell_size", 8)
    if not isinstance(cell_size, int) or isinstance(cell_size, bool) or cell_size < 1:
        raise ConfigError(f"cell_size は1以上の整数で書く: {path}")


def load_life_config(path: Path) -> LifeConfig:
    """ライフゲームの設定を読む。

    Raises:
        ConfigError: JSON として読めない、オブジェクトでない、`cell_size` が1以上の整数でない。
    """
    raw = _read_json_object(path)
    _check_name(raw, path)
    _check_cell_size(raw, path)
    return cast(LifeConfig, raw)


def load_eca_config(path: Path) -> EcaConfig:
    """1次元のセルオートマトンの設定を読む。

    Raises:
        ConfigError: JSON として読めない、オブジェクトでない、`cell_size` が1以上の整数でない、
            `rule` が 0〜255 の整数でない。
    """
    raw = _read_json_object(path)
    _check_name(raw, path)
    _check_cell_size(raw, path)
    rule = raw.get("rule")
    if not isinstance(rule, int) or isinstance(rule, bool) or not 0 <= rule <= 255:
        raise ConfigError(f"rule は 0〜255 の整数で書く: {path}")
    return cast(EcaConfig, raw)
