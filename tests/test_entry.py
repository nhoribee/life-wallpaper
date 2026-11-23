"""エントリーポイント run.sh を、子プロセスとして動かすテスト。

リポの外の作業フォルダから呼び、uv の実行環境でコマンドが動くことを検証する。
出力の保存先（`LIFE_WALLPAPER_HOME`）は一時フォルダに向ける。
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import BASE, EXPECTED, FIXTURES, image_hash

RUN_SH = BASE / "run.sh"


def run_entry(args: list[str], cwd: Path, db_root: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "LIFE_WALLPAPER_HOME": str(db_root)}
    return subprocess.run(
        ["bash", str(RUN_SH), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        stdin=subprocess.DEVNULL,
        check=False,
    )


def test_run_sh_generate_saves_image_to_db_folder(tmp_path: Path, db_root: Path) -> None:
    args = ["generate", "--config", str(FIXTURES / "pattern_snapshot.json")]
    result = run_entry(args, tmp_path, db_root)
    assert result.returncode == 0, result.stderr
    saved = db_root / "output" / "pattern_snapshot_macbook_s42.png"
    assert result.stdout.startswith(f"Saved: {saved} (")
    assert image_hash(saved) == EXPECTED["macbook"]["generate/pattern_snapshot/s42"]


def test_run_sh_eca_saves_image(tmp_path: Path, db_root: Path) -> None:
    args = ["eca", "--config", str(FIXTURES / "eca_rule90.json"), "--output", str(tmp_path / "o")]
    result = run_entry(args, tmp_path, db_root)
    assert result.returncode == 0, result.stderr
    saved = tmp_path / "o" / "eca_rule90_macbook_s42.png"
    assert image_hash(saved) == EXPECTED["macbook"]["eca/eca_rule90/s42"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")
def test_run_sh_generate_video_writes_mp4_with_real_ffmpeg(tmp_path: Path, db_root: Path) -> None:
    args = ["generate", "--config", str(FIXTURES / "plain_gif.json"), "--video"]
    result = run_entry([*args, "--output", str(tmp_path)], tmp_path, db_root)
    assert result.returncode == 0, result.stderr
    saved = tmp_path / "plain_gif_macbook_s42.mp4"
    assert saved.stat().st_size > 0
    # MP4 は、先頭の箱（ftyp）で見分けられる
    assert saved.read_bytes()[4:8] == b"ftyp"


def test_run_sh_atlas_writes_page(tmp_path: Path, db_root: Path) -> None:
    result = run_entry(["atlas"], tmp_path, db_root)
    assert result.returncode == 0, result.stderr
    page = db_root / "atlas" / "pattern-atlas.html"
    assert result.stdout.startswith(f"Saved: {page} (")
    assert '"_file": "10_motif_field_hires_t1500.json"' in page.read_text()


def test_run_sh_unknown_command_shows_usage(tmp_path: Path, db_root: Path) -> None:
    result = run_entry(["no-such-command"], tmp_path, db_root)
    assert result.returncode == 2
    assert "使い方: run.sh apply" in result.stderr
    assert "run.sh generate --config C" in result.stderr


def test_run_sh_generate_help(tmp_path: Path, db_root: Path) -> None:
    result = run_entry(["generate", "--help"], tmp_path, db_root)
    assert result.returncode == 0, result.stderr
    assert "--resolution" in result.stdout


def test_run_sh_apply_help(tmp_path: Path, db_root: Path) -> None:
    result = run_entry(["apply", "--help"], tmp_path, db_root)
    assert result.returncode == 0, result.stderr
    assert "--dry-run" in result.stdout


def test_run_sh_apply_does_not_touch_displays_under_pytest(tmp_path: Path, db_root: Path) -> None:
    """子プロセスにも PYTEST_CURRENT_TEST が伝わるので、osascript を動かさずに失敗で終わる。"""
    result = run_entry(["apply", "--dry-run"], tmp_path, db_root)
    assert result.returncode == 1
    assert "pytest の下では osascript を動かさない" in result.stderr
    assert list(db_root.rglob("*.png")) == []


def test_run_sh_generate_accepts_width_x_height(tmp_path: Path, db_root: Path) -> None:
    args = [
        "generate",
        "--config",
        str(FIXTURES / "pattern_snapshot.json"),
        "--resolution",
        "320x200",
    ]
    result = run_entry([*args, "--output", str(tmp_path)], tmp_path, db_root)
    assert result.returncode == 0, result.stderr
    saved = tmp_path / "pattern_snapshot_320x200_s42.png"
    assert image_hash(saved) == EXPECTED["320x200"]["generate/pattern_snapshot/s42"]
