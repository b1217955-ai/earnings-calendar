# 業種別騰落率ランキング 自動ツイート — Codex Context

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
| 決算カレンダー更新 | `.github/workflows/update.yml` | `0 9,21 * * *` |
| PTS値上がりランキング保存 | `.github/workflows/pts_daily.yml` | `30 21 * * *` |
| 業種別騰落率ランキング投稿 | `.github/workflows/sector_ranking.yml` | `30 6 * * 1-5` |
| Codex Context 再生成 | `.github/workflows/codex_context.yml` | workflow変更・関連スクリプト変更・手動実行 |

## 業種別ランキングの設計

- 実行環境: GitHub Actions / Python 3.11
- データ取得: 主要株式指標ページから東証33業種の前日比を取得
- 画像生成: `Pillow` のみで横棒グラフを生成
- 投稿: `tweepy` で画像付きツイート
- 日本市場の休場日: `jpholiday` で土日祝をスキップ
- 生成物: `sector_ranking/output/` に画像とツイート本文を保存し、Actions Artifact に残す

## コマンドライン引数

```bash
python3 sector_ranking/make_sector_ranking.py
python3 sector_ranking/make_sector_ranking.py --image-only
python3 sector_ranking/make_sector_ranking.py --draft
python3 sector_ranking/make_sector_ranking.py --force
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
tweepy>=4.14.0
Pillow>=10.0.0
jpholiday>=0.1.10
```

## 東証33業種

```txt
01. 水産・農林業    02. 鉱業    03. 建設業
04. 食料品    05. 繊維製品    06. パルプ・紙
07. 化学    08. 医薬品    09. 石油・石炭製品
10. ゴム製品    11. ガラス・土石製品    12. 鉄鋼
13. 非鉄金属    14. 金属製品    15. 機械
16. 電気機器    17. 輸送用機器    18. 精密機器
19. その他製品    20. 電気・ガス業    21. 陸運業
22. 海運業    23. 空運業    24. 倉庫・運輸関連業
25. 情報・通信業    26. 卸売業    27. 小売業
28. 銀行業    29. 証券、商品先物取引業    30. 保険業
31. その他金融業    32. 不動産業    33. サービス業
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

```yaml
name: 業種別騰落率ランキング 自動ツイート

on:
  schedule:
    # 平日 06:30 UTC = 15:30 JST（大引け30分後）
    - cron: '30 6 * * 1-5'
  workflow_dispatch:

jobs:
  post:
    runs-on: ubuntu-latest
    steps:
      - name: リポジトリ取得
        uses: actions/checkout@v4

      - name: Python セットアップ
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: pip
          cache-dependency-path: sector_ranking/requirements.txt

      - name: 日本語フォントをインストール
        run: sudo apt-get update && sudo apt-get install -y fonts-noto-cjk

      - name: 依存パッケージをインストール
        run: pip install -r sector_ranking/requirements.txt

      - name: 業種別ランキングを実行
        working-directory: sector_ranking
        env:
          X_API_KEY: ${{ secrets.X_API_KEY }}
          X_API_SECRET: ${{ secrets.X_API_SECRET }}
          X_ACCESS_TOKEN: ${{ secrets.X_ACCESS_TOKEN }}
          X_ACCESS_TOKEN_SECRET: ${{ secrets.X_ACCESS_TOKEN_SECRET }}
        run: python3 make_sector_ranking.py

      - name: 画像を Artifact にアップロード
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: sector-ranking-${{ github.run_id }}
          path: sector_ranking/output/
          retention-days: 30
```

### `sector_ranking/requirements.txt`

```txt
tweepy>=4.14.0
Pillow>=10.0.0
jpholiday>=0.1.10
```

### `sector_ranking/x_poster.py`

```python
"""X（Twitter）画像付き投稿モジュール（GitHub Actions 用）"""
import os
import logging

import tweepy


def _get_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def _get_api_v1() -> tweepy.API:
    auth = tweepy.OAuth1UserHandler(
        os.environ["X_API_KEY"],
        os.environ["X_API_SECRET"],
        os.environ["X_ACCESS_TOKEN"],
        os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    return tweepy.API(auth)


def post_tweet_with_image(text: str, image_path: str) -> bool:
    """画像付き1ツイート。成功 True、重複 False。"""
    api_v1 = _get_api_v1()
    client = _get_client()
    try:
        media = api_v1.media_upload(filename=image_path)
        response = client.create_tweet(text=text, media_ids=[media.media_id])
        logging.info(f"投稿完了 tweet_id={response.data['id']}")
        return True
    except tweepy.errors.Forbidden as e:
        if "duplicate" in str(e).lower():
            logging.warning("重複スキップ")
            return False
        raise
```

## 運用メモ

- Mac の launchd 常駐より GitHub Actions を優先する。Mac がスリープ中でも実行できるため。
- 既存の Mac 側 `x-stock-bot` は二重投稿防止のため停止済み。
- `sector_ranking/output/` は `.gitignore` 済み。生成画像はリポジトリには残さず Artifact で確認する。
- `CODEX_CONTEXT.md` を手で直した場合は、次回の自動生成で上書きされる。恒久的に残したい内容はこのスクリプトに反映する。
