"""ffmpeg の呼び出し。生の RGB のコマを流し込んで、MP4（H.264）にする。"""

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO


class FfmpegError(RuntimeError):
    """ffmpeg が無い、または動画を書き出せなかった。"""


class Encoder:
    """動かしている ffmpeg に、コマを1枚ずつ渡す口。"""

    def __init__(self, stdin: IO[bytes]) -> None:
        self._stdin = stdin

    def write(self, frame: bytes) -> None:
        """コマ1枚（幅 x 高さ x 3 バイトの RGB）を渡す。"""
        self._stdin.write(frame)


@contextmanager
def open_encoder(path: Path, width: int, height: int, fps: int) -> Iterator[Encoder]:
    """ffmpeg を動かし、コマを渡す口を返す。ブロックを抜けると、動画を書き終えるまで待つ。

    Args:
        path: 書き出す MP4 のパス。同じ名前のファイルは上書きする。
        width: コマの幅（ピクセル。yuv420p のため偶数）。
        height: コマの高さ（ピクセル。偶数）。
        fps: 1秒あたりのコマの数。

    Raises:
        FfmpegError: ffmpeg が見つからない、または 0 以外の終了コードで終わった。
    """
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "20",
        "-movflags",
        "+faststart",
        # 絶対パスで渡し、`proto:` で始まる名前を ffmpeg が URL として読まないようにする
        str(path.resolve()),
    ]
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE)
    except FileNotFoundError as error:
        raise FfmpegError("ffmpeg が見つからない（動画の書き出しには ffmpeg が要る）") from error
    if process.stdin is None:
        process.kill()
        raise FfmpegError("ffmpeg にコマを渡す口を開けなかった")
    try:
        yield Encoder(process.stdin)
    except BrokenPipeError as error:
        process.wait()
        raise FfmpegError(
            f"ffmpeg が途中で終わった（終了コード {process.returncode}）: {path}"
        ) from error
    except BaseException:
        process.kill()
        process.wait()
        raise
    process.stdin.close()
    return_code = process.wait()
    if return_code != 0:
        raise FfmpegError(f"ffmpeg が失敗した（終了コード {return_code}）: {path}")
