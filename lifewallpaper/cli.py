"""エントリーポイントと引数の解釈。`run.sh` から `python -m lifewallpaper.cli <コマンド>` で呼ぶ。"""

import argparse
import logging
import sys
from pathlib import Path

from lifewallpaper import animation, atlas, config, desktop, eca, wallpaper
from lifewallpaper.ffmpeg import FfmpegError
from lifewallpaper.models import Resolution
from lifewallpaper.osascript import OsascriptError

DEFAULT_SEED = 42


def _output_dir(given: str | None) -> Path:
    """`--output` があればそのフォルダ、無ければ `<データのフォルダ>/output/` を返す。"""
    if given:
        return Path(given).expanduser()
    return config.data_dir(config.OUTPUT_SUBDIR)


def _resolution_argument(value: str) -> Resolution:
    """`--resolution` の値を解釈する。読めなければ、argparse の引数の誤り（終了コード 2）にする。"""
    try:
        return config.parse_resolution(value)
    except config.ConfigError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"1以上の整数で書く: {value}")
    return number


def _report_saved(path: Path) -> None:
    print(f"Saved: {path} ({path.stat().st_size // 1024} KB)")


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        required=True,
        help="設定の JSON のパス。config/ の中の名前でもよい（.json は省ける）",
    )
    parser.add_argument(
        "--resolution",
        default="macbook",
        type=_resolution_argument,
        metavar="R",
        help="画像の大きさ。名前（macbook、ultrawide、4k）か、幅x高さ（1600x1000 など）。既定は macbook",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="乱数の seed（既定は 42）")
    parser.add_argument(
        "--output", help="保存先のフォルダ（既定は ~/Pictures/life-wallpaper/output/）"
    )


def build_parser() -> argparse.ArgumentParser:
    """引数の解釈を組み立てる。"""
    parser = argparse.ArgumentParser(
        prog="run.sh", description="ライフゲームと1次元のセルオートマトンで、壁紙を作る"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate", help="ライフゲームの画像、GIF、動画を作る")
    _add_common_arguments(generate)
    generate.add_argument(
        "--format", default="png", choices=["png", "webp"], help="静止画の形式（どちらも劣化なし）"
    )
    kind = generate.add_mutually_exclusive_group()
    kind.add_argument(
        "--gif", action="store_true", help="静止画の代わりに、移り変わりの GIF を作る"
    )
    kind.add_argument(
        "--video", action="store_true", help="静止画の代わりに、長い MP4 を作る（ffmpeg が要る）"
    )

    eca_parser = commands.add_parser("eca", help="1次元のセルオートマトンの画像、動画を作る")
    _add_common_arguments(eca_parser)
    eca_parser.add_argument(
        "--video",
        action="store_true",
        help="静止画の代わりに、横スクロールの MP4 を作る（ffmpeg が要る）",
    )

    atlas_parser = commands.add_parser("atlas", help="設定の一覧のページを作り直す")
    atlas_parser.add_argument(
        "--output",
        help="書き出すページのパス（既定は ~/Pictures/life-wallpaper/atlas/pattern-atlas.html）",
    )

    apply_parser = commands.add_parser(
        "apply", help="接続中の画面ごとに、その解像度で壁紙を作り、その画面に設定する"
    )
    apply_parser.add_argument(
        "--config",
        default=config.DEFAULT_APPLY_CONFIG,
        help=f"設定の JSON のパスか、config/ の中の名前（既定は {config.DEFAULT_APPLY_CONFIG}）",
    )
    apply_parser.add_argument(
        "--seed",
        type=int,
        help="乱数の seed。省くと、画面ごとにランダムに決める。渡すと、すべての画面で同じ値を使う",
    )
    apply_parser.add_argument(
        "--keep",
        type=_positive_int,
        default=desktop.DEFAULT_KEEP,
        help=f"画面ごとに残す画像の枚数（既定は {desktop.DEFAULT_KEEP}）",
    )
    apply_parser.add_argument(
        "--dry-run", action="store_true", help="画像を作るところまでで止め、壁紙は設定しない"
    )
    return parser


def run_generate(args: argparse.Namespace) -> None:
    """`generate`: ライフゲームの静止画、GIF、動画のどれかを作る。"""
    life_config = config.load_life_config(config.resolve_config_path(args.config))
    resolution: Resolution = args.resolution
    output_dir = _output_dir(args.output)
    if args.video:
        path = animation.render_video(life_config, resolution, args.seed, output_dir)
    elif args.gif:
        path = animation.render_gif(life_config, resolution, args.seed, output_dir)
    else:
        path = wallpaper.generate_still(
            life_config, resolution, args.seed, output_dir, fmt=args.format
        )
    _report_saved(path)


def run_eca(args: argparse.Namespace) -> None:
    """`eca`: 1次元のセルオートマトンの静止画か動画を作る。"""
    eca_config = config.load_eca_config(config.resolve_config_path(args.config))
    resolution: Resolution = args.resolution
    output_dir = _output_dir(args.output)
    if args.video:
        path = eca.render_video(eca_config, resolution, args.seed, output_dir)
    else:
        path = eca.generate_still(eca_config, resolution, args.seed, output_dir)
    _report_saved(path)


def run_atlas(args: argparse.Namespace) -> None:
    """`atlas`: 設定の一覧のページを作り直す。"""
    if args.output:
        output_path = Path(args.output).expanduser()
    else:
        output_path = config.data_dir(config.ATLAS_SUBDIR) / config.ATLAS_NAME
    count = atlas.build_atlas(config.CONFIG_DIR, config.ATLAS_TEMPLATE, output_path)
    print(f"Saved: {output_path} ({count} configs)")


def run_apply(args: argparse.Namespace) -> int:
    """`apply`: 接続中の画面ごとに壁紙を作り、設定する。設定できない画面があれば 1 を返す。"""
    config_path = config.resolve_config_path(args.config)
    life_config = config.load_life_config(config_path)
    results = desktop.apply_wallpapers(
        life_config,
        config_path.name,
        config.data_dir(config.DESKTOP_SUBDIR),
        seed=args.seed,
        keep=args.keep,
        dry_run=args.dry_run,
    )
    if not results:
        print("エラー: 接続中の画面が見つからない", file=sys.stderr)
        return 1
    for result in results:
        display = result.display
        if result.applied:
            state = "適用した"
        elif result.error:
            state = f"適用できなかった（{result.error}）"
        else:
            state = "適用していない（dry-run）"
        print(
            f"{display.name} {display.width}x{display.height} seed={result.seed} "
            f"{result.seconds:.1f}s {state} -> {result.image_path}"
        )
    return 1 if any(result.error for result in results) else 0


def main(argv: list[str] | None = None) -> int:
    """コマンドを1つ動かし、終了コードを返す（0 = 成功、1 = 失敗、2 = 引数の誤り）。"""
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    handlers = {"generate": run_generate, "eca": run_eca, "atlas": run_atlas}
    try:
        if args.command == "apply":
            return run_apply(args)
        handlers[args.command](args)
    except (
        config.ConfigError,
        FfmpegError,
        atlas.AtlasError,
        OsascriptError,
        OSError,
    ) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
