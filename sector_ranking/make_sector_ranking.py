"""業種別騰落率ランキング 自動ツイート（GitHub Actions 用）

毎日大引け後（15:30 JST = 06:30 UTC）に GitHub Actions から実行：
1. yfinance で TOPIX-17 業種 ETF の前日比を取得
2. インパクト重視の横棒グラフ画像を生成（Pillow）
3. 画像付きツイート投稿

使い方:
    python3 make_sector_ranking.py              # 画像生成＋ツイート
    python3 make_sector_ranking.py --image-only # 画像生成のみ
    python3 make_sector_ranking.py --draft      # 画像＋本文を保存（投稿なし）
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from x_poster import post_tweet_with_image

OUTPUT_DIR = Path(__file__).parent / "output"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


# =========================================
# 1. データ取得（yfinance + TOPIX-17 ETF）
# =========================================
TOPIX17_ETFS = {
    "1617.T": "食品",
    "1618.T": "エネルギー資源",
    "1619.T": "建設・資材",
    "1620.T": "素材・化学",
    "1621.T": "医薬品",
    "1622.T": "自動車・輸送機",
    "1623.T": "鉄鋼・非鉄",
    "1624.T": "機械",
    "1625.T": "電機・精密",
    "1626.T": "情報通信・サービス",
    "1627.T": "電力・ガス",
    "1628.T": "運輸・物流",
    "1629.T": "商社・卸売",
    "1630.T": "小売",
    "1631.T": "銀行",
    "1632.T": "金融（除く銀行）",
    "1633.T": "不動産",
}


def fetch_sector_data():
    import yfinance as yf

    data = []
    for code, name in TOPIX17_ETFS.items():
        try:
            t = yf.Ticker(code)
            h = t.history(period="5d", auto_adjust=False)
            if len(h) >= 2:
                pct = (h["Close"].iloc[-1] / h["Close"].iloc[-2] - 1) * 100
                data.append((name, float(pct)))
                logging.info(f"  {name}: {pct:+.2f}%")
            else:
                logging.warning(f"  {name}({code}): データ不足")
        except Exception as e:
            logging.warning(f"  {name}({code}): 取得失敗 {e}")

    if not data:
        raise RuntimeError("業種データを取得できませんでした")
    data.sort(key=lambda x: -x[1])
    return data


# =========================================
# 2. 画像生成（Pillow）
# =========================================
# OS判定でフォントパスを切り替え
if sys.platform == "darwin":
    FONT_REG = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
    FONT_BOLD = "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc"
else:
    # Ubuntu (GitHub Actions) — fonts-noto-cjk
    FONT_REG = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
    FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"


def _font(size, bold=False):
    path = FONT_BOLD if bold else FONT_REG
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        # フォールバック
        for p in [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        ]:
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
        return ImageFont.load_default()


def _grad(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _draw_chart_up(d, cx, cy, size=35, color="#27ae60"):
    pts = [(cx - size, cy + size // 2), (cx - size // 3, cy),
           (cx + size // 4, cy + size // 4), (cx + size, cy - size // 2)]
    for i in range(len(pts) - 1):
        d.line([pts[i], pts[i + 1]], fill=color, width=5)
    d.polygon([(cx + size, cy - size // 2),
               (cx + size - 12, cy - size // 2 - 3),
               (cx + size - 8, cy - size // 2 + 10)], fill=color)
    for p in pts:
        d.ellipse([p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4], fill=color)


def _draw_chart_down(d, cx, cy, size=35, color="#e74c3c"):
    pts = [(cx - size, cy - size // 2), (cx - size // 3, cy),
           (cx + size // 4, cy - size // 4), (cx + size, cy + size // 2)]
    for i in range(len(pts) - 1):
        d.line([pts[i], pts[i + 1]], fill=color, width=5)
    d.polygon([(cx + size, cy + size // 2),
               (cx + size - 12, cy + size // 2 + 3),
               (cx + size - 8, cy + size // 2 - 10)], fill=color)
    for p in pts:
        d.ellipse([p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4], fill=color)


def generate_image(data, date_str, out_path):
    W = 1000
    ROW_H = 34
    TOP_PAD = 200
    BOTTOM_PAD = 110
    H = TOP_PAD + ROW_H * len(data) + BOTTOM_PAD

    LABEL_W = 250
    CENTER_X = LABEL_W + 230
    BAR_RIGHT = W - 60
    NEG_LEFT = LABEL_W + 40

    max_abs = max(7.0, max(abs(v) for _, v in data) * 1.05)
    pos_ppp = (BAR_RIGHT - CENTER_X) / max_abs
    neg_ppp = (CENTER_X - NEG_LEFT) / max_abs

    img = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(img)

    for x in range(W):
        t = x / W
        d.line([(x, 0), (x, 12)],
               fill=(int(255 - 12 * t), int(220 - 64 * t), int(50 + 25 * t)))
        d.line([(x, H - 8), (x, H)],
               fill=(int(243 + 12 * t), int(156 + 64 * t), int(75 - 25 * t)))

    d.ellipse([-60, -60, 80, 80], fill="#fef5e7")
    d.ellipse([W - 80, -60, W + 60, 80], fill="#fdebd0")
    d.ellipse([-40, H - 40, 80, H + 60], fill="#fef9e7")
    d.ellipse([W - 80, H - 40, W + 40, H + 60], fill="#fef5e7")

    _draw_chart_up(d, 110, 70, 35, "#27ae60")
    _draw_chart_down(d, W - 110, 70, 35, "#e74c3c")
    d.text((W // 2, 60), "業種別 騰落率ランキング",
           font=_font(42, bold=True), fill="#222222", anchor="mm")
    d.rectangle([W // 2 - 220, 90, W // 2 + 220, 96], fill="#f39c12")

    d.rounded_rectangle([W // 2 - 200, 110, W // 2 + 200, 148],
                        radius=18, fill="#34495e")
    d.text((W // 2, 129),
           f"{date_str} 大引け  ／  TOPIX-17業種",
           font=_font(20, bold=True), fill="#ffffff", anchor="mm")

    for cx in (40, W - 40):
        d.ellipse([cx - 16, 165 - 16, cx + 16, 165 + 16], fill="#f1c40f")
        d.text((cx, 166), "¥", font=_font(20, bold=True), fill="#ffffff", anchor="mm")

    grid_top = TOP_PAD - 5
    grid_bottom = H - BOTTOM_PAD + 5
    step = 2 if max_abs <= 8 else 4
    pct = -int(max_abs)
    while pct <= int(max_abs):
        if pct == 0:
            pct += step
            continue
        x = CENTER_X + pct * (pos_ppp if pct > 0 else neg_ppp)
        if NEG_LEFT - 5 < x < BAR_RIGHT + 5:
            d.line([(x, grid_top), (x, grid_bottom)], fill="#ecf0f1", width=1)
            d.text((x, grid_bottom + 18), f"{pct:+d}%",
                   font=_font(12), fill="#95a5a6", anchor="mm")
        pct += step
    d.line([(CENTER_X, grid_top), (CENTER_X, grid_bottom)],
           fill="#7f8c8d", width=2)
    d.text((CENTER_X, grid_bottom + 18), "0%",
           font=_font(12), fill="#2c3e50", anchor="mm")

    GREEN_TOP = (39, 220, 110)
    GREEN_MID = (39, 174, 96)
    RED_TOP = (231, 76, 60)
    RED_BOTTOM = (192, 57, 43)
    medals = {0: "#FFD700", 1: "#C0C0C0", 2: "#CD7F32"}

    for i, (name, val) in enumerate(data):
        y = TOP_PAD + i * ROW_H
        cy = y + ROW_H // 2

        if i < 3:
            d.rectangle([20, y + 2, W - 20, y + ROW_H - 2], fill="#eafaf1")
        elif i >= len(data) - 3:
            d.rectangle([20, y + 2, W - 20, y + ROW_H - 2], fill="#fdedec")
        elif i % 2 == 0:
            d.rectangle([20, y + 2, W - 20, y + ROW_H - 2], fill="#f8f9fa")

        if i < 3:
            bg, fg = medals[i], "#ffffff"
        elif i >= len(data) - 3:
            bg, fg = "#c0392b", "#ffffff"
        else:
            bg, fg = "#bdc3c7", "#ffffff"
        d.ellipse([50 - 14, cy - 14, 50 + 14, cy + 14], fill=bg)
        d.text((50, cy), str(i + 1), font=_font(18, bold=True), fill=fg, anchor="mm")

        d.text((90, cy), name, font=_font(17, bold=True), fill="#2c3e50", anchor="lm")

        ax = LABEL_W + 5
        if val >= 0:
            d.polygon([(ax, cy + 4), (ax + 10, cy + 4), (ax + 5, cy - 6)], fill="#27ae60")
        else:
            d.polygon([(ax, cy - 4), (ax + 10, cy - 4), (ax + 5, cy + 6)], fill="#e74c3c")

        bar_h = 22
        if val >= 0:
            color = _grad(GREEN_TOP, GREEN_MID, min(i / 15, 1))
            bw = val * pos_ppp
            d.rounded_rectangle([CENTER_X, cy - bar_h // 2, CENTER_X + bw, cy + bar_h // 2],
                                radius=4, fill=color)
            d.text((CENTER_X + bw + 10, cy), f"+{val:.2f}%",
                   font=_font(17, bold=True), fill="#1e8449", anchor="lm")
        else:
            color = _grad(RED_BOTTOM, RED_TOP, min((len(data) - 1 - i) / 17, 1))
            bw = abs(val) * neg_ppp
            d.rounded_rectangle([CENTER_X - bw, cy - bar_h // 2, CENTER_X, cy + bar_h // 2],
                                radius=4, fill=color)
            d.text((CENTER_X - bw - 10, cy), f"{val:.2f}%",
                   font=_font(17, bold=True), fill="#a93226", anchor="rm")

    fy = H - 80
    card_w = (W - 80) // 2
    best_name, best_val = data[0]
    worst_name, worst_val = data[-1]

    d.rounded_rectangle([30, fy, 30 + card_w, fy + 60],
                        radius=12, fill="#27ae60", outline="#1e8449", width=2)
    _draw_chart_up(d, 65, fy + 30, 18, "#ffffff")
    d.text((100, fy + 18), "BEST", font=_font(14, bold=True), fill="#ffffff", anchor="lm")
    d.text((100, fy + 42), best_name, font=_font(18, bold=True), fill="#ffffff", anchor="lm")
    d.text((30 + card_w - 20, fy + 30), f"+{best_val:.2f}%",
           font=_font(28, bold=True), fill="#ffffff", anchor="rm")

    d.rounded_rectangle([W - 30 - card_w, fy, W - 30, fy + 60],
                        radius=12, fill="#e74c3c", outline="#a93226", width=2)
    _draw_chart_down(d, W - 30 - card_w + 35, fy + 30, 18, "#ffffff")
    d.text((W - 30 - card_w + 70, fy + 18), "WORST",
           font=_font(14, bold=True), fill="#ffffff", anchor="lm")
    d.text((W - 30 - card_w + 70, fy + 42), worst_name,
           font=_font(18, bold=True), fill="#ffffff", anchor="lm")
    d.text((W - 50, fy + 30), f"{worst_val:.2f}%",
           font=_font(28, bold=True), fill="#ffffff", anchor="rm")

    img.save(out_path)
    logging.info(f"画像保存: {out_path}")


# =========================================
# 3. ツイート本文
# =========================================
def build_tweet_text(data, date_str):
    top3 = data[:3]
    bottom3 = data[-3:]
    lines = [
        f"📊 業種別騰落率ランキング（{date_str} 大引け）",
        "",
        "🔥 上昇トップ3",
    ]
    for i, (name, v) in enumerate(top3, 1):
        lines.append(f"{i}. {name} +{v:.2f}%")
    lines.append("")
    lines.append("📉 下落トップ3")
    for i, (name, v) in enumerate(bottom3, len(data) - 2):
        lines.append(f"{i}. {name} {v:.2f}%")
    lines.append("")
    lines.append("#日本株 #業種別 #TOPIX")
    return "\n".join(lines)


# =========================================
# 4. メイン
# =========================================
def is_jp_holiday():
    """日本の祝日（土日含む）なら True"""
    try:
        import jpholiday
        jst = timezone(timedelta(hours=9))
        today = datetime.now(jst).date()
        if today.weekday() >= 5:
            return True, "週末"
        if jpholiday.is_holiday(today):
            return True, jpholiday.is_holiday_name(today)
    except Exception:
        pass
    return False, ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-only", action="store_true")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--force", action="store_true", help="休場日でも実行")
    args = parser.parse_args()

    # 休場日チェック
    is_holiday, hname = is_jp_holiday()
    if is_holiday and not args.force:
        logging.info(f"休場日のためスキップ: {hname}")
        return

    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst)
    date_str = today.strftime("%Y年%m月%d日")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logging.info(f"=== 業種別ランキング 開始: {date_str} ===")

    data = fetch_sector_data()

    image_path = OUTPUT_DIR / f"sector_{today.strftime('%Y-%m-%d')}.png"
    generate_image(data, date_str, image_path)

    text = build_tweet_text(data, date_str)
    (OUTPUT_DIR / f"tweet_{today.strftime('%Y-%m-%d')}.txt").write_text(text, encoding="utf-8")

    if args.image_only:
        print(f"画像生成: {image_path}")
        return
    if args.draft:
        print(text)
        return

    ok = post_tweet_with_image(text, str(image_path))
    logging.info("投稿成功" if ok else "重複スキップ")


if __name__ == "__main__":
    main()
