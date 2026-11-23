#!/usr/bin/env bash
# life-wallpaper のエントリーポイント。コマンドと引数は README.md の「Commands」にある。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# スキルやほかのツールから呼ばれると PATH が短いことがある。uv、ruff、ffmpeg（Homebrew）を
# 見つけられるように、末尾に足す。osascript（apply が使う）は /usr/bin にある
export PATH="$PATH:/opt/homebrew/bin"

usage() {
  echo "使い方: run.sh apply [--config C] [--seed N] [--keep N] [--dry-run]" >&2
  echo "        run.sh generate --config C [--resolution macbook|ultrawide|4k|WxH] [--seed N] [--output DIR] [--format png|webp] [--gif | --video]" >&2
  echo "        run.sh eca --config C [--resolution macbook|ultrawide|4k|WxH] [--seed N] [--output DIR] [--video]" >&2
  echo "        run.sh atlas [--output FILE]" >&2
  echo "        run.sh check" >&2
}

command="${1:-}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "$command" in
  apply | generate | eca | atlas)
    # -P: 作業フォルダを import の探索先に入れない（呼んだ側のフォルダにある同名のパッケージを読まない）
    # --locked: uv.lock を書き換えない。lock と pyproject.toml が食い違えば止まる
    exec uv run --project "$ROOT_DIR" --locked --quiet python -P -m lifewallpaper.cli "$command" "$@"
    ;;
  check)
    cd "$ROOT_DIR"
    uv run --locked --quiet ruff format --check .
    uv run --locked --quiet ruff check .
    shellcheck run.sh
    uv run --locked --quiet mypy lifewallpaper
    uv run --locked --quiet pytest -q
    ;;
  *)
    usage
    exit 2
    ;;
esac
