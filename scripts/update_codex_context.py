"""Regenerate CODEX_CONTEXT.md from the repository's current automation files."""

from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_PATH = ROOT / "CODEX_CONTEXT.md"
SECTOR_SCRIPT = ROOT / "sector_ranking" / "make_sector_ranking.py"
SECTOR_WORKFLOW = ROOT / ".github" / "workflows" / "sector_ranking.yml"
UPDATE_WORKFLOW = ROOT / ".github" / "workflows" / "update.yml"
PTS_WORKFLOW = ROOT / ".github" / "workflows" / "pts_daily.yml"
REQUIREMENTS = ROOT / "sector_ranking" / "requirements.txt"
POSTER = ROOT / "sector_ranking" / "x_poster.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_crons(workflow: str) -> list[str]:
    return re.findall(r"cron:\s*['\"]([^'\"]+)['\"]", workflow)


def extract_python_version(workflow: str) -> str:
    match = re.search(r"python-version:\s*['\"]?([^'\"\n]+)", workflow)
    return match.group(1).strip() if match else "未指定"


def extract_topix17() -> dict[str, str]:
    source = read(SECTOR_SCRIPT)
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "TOPIX17_ETFS":
                    value = ast.literal_eval(node.value)
                    return dict(value)
    return {}


def extract_parser_flags() -> list[str]:
    source = read(SECTOR_SCRIPT)
    flags = re.findall(r"add_argument\(\s*['\"](--[^'\"]+)['\"]", source)
    return flags


def code_block(path: Path, language: str = "") -> str:
    return f"```{language}\n{read(path).rstrip()}\n```"


def build_context() -> str:
    sector_workflow = read(SECTOR_WORKFLOW)
    update_workflow = read(UPDATE_WORKFLOW)
    pts_workflow = read(PTS_WORKFLOW)
    requirements = read(REQUIREMENTS).strip().splitlines()
    topix17 = extract_topix17()
    flags = extract_parser_flags()

    sector_crons = ", ".join(extract_crons(sector_workflow)) or "なし"
    update_crons = ", ".join(extract_crons(update_workflow)) or "なし"
    pts_crons = ", ".join(extract_crons(pts_workflow)) or "なし"
    python_version = extract_python_version(sector_workflow)

    topix_lines = []
    items = list(topix17.items())
    for i in range(0, len(items), 3):
        chunk = items[i:i + 3]
        topix_lines.append("    ".join(f"{code}: {name}" for code, name in chunk))

    return f"""# 業種別騰落率ランキング 自動ツイート — Codex Context

> このファイルは `scripts/update_codex_context.py` で自動生成しています。
> 恒久的に残したい変更は、本文を直接編集せず生成スクリプトに反映してください。

## 目的

このリポジトリは、決算カレンダーの自動更新に加えて、毎平日 15:30 JST に
「業種別騰落率ランキング」画像を X に自動投稿する仕組みを管理する。

## 経緯

> PTSを自動化のセッションで自動化した

PTS値上がりランキングの自動保存を先に整備し、その流れに続けて
業種別騰落率ランキングの自動投稿と、この `CODEX_CONTEXT.md` の自動更新を追加した。

## 現在の自動化

| 自動化 | ファイル | スケジュール |
|---|---|---|
| 決算カレンダー更新 | `.github/workflows/update.yml` | `{update_crons}` |
| PTS値上がりランキング保存 | `.github/workflows/pts_daily.yml` | `{pts_crons}` |
| 業種別騰落率ランキング投稿 | `.github/workflows/sector_ranking.yml` | `{sector_crons}` |
| Codex Context 再生成 | `.github/workflows/codex_context.yml` | workflow変更・関連スクリプト変更・手動実行 |

## 業種別ランキングの設計

- 実行環境: GitHub Actions / Python {python_version}
- データ取得: `yfinance` で TOPIX-17 業種 ETF の直近2営業日 Close から前日比を計算
- 画像生成: `Pillow` のみで横棒グラフを生成
- 投稿: `tweepy` で画像付きツイート
- 日本市場の休場日: `jpholiday` で土日祝をスキップ
- 生成物: `sector_ranking/output/` に画像とツイート本文を保存し、Actions Artifact に残す

## コマンドライン引数

```bash
python3 sector_ranking/make_sector_ranking.py
{chr(10).join(f'python3 sector_ranking/make_sector_ranking.py {flag}' for flag in flags)}
```

## 必要な GitHub Secrets

| Secret 名 | 用途 |
|---|---|
| `X_API_KEY` | X API Key |
| `X_API_SECRET` | X API Key Secret |
| `X_ACCESS_TOKEN` | X Access Token |
| `X_ACCESS_TOKEN_SECRET` | X Access Token Secret |

## 依存パッケージ

```txt
{chr(10).join(requirements)}
```

## TOPIX-17 業種 ETF

```txt
{chr(10).join(topix_lines)}
```

## 主要ファイル

```txt
sector-ranking-gh/
├── CODEX_CONTEXT.md
├── scripts/
│   └── update_codex_context.py
├── .github/workflows/
│   ├── update.yml
│   ├── pts_daily.yml
│   ├── sector_ranking.yml
│   └── codex_context.yml
└── sector_ranking/
    ├── make_sector_ranking.py
    ├── x_poster.py
    ├── requirements.txt
    └── output/
```

## ワークフロー定義

### `.github/workflows/sector_ranking.yml`

{code_block(SECTOR_WORKFLOW, "yaml")}

### `sector_ranking/requirements.txt`

{code_block(REQUIREMENTS, "txt")}

### `sector_ranking/x_poster.py`

{code_block(POSTER, "python")}

## 運用メモ

- Mac の launchd 常駐より GitHub Actions を優先する。Mac がスリープ中でも実行できるため。
- 既存の Mac 側 `x-stock-bot` は二重投稿防止のため停止済み。
- `sector_ranking/output/` は `.gitignore` 済み。生成画像はリポジトリには残さず Artifact で確認する。
- `CODEX_CONTEXT.md` を手で直した場合は、次回の自動生成で上書きされる。恒久的に残したい内容はこのスクリプトに反映する。
"""


def main() -> None:
    CONTEXT_PATH.write_text(build_context(), encoding="utf-8")
    print(f"updated {CONTEXT_PATH}")


if __name__ == "__main__":
    main()
