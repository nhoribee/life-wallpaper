"""接続中のディスプレイの壁紙。画面ごとに、その解像度で1枚作り、その画面に設定する。

macOS は、同じパスの画像を差し替えても表示を更新しない。そのため、ファイル名は毎回変え、
古い画像は画面ごとに新しいものだけを残して消す。
"""

import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from lifewallpaper import osascript
from lifewallpaper.config import sized_resolution
from lifewallpaper.models import Display, LifeConfig
from lifewallpaper.render import save_image
from lifewallpaper.wallpaper import render_still

logger = logging.getLogger(__name__)

# メタデータの JSON が、このモジュールの作った壁紙のものだと見分ける値
KIND = "life-wallpaper-desktop"
DEFAULT_KEEP = 5
_SEED_RANGE = 2**32


class ScreenRecord(TypedDict):
    """メタデータに残す、画面の情報。`key` は、古い画像を画面ごとに数えるときの名前。"""

    key: str
    id: int
    name: str
    width: int
    height: int
    scale: float


@dataclass
class ScreenResult:
    """画面1つぶんの結果。

    Attributes:
        display: 画像を作ったときの画面。
        seed: 使った seed。
        image_path: 作った画像のパス。
        metadata_path: メタデータの JSON のパス。
        seconds: 画像を作って保存するまでにかかった秒数。
        applied: 壁紙として設定したか。
        error: 設定できなかった理由。設定した、または dry-run なら None。
    """

    display: Display
    seed: int
    image_path: Path
    metadata_path: Path
    seconds: float
    applied: bool = False
    error: str | None = None


def screen_key(display: Display) -> str:
    """画面の名前と解像度から、古い画像を画面ごとに数えるときの名前を作る。

    画面の番号は、つなぎ直すと変わることがあるので使わない。
    """
    slug = re.sub(r"[^a-z0-9]+", "-", display.name.lower()).strip("-") or "display"
    return f"{slug}_{display.width}x{display.height}"


def matched_cell_size(base_cell: int, main_scale: float, scale: float) -> int:
    """メインの画面と同じ見た目の大きさになる、その画面のセルの大きさ（物理ピクセル）を返す。

    セルの大きさを、メインの画面でのポイント（`base_cell / main_scale`）にそろえる。
    1セルが物理ピクセルをまたいで滲まないよう、整数に丸め、1より小さくしない。
    例: メインが scale 2 で 3px（1.5pt）なら、scale 1 の画面は 2px、scale 2 の画面は 3px。
    """
    points = base_cell / main_scale
    return max(1, int(points * scale + 0.5))


def _write_metadata(result: ScreenResult, metadata: dict[str, object]) -> None:
    result.metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _generate_for_display(
    config: LifeConfig,
    config_file: str,
    display: Display,
    seed: int,
    output_dir: Path,
    now: datetime,
) -> tuple[ScreenResult, dict[str, object]]:
    """画面1つぶんの画像を作って保存し、結果とメタデータを返す。"""
    resolution = sized_resolution(display.width, display.height)
    cell_size = config.get("cell_size", 8)
    started = time.perf_counter()
    still = render_still(config, resolution, seed)
    key = screen_key(display)
    stem = (
        f"{config.get('name', 'life')}_{key}-d{display.display_id}"
        f"_s{seed}_{now.strftime('%Y%m%d-%H%M%S')}"
    )
    image_path = output_dir / f"{stem}.png"
    save_image(still.rgb, image_path)
    seconds = time.perf_counter() - started
    result = ScreenResult(display, seed, image_path, output_dir / f"{stem}.json", seconds)
    screen: ScreenRecord = {
        "key": key,
        "id": display.display_id,
        "name": display.name,
        "width": display.width,
        "height": display.height,
        "scale": display.scale,
    }
    metadata: dict[str, object] = {
        "kind": KIND,
        "created_at": now.isoformat(timespec="seconds"),
        "image": image_path.name,
        "screen": screen,
        "seed": seed,
        "resolution": resolution.label,
        "grid_rows": still.rows,
        "grid_cols": still.cols,
        "seconds": round(seconds, 2),
        "cell_size": cell_size,
        "applied": False,
        "config_file": config_file,
        "config": config,
    }
    _write_metadata(result, metadata)
    return result, metadata


def _apply_one(result: ScreenResult, current: dict[int, Display]) -> None:
    """作った画像を、その画面に設定する。画面が外れた、解像度が変わったときは、設定せずに理由を残す。"""
    display = result.display
    now = current.get(display.display_id)
    if now is None:
        result.error = "画像を作ったあとに、画面が外れた"
        return
    if (now.width, now.height) != (display.width, display.height):
        result.error = (
            f"画像を作ったあとに、解像度が変わった"
            f"（{display.width}x{display.height} から {now.width}x{now.height}）"
        )
        return
    try:
        osascript.set_desktop_image(display.display_id, result.image_path)
    except osascript.OsascriptError as error:
        result.error = str(error)
        return
    result.applied = True


def prune_old_images(output_dir: Path, keep: int, protected: set[Path]) -> list[Path]:
    """古い画像を、画面ごとに新しい `keep` 枚だけ残して消す。消した画像のパスを返す。

    消すのは、`output_dir` の中の、このモジュールが作った画像とそのメタデータだけである
    （メタデータの `kind` で見分ける）。`protected` にある画像（いまどれかの画面に表示している画像、
    今回作った画像）は、古くても消さない。消すと、その画面の壁紙が表示できなくなるためである。
    """
    by_screen: dict[str, list[tuple[str, Path, Path]]] = {}
    for metadata_path in output_dir.glob("*.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(metadata, dict) or metadata.get("kind") != KIND:
            continue
        screen = metadata.get("screen")
        image = metadata.get("image")
        created_at = metadata.get("created_at")
        if not isinstance(screen, dict) or not isinstance(image, str):
            continue
        # メタデータに書かれた名前で、フォルダの外や、ほかのファイルを指させない。
        # 画像は、メタデータと同じ名前の .png だけを認める
        image_path = output_dir / Path(image).name
        if image_path.name != f"{metadata_path.stem}.png":
            continue
        entry = (str(created_at), image_path, metadata_path)
        by_screen.setdefault(str(screen.get("key")), []).append(entry)

    protected_resolved = {path.resolve() for path in protected}
    removed: list[Path] = []
    for entries in by_screen.values():
        entries.sort(key=lambda entry: (entry[0], entry[1].name), reverse=True)
        for _, image_path, metadata_path in entries[keep:]:
            if image_path.resolve() in protected_resolved:
                continue
            image_path.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
            removed.append(image_path)
    return removed


def apply_wallpapers(
    config: LifeConfig,
    config_file: str,
    output_dir: Path,
    seed: int | None = None,
    keep: int = DEFAULT_KEEP,
    dry_run: bool = False,
    now: datetime | None = None,
) -> list[ScreenResult]:
    """接続中の画面ごとに、その解像度で壁紙を1枚作り、その画面に設定する。

    Args:
        config: ライフゲームの設定。
        config_file: 設定のファイル名（メタデータに残す）。
        output_dir: 画像とメタデータの保存先。
        seed: 乱数の seed。None なら、画面ごとにランダムに決める。渡すと、すべての画面で同じ値を使う。
        keep: 画面ごとに残す画像の枚数（1以上）。
        dry_run: True なら、画像を作るところまでで止め、壁紙は設定しない。
        now: ファイル名とメタデータに入れる時刻。None なら、いまの時刻。

    Returns:
        画面ごとの結果（NSScreen の並びの順）。設定できなかった画面は、`error` に理由が入る。

    Raises:
        lifewallpaper.osascript.OsascriptError: 画面の一覧を取れなかった。
        ValueError: `keep` が1より小さい。
    """
    if keep < 1:
        raise ValueError(f"残す枚数は1以上で渡す: {keep}")
    stamp = now if now is not None else datetime.now().astimezone()
    displays = osascript.list_displays()

    # NSScreen の並びの先頭がメインの画面（メニューバーのある画面）。ほかの画面のセルを、
    # メインの画面と同じ見た目の大きさにそろえる（画面ごとに scale が違うと、同じ px でも大きさが変わる）
    base_cell = config.get("cell_size", 8)
    main_scale = displays[0].scale if displays else 1.0
    generated: list[tuple[ScreenResult, dict[str, object]]] = []
    for display in displays:
        display_seed = seed if seed is not None else secrets.randbelow(_SEED_RANGE)
        cell = matched_cell_size(base_cell, main_scale, display.scale)
        display_config: LifeConfig = {**config, "cell_size": cell}
        generated.append(
            _generate_for_display(
                display_config, config_file, display, display_seed, output_dir, stamp
            )
        )
        logger.info("%s（%dx%d）の画像を作った", display.name, display.width, display.height)
    results = [result for result, _ in generated]

    if not dry_run:
        # 画像を作っているあいだに、画面をつなぎ替えたかもしれないので、設定の直前に引き直す
        current = {display.display_id: display for display in osascript.list_displays()}
        for result, metadata in generated:
            _apply_one(result, current)
            if result.applied:
                applied_at = datetime.now().astimezone().isoformat(timespec="seconds")
                _write_metadata(result, {**metadata, "applied": True, "applied_at": applied_at})
        displays = osascript.list_displays()

    # dry-run では消さない（「設定しないで」と頼まれたときに、ほかの Space の画像まで消さないため）。
    # 表示中の画像を調べられなかった画面があるときも消さない（表示中の画像を守れないため）
    if dry_run:
        return results
    if not all(display.current_image_known for display in displays):
        logger.warning("いまの壁紙を調べられない画面があるので、古い画像を消さなかった")
        return results
    protected = {result.image_path for result in results}
    protected |= {Path(display.current_image) for display in displays if display.current_image}
    for removed in prune_old_images(output_dir, keep, protected):
        logger.info("古い画像を消した: %s", removed.name)
    return results
