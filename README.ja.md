# life-wallpaper

ライフゲーム（Conway）と1次元のセルオートマトン（Wolfram のルール）で、デスクトップの壁紙の画像、GIF、動画を作るツールです。
`apply` は、接続中の画面ごとに、その画面の解像度（物理ピクセル）で画像を1枚作り、その画面の壁紙に設定します（macOS）。

## 入れ方

Claude Code のプラグインとして入れる場合は、次の2行を実行します。
そのあと「壁紙を更新して」と頼むと、スキル `life-wallpaper` が動きます。

```text
/plugin marketplace add nhoribee/life-wallpaper
/plugin install life-wallpaper@life-wallpaper
```

CLI として使う場合は、clone して `run.sh` を呼びます。

```bash
git clone https://github.com/nhoribee/life-wallpaper
cd life-wallpaper
./run.sh apply --dry-run
```

必要なものは、macOS（`apply` のため）、Python 3.13 以上、[uv](https://docs.astral.sh/uv/) です。
`--video` を使うときだけ ffmpeg も要ります。

## コマンド

| コマンド | すること |
|---|---|
| `apply [--config C] [--seed N] [--keep N] [--dry-run]` | 接続中の画面ごとに、その解像度で静止画を1枚作り、その画面の壁紙に設定する。セルの大きさは、メインの画面での見た目の大きさ（ポイント）にそろえ、整数の px に丸める。`--dry-run` は画像を作るだけで、設定しない |
| `generate --config C [--resolution R] [--seed N] [--output DIR] [--format png\|webp] [--gif \| --video]` | ライフゲームの静止画、GIF、MP4 を作る |
| `eca --config C [--resolution R] [--seed N] [--output DIR] [--video]` | 1次元のセルオートマトンの静止画か、横スクロールの MP4 を作る |
| `atlas [--output FILE]` | `config/` の設定をブラウザの中で動かして見比べるページを作る |
| `check` | 整形、lint、shellcheck、型、テストをまとめて走らせる |

| 引数 | 意味 | 既定 |
|---|---|---|
| `--config C` | 設定の JSON のパスか、`config/` の中の名前（`.json` は省ける） | `apply` は `10_motif_field_hires_t1500`。`generate` と `eca` では必須 |
| `--resolution R` | `macbook`（3024x1964）、`ultrawide`（3840x1600）、`4k`（3840x2160）、または `幅x高さ`（1辺 16384 まで） | `macbook` |
| `--seed N` | 乱数の seed。設定、解像度、seed が同じなら同じ画像になる | 42（`apply` は画面ごとにランダム） |
| `--keep N` | `apply` が画面ごとに残す画像の枚数 | 5 |
| `--output DIR` | `generate` と `eca` の保存先 | `~/Pictures/life-wallpaper/output/` |

終了コードは、成功が 0、失敗が 1、引数の誤りが 2 です。

## 保存先

出力はすべて `~/Pictures/life-wallpaper/` の下に書きます（環境変数 `LIFE_WALLPAPER_HOME` で変えられます）。
`generate` と `eca` は `output/`、`apply` は `desktop/`、`atlas` は `atlas/` に書きます。
`apply` の画像には、作り直すための seed と設定を書いた JSON が付きます。

## 注意

- 画面は osascript（JXA）から AppKit の NSScreen を読んで調べ、壁紙は NSWorkspace の `setDesktopImageURL:forScreen:options:error:` で設定します。拡大の方法と余白の色は、その画面のいまの設定を引き継ぎます。変わるのは、各画面でいま表示している Space の壁紙だけです。
- macOS は同じパスの画像を差し替えても表示を更新しないので、ファイル名に日時を入れています。
- 古い画像を消すとき、いまどれかの画面に表示している画像は残します。ほかの Space に設定した画像は調べられないので、`--keep` の枚数より古くなると消えます。
- テストでは osascript を動かさず、本物の壁紙には触れません。
- 設定の一覧のページは、Python と同じ計算を JavaScript で書き直したものです。`lifewallpaper/life.py` と `lifewallpaper/motifs.py` を変えたら、`lifewallpaper/atlas_template.html` も変更してください。

## ライセンス

MIT
