"""接続中の画面ごとに壁紙を作って設定する処理（lifewallpaper.desktop）のテスト。

画面の一覧と壁紙の設定は、`fake_desktop` の記録に置き換える。本物の壁紙の設定には届かない。
"""

import dataclasses
import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import EXPECTED, FIXTURES, FakeDesktop, image_hash
from PIL import Image

from lifewallpaper import config, desktop, osascript
from lifewallpaper.models import Display, LifeConfig

CONFIG_FILE = "motif_snapshot.json"
START = datetime(2026, 11, 16, 9, 0, 0, tzinfo=timezone(timedelta(hours=9)))


@pytest.fixture
def life_config() -> LifeConfig:
    return config.load_life_config(FIXTURES / CONFIG_FILE)


def image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def test_dry_run_generates_one_image_per_display_at_its_resolution(
    fake_desktop: FakeDesktop, life_config: LifeConfig, tmp_path: Path
) -> None:
    results = desktop.apply_wallpapers(life_config, CONFIG_FILE, tmp_path, dry_run=True, now=START)

    assert [image_size(result.image_path) for result in results] == [
        (320, 200),
        (384, 160),
        (160, 100),
    ]
    assert [result.display.display_id for result in results] == [1, 2, 3]
    assert not any(result.applied or result.error for result in results)
    assert fake_desktop.applied == []


def test_apply_sets_each_image_on_its_own_display(
    fake_desktop: FakeDesktop, life_config: LifeConfig, tmp_path: Path
) -> None:
    results = desktop.apply_wallpapers(life_config, CONFIG_FILE, tmp_path, now=START)

    assert fake_desktop.applied == [
        (result.display.display_id, result.image_path) for result in results
    ]
    assert all(result.applied and result.error is None for result in results)


def test_fixed_seed_reproduces_generate_output(
    fake_desktop: FakeDesktop, life_config: LifeConfig, tmp_path: Path
) -> None:
    """同じ設定、解像度、seed なら、generate と同じ画像になる。"""
    results = desktop.apply_wallpapers(
        life_config, CONFIG_FILE, tmp_path, seed=42, dry_run=True, now=START
    )

    assert [result.seed for result in results] == [42, 42, 42]
    assert image_hash(results[0].image_path) == EXPECTED["320x200"]["generate/motif_snapshot/s42"]


def test_seed_is_drawn_per_display_when_not_given(
    fake_desktop: FakeDesktop,
    life_config: LifeConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drawn = iter([11, 22, 33])
    monkeypatch.setattr(secrets, "randbelow", lambda _: next(drawn))

    results = desktop.apply_wallpapers(life_config, CONFIG_FILE, tmp_path, dry_run=True, now=START)

    assert [result.seed for result in results] == [11, 22, 33]


def test_metadata_records_seed_and_screen(
    fake_desktop: FakeDesktop, life_config: LifeConfig, tmp_path: Path
) -> None:
    results = desktop.apply_wallpapers(
        life_config, CONFIG_FILE, tmp_path, seed=7, dry_run=True, now=START
    )

    metadata = json.loads(results[0].metadata_path.read_text())
    seconds = metadata.pop("seconds")
    assert seconds >= 0
    assert metadata == {
        "kind": "life-wallpaper-desktop",
        "created_at": "2026-11-16T09:00:00+09:00",
        "image": results[0].image_path.name,
        "screen": {
            "key": "built-in-retina-display_320x200",
            "id": 1,
            "name": "Built-in Retina Display",
            "width": 320,
            "height": 200,
            "scale": 2.0,
        },
        "seed": 7,
        "resolution": "320x200",
        "grid_rows": 66,
        "grid_cols": 106,
        "cell_size": 3,
        "applied": False,
        "config_file": CONFIG_FILE,
        "config": json.loads((FIXTURES / CONFIG_FILE).read_text()),
    }


def test_metadata_is_marked_applied_after_apply(
    fake_desktop: FakeDesktop, life_config: LifeConfig, tmp_path: Path
) -> None:
    results = desktop.apply_wallpapers(life_config, CONFIG_FILE, tmp_path, now=START)

    metadata = json.loads(results[0].metadata_path.read_text())
    assert metadata["applied"] is True
    assert "applied_at" in metadata


def test_file_name_changes_on_every_run(
    fake_desktop: FakeDesktop, life_config: LifeConfig, tmp_path: Path
) -> None:
    """macOS は同じパスの画像を差し替えても表示を更新しないので、同じ seed でも名前を変える。"""
    first = desktop.apply_wallpapers(life_config, CONFIG_FILE, tmp_path, seed=1, now=START)
    second = desktop.apply_wallpapers(
        life_config, CONFIG_FILE, tmp_path, seed=1, now=START + timedelta(seconds=1)
    )

    assert first[0].image_path.name == (
        "motif_snapshot_built-in-retina-display_320x200-d1_s1_20261116-090000.png"
    )
    assert second[0].image_path.name == (
        "motif_snapshot_built-in-retina-display_320x200-d1_s1_20261116-090001.png"
    )


def test_old_images_are_pruned_per_display(
    fake_desktop: FakeDesktop, life_config: LifeConfig, tmp_path: Path
) -> None:
    runs = [
        desktop.apply_wallpapers(
            life_config, CONFIG_FILE, tmp_path, keep=2, now=START + timedelta(minutes=minute)
        )
        for minute in range(4)
    ]

    remaining = sorted(path.name for path in tmp_path.glob("*.png"))
    expected = sorted(result.image_path.name for run in runs[2:] for result in run)
    assert remaining == expected
    assert len(list(tmp_path.glob("*.json"))) == len(expected)


def test_prune_keeps_image_that_a_display_still_shows(
    fake_desktop: FakeDesktop, life_config: LifeConfig, tmp_path: Path
) -> None:
    """設定に失敗して古い画像を表示し続けている画面では、その画像を消さない。"""
    applied = desktop.apply_wallpapers(life_config, CONFIG_FILE, tmp_path, now=START)
    fake_desktop.failing_ids = {1, 2, 3}
    for minute in range(1, 4):
        desktop.apply_wallpapers(
            life_config, CONFIG_FILE, tmp_path, keep=1, now=START + timedelta(minutes=minute)
        )

    for result in applied:
        assert result.image_path.is_file()
    # 画面ごとに、表示中の1枚と、いちばん新しい1枚が残る
    assert len(list(tmp_path.glob("*.png"))) == 6


def test_dry_run_does_not_prune(
    fake_desktop: FakeDesktop, life_config: LifeConfig, tmp_path: Path
) -> None:
    for minute in range(3):
        desktop.apply_wallpapers(
            life_config,
            CONFIG_FILE,
            tmp_path,
            keep=1,
            dry_run=True,
            now=START + timedelta(minutes=minute),
        )

    assert len(list(tmp_path.glob("*.png"))) == 9


def test_prune_is_skipped_when_current_image_is_unknown(
    fake_desktop: FakeDesktop, life_config: LifeConfig, tmp_path: Path
) -> None:
    """いまの壁紙を調べられない画面があれば、表示中の画像を守れないので消さない。"""
    fake_desktop.displays[1] = dataclasses.replace(
        fake_desktop.displays[1], current_image_known=False
    )
    fake_desktop.failing_ids = {2}
    for minute in range(3):
        desktop.apply_wallpapers(
            life_config, CONFIG_FILE, tmp_path, keep=1, now=START + timedelta(minutes=minute)
        )

    assert len(list(tmp_path.glob("*.png"))) == 9


def test_prune_leaves_files_it_did_not_create(
    fake_desktop: FakeDesktop, life_config: LifeConfig, tmp_path: Path
) -> None:
    (tmp_path / "other.png").write_bytes(b"not ours")
    (tmp_path / "other.json").write_text(json.dumps({"seed": 1}))
    (tmp_path / "broken.json").write_text("{")

    for minute in range(3):
        desktop.apply_wallpapers(
            life_config,
            CONFIG_FILE,
            tmp_path,
            keep=1,
            now=START + timedelta(minutes=minute),
        )

    assert (tmp_path / "other.png").read_bytes() == b"not ours"
    assert (tmp_path / "other.json").is_file()
    assert (tmp_path / "broken.json").is_file()


def test_display_removed_after_generation_is_not_applied(
    fake_desktop: FakeDesktop,
    life_config: LifeConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """画像を作っているあいだに画面が外れたら、その画面には設定しない。"""
    before = fake_desktop.displays
    listed = iter([before, before[:2], before[:2]])
    monkeypatch.setattr(osascript, "list_displays", lambda: list(next(listed)))

    results = desktop.apply_wallpapers(life_config, CONFIG_FILE, tmp_path, now=START)

    assert [result.applied for result in results] == [True, True, False]
    assert results[2].error == "画像を作ったあとに、画面が外れた"
    assert [display_id for display_id, _ in fake_desktop.applied] == [1, 2]


def test_display_with_changed_resolution_is_not_applied(
    fake_desktop: FakeDesktop,
    life_config: LifeConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = fake_desktop.displays
    after = [before[0], Display(2, "External A", 192, 80, 1.0, None), before[2]]
    listed = iter([before, after, after])
    monkeypatch.setattr(osascript, "list_displays", lambda: list(next(listed)))

    results = desktop.apply_wallpapers(life_config, CONFIG_FILE, tmp_path, now=START)

    assert [result.applied for result in results] == [True, False, True]
    assert results[1].error == "画像を作ったあとに、解像度が変わった（384x160 から 192x80）"


def test_failed_apply_is_reported_and_others_continue(
    fake_desktop: FakeDesktop, life_config: LifeConfig, tmp_path: Path
) -> None:
    fake_desktop.failing_ids = {2}

    results = desktop.apply_wallpapers(life_config, CONFIG_FILE, tmp_path, now=START)

    assert [result.applied for result in results] == [True, False, True]
    assert results[1].error == "setDesktopImageURL failed: recorded failure"


def test_keep_must_be_positive(
    fake_desktop: FakeDesktop, life_config: LifeConfig, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="残す枚数は1以上"):
        desktop.apply_wallpapers(life_config, CONFIG_FILE, tmp_path, keep=0)


@pytest.mark.parametrize(
    ("base", "main_scale", "scale", "expected"),
    [(3, 2.0, 1.0, 2), (3, 2.0, 2.0, 3), (2, 2.0, 1.0, 1), (1, 2.0, 1.0, 1), (3, 1.0, 2.0, 6)],
)
def test_matched_cell_size(base: int, main_scale: float, scale: float, expected: int) -> None:
    assert desktop.matched_cell_size(base, main_scale, scale) == expected


def test_cell_size_matches_main_display_in_points(
    fake_desktop: FakeDesktop, life_config: LifeConfig, tmp_path: Path
) -> None:
    """メイン（scale 2、3px）に合わせ、scale 1 の画面は 2px のセルで作る。"""
    results = desktop.apply_wallpapers(life_config, CONFIG_FILE, tmp_path, dry_run=True, now=START)

    cells = [json.loads(r.metadata_path.read_text())["cell_size"] for r in results]
    assert cells == [3, 2, 2]


def test_prune_ignores_metadata_that_points_at_another_file(tmp_path: Path) -> None:
    victim = tmp_path / "notes.txt"
    victim.write_text("keep me", encoding="utf-8")
    for index in range(3):
        meta = {
            "kind": desktop.KIND,
            "screen": {"key": "screen"},
            "image": "notes.txt",
            "created_at": f"2026-01-0{index + 1}T00:00:00",
        }
        (tmp_path / f"fake{index}.json").write_text(json.dumps(meta), encoding="utf-8")
    desktop.prune_old_images(tmp_path, keep=1, protected=set())
    assert victim.exists()
