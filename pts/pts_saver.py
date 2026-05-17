import os
import re
import sys
import platform
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pytz
from PIL import Image, ImageDraw, ImageFont

JST = pytz.timezone("Asia/Tokyo")
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

if platform.system() == "Darwin":
    FONT_BOLD = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
    FONT_REG  = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
    SAVE_DIR  = os.path.expanduser(
        "~/Library/Mobile Documents/com~apple~CloudDocs/PTS"
    )
else:
    FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
    FONT_REG  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    SAVE_DIR  = os.path.join(os.path.dirname(__file__), "output")


def fetch_pts_ranking(top_n: int = 10) -> list:
    url = "https://kabutan.jp/warning/pts_night_price_increase"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        table = None
        for t in soup.find_all("table"):
            if t.find("th", {"scope": "row"}):
                table = t
                break
        if not table:
            return []
        result = []
        for row in table.find_all("tr"):
            code_td = row.find("td", class_="tac")
            if not code_td:
                continue
            code = code_td.get_text(strip=True)
            name_th = row.find("th", {"scope": "row"})
            name = name_th.get_text(strip=True) if name_th else ""
            tds = row.find_all("td")
            price = tds[4].get_text(strip=True) + "円" if len(tds) > 4 else ""
            pct = ""
            if len(tds) > 7:
                span = tds[7].find("span")
                val = span.get_text(strip=True) if span else tds[7].get_text(strip=True).replace("%", "")
                if val:
                    if not val.startswith(("+", "-")):
                        val = "+" + val
                    pct = val + "%"
            if not code:
                continue
            result.append({"name": name, "code": code, "pct": pct, "price": price})
            if len(result) >= top_n:
                break
        return result
    except Exception as e:
        print(f"スクレイピング失敗: {e}", file=sys.stderr)
        return []


def save_text(ranking: list, date_str: str, fetch_time: str, out_path: str) -> None:
    lines = [
        f"PTS値上がりランキング（{date_str} 夜）",
        "=" * 44,
    ]
    for i, r in enumerate(ranking, 1):
        lines.append(
            f"{i:2}位  {r['name']:<16} ({r['code']})  {r['pct']:>8}  {r['price']}"
        )
    lines += ["", f"取得時刻: {fetch_time}"]
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def save_image(ranking: list, date_str: str, out_path: str) -> None:
    W = 640
    ROW_H = 64
    HEADER_H = 120
    IMG_H = HEADER_H + ROW_H * len(ranking) + 40
    BG_TOP = (8, 28, 72)
    BG_BOT = (12, 40, 100)
    ACCENT = (30, 100, 200)
    WHITE = (255, 255, 255)
    LIGHT = (180, 200, 230)
    RED = (255, 60, 80)
    ROW_ODD = (14, 35, 85)
    ROW_EVN = (10, 25, 65)
    GOLD = (255, 200, 50)

    img = Image.new("RGB", (W, IMG_H), BG_TOP)
    draw = ImageDraw.Draw(img)

    for y in range(IMG_H):
        t = y / IMG_H
        r = int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    try:
        font_title = ImageFont.truetype(FONT_BOLD, 32)
        font_date  = ImageFont.truetype(FONT_REG,  18)
        font_name  = ImageFont.truetype(FONT_REG,  18)
        font_code  = ImageFont.truetype(FONT_REG,  13)
        font_pct   = ImageFont.truetype(FONT_BOLD, 22)
        font_rank  = ImageFont.truetype(FONT_BOLD, 20)
    except Exception:
        font_title = font_date = font_name = font_code = font_pct = font_rank = ImageFont.load_default()

    title = "PTS 値上がり率ランキング"
    bbox = draw.textbbox((0, 0), title, font=font_title)
    draw.text(((W - (bbox[2] - bbox[0])) // 2, 18), title, font=font_title, fill=WHITE)

    dbbox = draw.textbbox((0, 0), date_str, font=font_date)
    draw.text(((W - (dbbox[2] - dbbox[0])) // 2, 68), date_str, font=font_date, fill=LIGHT)

    draw.rectangle([(40, 104), (W - 40, 106)], fill=ACCENT)

    COL_RANK = 20
    COL_NAME = 68
    COL_PCT  = 420
    COL_PRC  = 530

    for i, r in enumerate(ranking):
        y = HEADER_H + i * ROW_H
        draw.rectangle([(0, y), (W, y + ROW_H)], fill=ROW_ODD if i % 2 == 0 else ROW_EVN)
        draw.line([(40, y + ROW_H - 1), (W - 40, y + ROW_H - 1)], fill=(30, 60, 110))
        cy = y + ROW_H // 2
        draw.text((COL_RANK, cy - 12), f"{i+1}", font=font_rank, fill=GOLD if i == 0 else (200, 210, 255))
        name = r["name"][:9] + "…" if len(r["name"]) > 10 else r["name"]
        draw.text((COL_NAME, cy - 14), name, font=font_name, fill=WHITE)
        draw.text((COL_NAME, cy + 6), r["code"], font=font_code, fill=LIGHT)
        draw.text((COL_PCT, cy - 14), r.get("pct", ""), font=font_pct, fill=RED)
        draw.text((COL_PRC, cy - 10), r.get("price", ""), font=font_code, fill=LIGHT)

    draw.rectangle([(0, IMG_H - 32), (W, IMG_H)], fill=(6, 18, 50))
    draw.text((20, IMG_H - 24), "※出来高1,000株未満は除外  ※S高は前日終値ベース参考値", font=font_code, fill=(120, 140, 180))

    img.save(out_path)


def main() -> None:
    now = datetime.now(JST)
    prev = now - timedelta(days=1)
    date_str = prev.strftime("%Y年%m月%d日")
    file_date = prev.strftime("%Y-%m-%d")
    fetch_time = now.strftime("%Y-%m-%d %H:%M")

    os.makedirs(SAVE_DIR, exist_ok=True)

    print(f"PTSランキング取得中... ({date_str} 夜)")
    ranking = fetch_pts_ranking(top_n=10)

    if not ranking:
        print("データ取得失敗。終了します。", file=sys.stderr)
        sys.exit(1)

    print(f"{len(ranking)}件取得")

    txt_path = os.path.join(SAVE_DIR, f"{file_date}.txt")
    img_path = os.path.join(SAVE_DIR, f"{file_date}.png")

    save_text(ranking, date_str, fetch_time, txt_path)
    print(f"テキスト保存: {txt_path}")

    save_image(ranking, date_str, img_path)
    print(f"画像保存:     {img_path}")


if __name__ == "__main__":
    main()
