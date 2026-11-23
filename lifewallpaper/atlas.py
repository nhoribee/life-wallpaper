"""設定の一覧のページ。`config/*.json` を、ひな型の HTML に埋め込んで書き出す。

`file://` で開いたページは、手元の JSON を fetch で読めない。
そのため、設定のデータをページの中に埋め込む。設定を足したり変えたりしたら、作り直す。
"""

import json
import re
from pathlib import Path

BEGIN = "// CONFIGS:BEGIN (run.sh atlas がここに config/*.json を埋め込む。手で書き換えない)"
END = "// CONFIGS:END"


class AtlasError(RuntimeError):
    """ひな型に、設定を埋め込む目印が無い。"""


def collect_configs(config_dir: Path) -> list[dict[str, object]]:
    """ライフゲームの設定を、ファイル名の順に集める。各設定に、ファイル名を `_file` として足す。

    1次元のセルオートマトンの設定（`eca*.json`）は、一覧のページの対象でないので除く。
    """
    configs: list[dict[str, object]] = []
    for path in sorted(config_dir.glob("*.json")):
        if path.name.startswith("eca"):
            continue
        config = json.loads(path.read_text(encoding="utf-8"))
        config["_file"] = path.name
        configs.append(config)
    return configs


def build_atlas(config_dir: Path, template_path: Path, output_path: Path) -> int:
    """ひな型に設定を埋め込んだページを書き出し、埋め込んだ設定の数を返す。

    Args:
        config_dir: 設定の JSON があるフォルダ。
        template_path: ひな型の HTML。目印（`CONFIGS:BEGIN` と `CONFIGS:END`）のあいだを差し替える。
        output_path: 書き出すページのパス。フォルダが無ければ作る。

    Raises:
        AtlasError: ひな型に目印が無い。
    """
    configs = collect_configs(config_dir)
    # 設定の文字列に `</script>` や `<!--` があっても、ページの script を壊さないようにする
    blob = json.dumps(configs, ensure_ascii=False, indent=2).replace("<", "\\u003c")
    template = template_path.read_text(encoding="utf-8")
    marked = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    if not marked.search(template):
        raise AtlasError(
            f"ひな型に、設定を埋め込む目印（CONFIGS:BEGIN と CONFIGS:END）が無い: {template_path}"
        )
    # 差し替える文に `\` が入っても、置き換えの記法として読まれないよう、関数で渡す
    page = marked.sub(lambda _: f"{BEGIN}\nconst CONFIGS = {blob};\n{END}", template)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    return len(configs)
