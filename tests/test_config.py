"""設定とパス（lifewallpaper.config）のテスト。"""

import json
from pathlib import Path

import pytest

from lifewallpaper import config
from lifewallpaper.models import Resolution


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("macbook", Resolution("macbook", 3024, 1964)),
        ("ultrawide", Resolution("ultrawide", 3840, 1600)),
        ("4k", Resolution("4k", 3840, 2160)),
        ("1600x1000", Resolution("1600x1000", 1600, 1000)),
        ("3024X1964", Resolution("3024x1964", 3024, 1964)),
    ],
)
def test_parse_resolution_accepts_names_and_sizes(value: str, expected: Resolution) -> None:
    assert config.parse_resolution(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "big", "1600", "1600x", "x1000", "1600*1000", "-1x5", "0x100", "100x0", "99999x100"],
)
def test_parse_resolution_rejects_other_forms(value: str) -> None:
    with pytest.raises(config.ConfigError):
        config.parse_resolution(value)


def test_resolve_config_path_finds_name_in_service_config_folder() -> None:
    expected = config.CONFIG_DIR / "10_motif_field_hires_t1500.json"
    assert config.resolve_config_path("10_motif_field_hires_t1500") == expected
    assert config.resolve_config_path("10_motif_field_hires_t1500.json") == expected


def test_default_apply_config_exists() -> None:
    path = config.resolve_config_path(config.DEFAULT_APPLY_CONFIG)
    assert config.load_life_config(path)["name"] == "motif_field_hires-3px_t1500"


@pytest.mark.parametrize("name", ["../../evil", "/tmp/evil", ".hidden", "a/b", "", "x" * 101])
def test_config_name_that_could_leave_the_data_folder_is_rejected(
    tmp_path: Path, name: str
) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"name": name}), encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.load_life_config(path)


def test_bundled_config_wins_over_same_name_in_working_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / config.DEFAULT_APPLY_CONFIG).write_text("{}", encoding="utf-8")
    resolved = config.resolve_config_path(config.DEFAULT_APPLY_CONFIG)
    assert resolved.parent == config.CONFIG_DIR


def test_every_bundled_config_loads() -> None:
    for path in sorted(config.CONFIG_DIR.glob("*.json")):
        if path.name.startswith("eca"):
            config.load_eca_config(path)
        else:
            config.load_life_config(path)
