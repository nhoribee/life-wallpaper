"""コマンド（generate、eca、atlas、apply）のスモークテスト。

決まった設定と seed で動かし、基準の出力（`fixtures/expected.json`）と
同じ画像になるかを検証する。
"""

import json
from pathlib import Path

import pytest
from conftest import EXPECTED, FIXTURES, FakeDesktop, RecordedEncoder, gif_hash, image_hash
from PIL import Image

from lifewallpaper import cli

MACBOOK = EXPECTED["macbook"]
SMALL = EXPECTED["320x200"]


def run_cli(*args: str) -> int:
    return cli.main(list(args))


@pytest.mark.parametrize(
    ("name", "seed"),
    [
        ("motif_snapshot", 42),
        ("motif_snapshot", 7),
        ("motif_heatmap", 42),
        ("motif_heatmap", 7),
        ("random_heatmap", 42),
        ("random_heatmap", 7),
        ("pattern_snapshot", 42),
    ],
)
def test_generate_still_matches_baseline(name: str, seed: int, tmp_path: Path) -> None:
    config = str(FIXTURES / f"{name}.json")
    code = run_cli("generate", "--config", config, "--seed", str(seed), "--output", str(tmp_path))
    assert code == 0
    assert (
        image_hash(tmp_path / f"{name}_macbook_s{seed}.png") == MACBOOK[f"generate/{name}/s{seed}"]
    )


def test_generate_writes_metadata_next_to_image(tmp_path: Path) -> None:
    config_path = FIXTURES / "pattern_snapshot.json"
    code = run_cli("generate", "--config", str(config_path), "--output", str(tmp_path))
    assert code == 0
    metadata = json.loads((tmp_path / "pattern_snapshot_macbook_s42.json").read_text())
    assert metadata == {
        "seed": 42,
        "resolution": "macbook",
        "grid_rows": 1964 // 7,
        "grid_cols": 3024 // 7,
        "config": json.loads(config_path.read_text()),
    }


def test_generate_webp_has_same_pixels_as_png(tmp_path: Path) -> None:
    config = str(FIXTURES / "motif_snapshot.json")
    code = run_cli("generate", "--config", config, "--format", "webp", "--output", str(tmp_path))
    assert code == 0
    saved = tmp_path / "motif_snapshot_macbook_s42.webp"
    assert image_hash(saved) == MACBOOK["generate/motif_snapshot/s42/webp"]


@pytest.mark.parametrize("name", ["motif_snapshot", "plain_gif"])
def test_generate_gif_matches_baseline(name: str, tmp_path: Path) -> None:
    config = str(FIXTURES / f"{name}.json")
    code = run_cli("generate", "--config", config, "--gif", "--output", str(tmp_path))
    assert code == 0
    assert gif_hash(tmp_path / f"{name}_macbook_s42.gif") == MACBOOK[f"generate/{name}/s42/gif"]


def test_generate_video_sends_baseline_frames_to_encoder(
    tmp_path: Path, recorded_encoders: list[RecordedEncoder]
) -> None:
    config = str(FIXTURES / "motif_snapshot.json")
    code = run_cli("generate", "--config", config, "--video", "--output", str(tmp_path))
    assert code == 0
    (encoder,) = recorded_encoders
    assert encoder.path == tmp_path / "motif_snapshot_macbook_s42.mp4"
    assert encoder.frame_count == 9
    assert encoder.hexdigest() == MACBOOK["generate/motif_snapshot/s42/video"]


def test_generate_saves_to_db_folder_by_default(db_root: Path) -> None:
    code = run_cli("generate", "--config", str(FIXTURES / "pattern_snapshot.json"))
    assert code == 0
    saved = db_root / "output" / "pattern_snapshot_macbook_s42.png"
    assert image_hash(saved) == MACBOOK["generate/pattern_snapshot/s42"]


def test_generate_accepts_config_name_in_service_config_folder(tmp_path: Path) -> None:
    """`config/` の中の名前だけでも設定を選べる（.json は省ける）。"""
    code = run_cli("generate", "--config", "01_random_snapshot", "--output", str(tmp_path))
    assert code == 0
    assert (tmp_path / "random_snapshot_macbook_s42.png").is_file()


def test_generate_reports_missing_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_cli("generate", "--config", "no_such_config", "--output", str(tmp_path))
    assert code == 1
    assert "設定のファイルが無い" in capsys.readouterr().err


def test_generate_reports_unknown_preset(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"cell_size": 24, "patterns": [{"name": "no-such-pattern"}]}))
    code = run_cli("generate", "--config", str(broken), "--output", str(tmp_path))
    assert code == 1
    assert "知らない種のパターン: no-such-pattern" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["eca_rule30", "eca_rule90"])
def test_eca_still_matches_baseline(name: str, tmp_path: Path) -> None:
    config = str(FIXTURES / f"{name}.json")
    code = run_cli("eca", "--config", config, "--output", str(tmp_path))
    assert code == 0
    assert image_hash(tmp_path / f"{name}_macbook_s42.png") == MACBOOK[f"eca/{name}/s42"]
    metadata = json.loads((tmp_path / f"{name}_macbook_s42.json").read_text())
    assert metadata["seed"] == 42
    assert metadata["resolution"] == "macbook"


def test_eca_video_sends_baseline_frames_to_encoder(
    tmp_path: Path, recorded_encoders: list[RecordedEncoder]
) -> None:
    config = str(FIXTURES / "eca_rule30.json")
    code = run_cli("eca", "--config", config, "--video", "--output", str(tmp_path))
    assert code == 0
    (encoder,) = recorded_encoders
    assert encoder.frame_count == 4
    assert encoder.hexdigest() == MACBOOK["eca/eca_rule30/s42/video"]


def test_eca_rejects_config_without_rule(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_cli(
        "eca", "--config", str(FIXTURES / "pattern_snapshot.json"), "--output", str(tmp_path)
    )
    assert code == 1
    assert "rule は 0〜255 の整数で書く" in capsys.readouterr().err


def test_atlas_embeds_life_configs_into_page(db_root: Path) -> None:
    code = run_cli("atlas")
    assert code == 0
    page = (db_root / "atlas" / "pattern-atlas.html").read_text()
    embedded = page.split("const CONFIGS = ", 1)[1].split(";\n// CONFIGS:END", 1)[0]
    configs = json.loads(embedded)
    files = [config["_file"] for config in configs]
    assert "10_motif_field_hires_t1500.json" in files
    assert files == sorted(files)
    assert not any(name.startswith("eca") for name in files)


def test_atlas_leaves_template_untouched(tmp_path: Path) -> None:
    template = Path(cli.config.ATLAS_TEMPLATE)
    before = template.read_bytes()
    code = run_cli("atlas", "--output", str(tmp_path / "page.html"))
    assert code == 0
    assert template.read_bytes() == before
    assert "const CONFIGS = [];" in before.decode()


@pytest.mark.parametrize(
    ("name", "seed"),
    [
        ("motif_snapshot", 42),
        ("motif_snapshot", 7),
        ("motif_heatmap", 42),
        ("motif_heatmap", 7),
        ("random_heatmap", 42),
        ("random_heatmap", 7),
        ("pattern_snapshot", 42),
    ],
)
def test_generate_still_at_given_size_matches_baseline(
    name: str, seed: int, tmp_path: Path
) -> None:
    """`幅x高さ` で渡した解像度でも、その大きさぴったりの、基準と同じ画像になる。"""
    config = str(FIXTURES / f"{name}.json")
    code = run_cli(
        "generate",
        "--config",
        config,
        "--resolution",
        "320x200",
        "--seed",
        str(seed),
        "--output",
        str(tmp_path),
    )
    assert code == 0
    saved = tmp_path / f"{name}_320x200_s{seed}.png"
    with Image.open(saved) as image:
        assert image.size == (320, 200)
    assert image_hash(saved) == SMALL[f"generate/{name}/s{seed}"]


@pytest.mark.parametrize("name", ["motif_snapshot", "plain_gif"])
def test_generate_gif_at_given_size_matches_baseline(name: str, tmp_path: Path) -> None:
    config = str(FIXTURES / f"{name}.json")
    code = run_cli(
        "generate",
        "--config",
        config,
        "--resolution",
        "320x200",
        "--gif",
        "--output",
        str(tmp_path),
    )
    assert code == 0
    assert gif_hash(tmp_path / f"{name}_320x200_s42.gif") == SMALL[f"generate/{name}/s42/gif"]


def test_generate_video_at_given_size_sends_baseline_frames(
    tmp_path: Path, recorded_encoders: list[RecordedEncoder]
) -> None:
    config = str(FIXTURES / "motif_snapshot.json")
    code = run_cli(
        "generate",
        "--config",
        config,
        "--resolution",
        "320x200",
        "--video",
        "--output",
        str(tmp_path),
    )
    assert code == 0
    (encoder,) = recorded_encoders
    assert encoder.hexdigest() == SMALL["generate/motif_snapshot/s42/video"]


@pytest.mark.parametrize("name", ["eca_rule30", "eca_rule90"])
def test_eca_still_at_given_size_matches_baseline(name: str, tmp_path: Path) -> None:
    config = str(FIXTURES / f"{name}.json")
    code = run_cli("eca", "--config", config, "--resolution", "320x200", "--output", str(tmp_path))
    assert code == 0
    assert image_hash(tmp_path / f"{name}_320x200_s42.png") == SMALL[f"eca/{name}/s42"]


def test_eca_video_at_given_size_sends_baseline_frames(
    tmp_path: Path, recorded_encoders: list[RecordedEncoder]
) -> None:
    config = str(FIXTURES / "eca_rule30.json")
    code = run_cli(
        "eca", "--config", config, "--resolution", "320x200", "--video", "--output", str(tmp_path)
    )
    assert code == 0
    (encoder,) = recorded_encoders
    assert encoder.hexdigest() == SMALL["eca/eca_rule30/s42/video"]


def test_generate_rejects_unreadable_resolution(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        run_cli("generate", "--config", "01_random_snapshot", "--resolution", "huge")
    assert raised.value.code == 2
    assert "解像度は名前" in capsys.readouterr().err


def test_generate_reports_resolution_smaller_than_cell(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = str(FIXTURES / "pattern_snapshot.json")
    code = run_cli("generate", "--config", config, "--resolution", "5x5", "--output", str(tmp_path))
    assert code == 1
    assert "セルの大きさ（7）より小さい" in capsys.readouterr().err


def test_apply_dry_run_generates_images_without_setting_wallpaper(
    fake_desktop: FakeDesktop, db_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = str(FIXTURES / "motif_snapshot.json")
    code = run_cli("apply", "--config", config, "--seed", "42", "--dry-run")
    assert code == 0
    assert fake_desktop.applied == []
    folder = db_root / "desktop"
    sizes = []
    for path in sorted(folder.glob("*.png")):
        with Image.open(path) as image:
            sizes.append(image.size)
    assert sorted(sizes) == [(160, 100), (320, 200), (384, 160)]
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("Built-in Retina Display 320x200 seed=42 ")
    assert all("適用していない（dry-run）" in line for line in lines)


def test_apply_sets_wallpaper_on_every_display(
    fake_desktop: FakeDesktop, db_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = str(FIXTURES / "motif_snapshot.json")
    code = run_cli("apply", "--config", config)
    assert code == 0
    folder = db_root / "desktop"
    assert [display_id for display_id, _ in fake_desktop.applied] == [1, 2, 3]
    assert all(path.parent == folder and path.is_file() for _, path in fake_desktop.applied)
    assert capsys.readouterr().out.count("適用した ->") == 3


def test_apply_returns_failure_when_a_display_cannot_be_set(
    fake_desktop: FakeDesktop, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_desktop.failing_ids = {3}
    code = run_cli("apply", "--config", str(FIXTURES / "motif_snapshot.json"))
    assert code == 1
    assert "External B 160x100" in capsys.readouterr().out


def test_apply_reports_no_display(
    fake_desktop: FakeDesktop, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_desktop.displays = []
    code = run_cli("apply", "--dry-run")
    assert code == 1
    assert "接続中の画面が見つからない" in capsys.readouterr().err
