"""osascript（JXA）の呼び出し。接続中のディスプレイを調べ、画面ごとに壁紙を設定する。

AppKit の NSScreen と NSWorkspace を、JavaScript for Automation から呼ぶ。
PyObjC を依存に足さずに済ませるためである（osascript は macOS に最初から入っている）。
"""

import json
import os
import subprocess
from pathlib import Path

from lifewallpaper.models import Display

_TIMEOUT_SECONDS = 30

# 画面ごとに、番号、名前、frame（ポイント）、backingScaleFactor、いまの壁紙のパスを JSON で返す
_LIST_DISPLAYS_SCRIPT = """
function run(argv) {
  ObjC.import("AppKit");
  const workspace = $.NSWorkspace.sharedWorkspace;
  const screens = $.NSScreen.screens;
  const displays = [];
  for (let index = 0; index < screens.count; index++) {
    const screen = screens.objectAtIndex(index);
    let currentImage = null;
    let currentImageKnown = true;
    try {
      const url = workspace.desktopImageURLForScreen(screen);
      if (!url.isNil()) {
        currentImage = ObjC.unwrap(url.path);
      }
    } catch (error) {
      currentImage = null;
      currentImageKnown = false;
    }
    displays.push({
      id: ObjC.unwrap(screen.deviceDescription.objectForKey("NSScreenNumber")),
      name: ObjC.unwrap(screen.localizedName),
      frame_width: screen.frame.size.width,
      frame_height: screen.frame.size.height,
      scale: screen.backingScaleFactor,
      current_image: currentImage === undefined ? null : currentImage,
      current_image_known: currentImageKnown,
    });
  }
  return JSON.stringify(displays);
}
"""

# 番号で選んだ画面に、画像を壁紙として設定する。拡大の方法や余白の色は、その画面のいまの設定を引き継ぐ
_SET_DESKTOP_IMAGE_SCRIPT = """
function run(argv) {
  ObjC.import("AppKit");
  const displayId = Number(argv[0]);
  const imagePath = argv[1];
  const workspace = $.NSWorkspace.sharedWorkspace;
  const screens = $.NSScreen.screens;
  let target = null;
  for (let index = 0; index < screens.count; index++) {
    const screen = screens.objectAtIndex(index);
    const id = ObjC.unwrap(screen.deviceDescription.objectForKey("NSScreenNumber"));
    if (id === displayId) {
      target = screen;
    }
  }
  if (target === null) {
    throw new Error("display not found: " + displayId);
  }
  let options = workspace.desktopImageOptionsForScreen(target);
  if (options.isNil()) {
    options = $.NSDictionary.dictionary;
  }
  const error = $();
  const url = $.NSURL.fileURLWithPath(imagePath);
  const applied = workspace.setDesktopImageURLForScreenOptionsError(url, target, options, error);
  if (!applied) {
    const reason = error.isNil() ? "unknown" : ObjC.unwrap(error.localizedDescription);
    throw new Error("setDesktopImageURL failed: " + reason);
  }
  return JSON.stringify({applied: true});
}
"""


class OsascriptError(RuntimeError):
    """osascript を動かせなかった、失敗した、または返事が読めなかった。"""


def _run_jxa(script: str, *arguments: str) -> str:
    """JXA のスクリプトを osascript で動かし、標準出力を返す。

    pytest の下では動かさない。テストから本物の画面と壁紙の設定に届かないようにするためで、
    テストは、この関数を記録した返事に置き換えて使う。

    Raises:
        OsascriptError: pytest の下で呼ばれた、osascript が無い、時間切れ、0 以外の終了コード。
    """
    if "PYTEST_CURRENT_TEST" in os.environ:
        raise OsascriptError("pytest の下では osascript を動かさない")
    command = ["osascript", "-l", "JavaScript", "-e", script, *arguments]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError as error:
        raise OsascriptError("osascript が見つからない（macOS でだけ動く）") from error
    except subprocess.TimeoutExpired as error:
        raise OsascriptError(f"osascript が {_TIMEOUT_SECONDS} 秒たっても終わらない") from error
    if result.returncode != 0:
        raise OsascriptError(
            f"osascript が失敗した（終了コード {result.returncode}）: {result.stderr.strip()}"
        )
    return result.stdout


def _positive_number(value: object) -> float | None:
    """0 より大きい数ならその値を、そうでなければ None を返す。"""
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    return float(value)


def _parse_display(raw: object) -> Display:
    """osascript の返事の1件を、形を検査して `Display` にする。"""
    if not isinstance(raw, dict):
        raise OsascriptError(f"画面の一覧の形が読めない: {raw!r}")
    display_id = raw.get("id")
    name = raw.get("name")
    current_image = raw.get("current_image")
    frame_width = _positive_number(raw.get("frame_width"))
    frame_height = _positive_number(raw.get("frame_height"))
    scale = _positive_number(raw.get("scale"))
    if (
        not isinstance(display_id, int)
        or isinstance(display_id, bool)
        or not isinstance(name, str)
        or not (current_image is None or isinstance(current_image, str))
        or frame_width is None
        or frame_height is None
        or scale is None
    ):
        raise OsascriptError(f"画面の一覧の形が読めない: {raw!r}")
    return Display(
        display_id=display_id,
        name=name,
        # frame はポイント、scale は1ポイントあたりのピクセル。掛けると物理ピクセルになる
        width=round(frame_width * scale),
        height=round(frame_height * scale),
        scale=scale,
        current_image=current_image,
        current_image_known=raw.get("current_image_known", True) is not False,
    )


def list_displays() -> list[Display]:
    """接続中のディスプレイを、NSScreen の並びの順に返す。設定は読むだけで、変えない。

    Raises:
        OsascriptError: osascript が失敗した、または返事が読めなかった。
    """
    output = _run_jxa(_LIST_DISPLAYS_SCRIPT)
    try:
        loaded = json.loads(output)
    except json.JSONDecodeError as error:
        raise OsascriptError(f"画面の一覧が JSON として読めない: {output[:200]!r}") from error
    if not isinstance(loaded, list):
        raise OsascriptError(f"画面の一覧の形が読めない: {output[:200]!r}")
    return [_parse_display(raw) for raw in loaded]


def set_desktop_image(display_id: int, image_path: Path) -> None:
    """番号で選んだ画面に、画像を壁紙として設定する（NSWorkspace の setDesktopImageURL:forScreen:options:error:）。

    その画面で、いま表示している Space の壁紙だけが変わる。
    拡大の方法と余白の色は、その画面のいまの設定を引き継ぐ。

    Raises:
        OsascriptError: 画面が見つからない、設定に失敗した、osascript が失敗した。
    """
    _run_jxa(_SET_DESKTOP_IMAGE_SCRIPT, str(display_id), str(image_path))
