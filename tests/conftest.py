"""テストの共通の準備。

どのテストでも、出力の保存先（環境変数 `LIFE_WALLPAPER_HOME`）を一時フォルダに向ける。
本物のデータのフォルダには書かない。

基準の出力（`fixtures/expected.json`）は、同じ設定と seed で動かして採った、画素のハッシュである。
計算を変えても同じ画像ができることを、これと比べて検証する。計算を意図して変えたときだけ、採り直す。

本物の画面と壁紙の設定には届かない。`lifewallpaper.osascript` は pytest の下で osascript を動かさず、
画面を使うテストは `fake_desktop` で、画面の一覧と壁紙の設定を記録に置き換える。
`fixtures/displays.json` は、osascript が返す画面の一覧の形を、実機の返事から採ったものである
（壁紙のパスは作った例に替えた）。
"""

import dataclasses
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from PIL import Image

from lifewallpaper import ffmpeg, osascript
from lifewallpaper.models import Display

BASE = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXPECTED: dict[str, dict[str, str]] = json.loads(
    (FIXTURES / "expected.json").read_text(encoding="utf-8")
)


def image_hash(path: Path) -> str:
    """画像の大きさと画素（RGB）のハッシュを返す。ファイルの形式や圧縮には左右されない。"""
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        digest = hashlib.sha256(f"{rgb.width}x{rgb.height}".encode())
        digest.update(rgb.tobytes())
    return digest.hexdigest()


def gif_hash(path: Path) -> str:
    """GIF の大きさ、コマの数、各コマの表示時間と画素のハッシュを返す。"""
    digest = hashlib.sha256()
    with Image.open(path) as image:
        frame_count = getattr(image, "n_frames", 1)
        digest.update(f"{image.width}x{image.height}x{frame_count}".encode())
        for index in range(frame_count):
            image.seek(index)
            digest.update(str(image.info.get("duration")).encode())
            digest.update(image.convert("RGB").tobytes())
    return digest.hexdigest()


class RecordedEncoder:
    """ffmpeg の代わりに、渡されたコマを記録する。"""

    def __init__(self, path: Path, width: int, height: int, fps: int) -> None:
        self.path = path
        self.frame_count = 0
        self._digest = hashlib.sha256(f"{width}x{height}@{fps}".encode())

    def write(self, frame: bytes) -> None:
        self.frame_count += 1
        self._digest.update(frame)

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


class FakeDesktop:
    """osascript の代わり。画面の一覧を返し、壁紙の設定を記録する。

    Attributes:
        displays: いま接続している画面。テストの途中で書き換えると、つなぎ替えを再現できる。
        applied: 設定された（画面の番号、画像のパス）。呼ばれた順。
        failing_ids: 壁紙の設定を失敗させる画面の番号。
    """

    def __init__(self, displays: list[Display]) -> None:
        self.displays = displays
        self.applied: list[tuple[int, Path]] = []
        self.failing_ids: set[int] = set()

    def list_displays(self) -> list[Display]:
        return list(self.displays)

    def set_desktop_image(self, display_id: int, image_path: Path) -> None:
        if display_id in self.failing_ids:
            raise osascript.OsascriptError("setDesktopImageURL failed: recorded failure")
        self.applied.append((display_id, image_path))
        self.displays = [
            dataclasses.replace(display, current_image=str(image_path))
            if display.display_id == display_id
            else display
            for display in self.displays
        ]


@pytest.fixture
def fake_desktop(monkeypatch: pytest.MonkeyPatch) -> FakeDesktop:
    """小さな画面を3つつないだことにする（内蔵の Retina、横長、小型）。"""
    desktop = FakeDesktop(
        [
            Display(1, "Built-in Retina Display", 320, 200, 2.0, "/somewhere/else/current.png"),
            Display(2, "External A", 384, 160, 1.0, None),
            Display(3, "External B", 160, 100, 1.0, None),
        ]
    )
    monkeypatch.setattr(osascript, "list_displays", desktop.list_displays)
    monkeypatch.setattr(osascript, "set_desktop_image", desktop.set_desktop_image)
    return desktop


@pytest.fixture(autouse=True)
def db_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """出力の保存先を、一時フォルダに向ける。"""
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("LIFE_WALLPAPER_HOME", str(root))
    return root


@pytest.fixture
def recorded_encoders(monkeypatch: pytest.MonkeyPatch) -> list[RecordedEncoder]:
    """ffmpeg を動かさず、渡されたコマを記録に置き換える。記録を、呼ばれた順に返す。"""
    encoders: list[RecordedEncoder] = []

    @contextmanager
    def fake_open_encoder(
        path: Path, width: int, height: int, fps: int
    ) -> Iterator[RecordedEncoder]:
        encoder = RecordedEncoder(path, width, height, fps)
        encoders.append(encoder)
        yield encoder
        path.write_bytes(b"recorded")

    monkeypatch.setattr(ffmpeg, "open_encoder", fake_open_encoder)
    return encoders
