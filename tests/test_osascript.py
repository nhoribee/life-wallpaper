"""osascript の呼び出し（lifewallpaper.osascript）のテスト。

osascript そのものは動かさず、返事を記録（`fixtures/displays.json`）に置き換える。
"""

from pathlib import Path

import pytest
from conftest import FIXTURES

from lifewallpaper import osascript
from lifewallpaper.models import Display

RECORDED_DISPLAYS = (FIXTURES / "displays.json").read_text(encoding="utf-8")


def test_list_displays_returns_physical_pixels(monkeypatch: pytest.MonkeyPatch) -> None:
    """frame（ポイント）に backingScaleFactor を掛けた、物理ピクセルの大きさを返す。"""
    monkeypatch.setattr(osascript, "_run_jxa", lambda script, *arguments: RECORDED_DISPLAYS)

    displays = osascript.list_displays()

    assert displays == [
        Display(
            1,
            "Built-in Retina Display",
            3024,
            1964,
            2.0,
            "/Users/example/WallPaper/lifegame/motif_field_hires-3px_t1500_macbook_s42.png",
        ),
        Display(
            2,
            "External A",
            3840,
            1600,
            1.0,
            "/Users/example/WallPaper/lifegame/motif_field_t150_4k_s42.png",
        ),
        Display(3, "External B", 1600, 1000, 1.0, None),
    ]


@pytest.mark.parametrize(
    "output",
    [
        "not json",
        "{}",
        '[{"id": 1, "name": "A"}]',
        '[{"id": "1", "name": "A", "frame_width": 10, "frame_height": 10, "scale": 1, "current_image": null}]',
        '[{"id": 1, "name": "A", "frame_width": 0, "frame_height": 10, "scale": 1, "current_image": null}]',
    ],
)
def test_list_displays_rejects_unreadable_output(
    output: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(osascript, "_run_jxa", lambda script, *arguments: output)

    with pytest.raises(osascript.OsascriptError):
        osascript.list_displays()


def test_set_desktop_image_passes_display_id_and_path(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def record(script: str, *arguments: str) -> str:
        calls.append((script, arguments))
        return '{"applied": true}'

    monkeypatch.setattr(osascript, "_run_jxa", record)

    osascript.set_desktop_image(2, Path("/tmp/wallpaper.png"))

    ((script, arguments),) = calls
    assert "setDesktopImageURLForScreenOptionsError" in script
    assert arguments == ("2", "/tmp/wallpaper.png")


def test_osascript_is_not_run_under_pytest() -> None:
    """置き換えを忘れたテストがあっても、本物の画面と壁紙の設定には届かない。"""
    with pytest.raises(osascript.OsascriptError, match="pytest の下では osascript を動かさない"):
        osascript.list_displays()
    with pytest.raises(osascript.OsascriptError, match="pytest の下では osascript を動かさない"):
        osascript.set_desktop_image(1, Path("/tmp/wallpaper.png"))


def test_list_displays_marks_unknown_current_image(monkeypatch: pytest.MonkeyPatch) -> None:
    """いまの壁紙を調べられなかった画面は、壁紙が無い画面と区別する。"""
    output = (
        '[{"id": 1, "name": "A", "frame_width": 10, "frame_height": 10, "scale": 1,'
        ' "current_image": null, "current_image_known": false}]'
    )
    monkeypatch.setattr(osascript, "_run_jxa", lambda script, *arguments: output)

    (display,) = osascript.list_displays()

    assert display.current_image is None
    assert display.current_image_known is False
