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
KABUTAN_BASE = "https://kabutan.jp"
LOCAL_ICLOUD_PTS_DIR = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs/AI Codex/自動化出力/PTS"
)

if platform.system() == "Darwin":
    FONT_BOLD = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
    FONT_REG  = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
    SAVE_DIR  = os.environ.get("PTS_OUTPUT_DIR", LOCAL_ICLOUD_PTS_DIR)
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


SKIP_REASON_WORDS = [
        "ＭＡＣＤ",
        "MACD",
        "ゴールデンクロス",
        "デッドクロス",
        "ボリンジャー",
        "均衡表",
        "前日に動いた銘柄",
        "ストップ高",
        "上場来高値銘柄",
]
REASON_WORDS = [
        "決算",
        "上方修正",
        "下方修正",
        "最高益",
        "増益",
        "増配",
        "黒字",
        "営業利益",
        "経常",
        "純利益",
        "配当",
        "自社株",
        "新製品",
        "提携",
        "受注",
        "承認",
        "イチオシ",
        "サプライズ",
]
STRONG_REASON_WORDS = [
    "上方修正",
    "最高益",
    "増益",
    "増配",
    "黒字",
    "営業利益",
    "経常",
    "純利益",
    "配当",
    "自社株",
    "提携",
    "受注",
    "承認",
]
GENERIC_REASON_WORDS = ["イチオシ", "サプライズ", "成長企業"]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


def looks_like_reason_headline(title: str) -> bool:
    if any(word in title for word in SKIP_REASON_WORDS):
        return False
    return any(word in title for word in REASON_WORDS)


def reason_score(title: str, name: str) -> int:
    score = 0
    norm_title = normalize_text(title)
    norm_name = normalize_text(name)
    if norm_name and norm_name in norm_title:
        score += 8
    score += sum(2 for word in STRONG_REASON_WORDS if word in title)
    score += sum(1 for word in REASON_WORDS if word in title)
    score -= sum(2 for word in GENERIC_REASON_WORDS if word in title)
    return score


def fetch_reason(code: str, name: str = "") -> dict:
    url = f"{KABUTAN_BASE}/stock/news?code={code}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        fallback = ""
        candidates = []
        for a in soup.select('a[href*="/stock/news?code="]'):
            title = a.get_text(" ", strip=True)
            href = a.get("href", "")
            if not title or f"code={code}" not in href or "&b=" not in href:
                continue
            if not fallback:
                fallback = title
            if looks_like_reason_headline(title):
                candidates.append({
                    "title": title,
                    "url": KABUTAN_BASE + href,
                    "score": reason_score(title, name),
                })
        if candidates:
            best = sorted(candidates, key=lambda x: x["score"], reverse=True)[0]
            return {"title": best["title"], "url": best["url"]}
        if fallback:
            return {"title": fallback, "url": url}
    except Exception as e:
        print(f"材料候補取得失敗 ({code}): {e}", file=sys.stderr)
    return {"title": "関連ニュース見出しを確認できませんでした", "url": url}


def add_top_reasons(ranking: list, top_n: int = 3) -> None:
    for item in ranking[:top_n]:
        item["reason"] = fetch_reason(item["code"], item["name"])


def save_text(ranking: list, date_str: str, fetch_time: str, out_path: str) -> None:
    lines = [
        f"🚀 PTS値上がりランキング（{date_str} 夜）",
        "=" * 44,
    ]
    icons = ["🏆", "🥈", "🥉"]
    for i, r in enumerate(ranking, 1):
        icon = icons[i - 1] if i <= 3 else "🔥"
        lines.append(
            f"{icon} {i:2}位  {r['name']:<16} ({r['code']})  {r['pct']:>8}  {r['price']}"
        )
    lines += ["", "📝 上位3銘柄の材料候補（株探ニュース見出しベース）"]
    for i, r in enumerate(ranking[:3], 1):
        reason = r.get("reason") or {}
        title = reason.get("title", "関連ニュース見出しを確認できませんでした")
        url = reason.get("url", f"{KABUTAN_BASE}/stock/news?code={r['code']}")
        lines.append(f"{i}. {r['name']}（{r['code']}）: {title}")
        lines.append(f"   参考: {url}")
    lines += ["", f"取得時刻: {fetch_time}"]
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def save_image(ranking: list, date_str: str, out_path: str) -> None:
    W = 720
    ROW_H = 68
    HEADER_H = 132
    FOOTER_H = 44
    IMG_H = HEADER_H + ROW_H * len(ranking) + FOOTER_H
    WHITE = (255, 255, 255)
    PAPER = (255, 252, 248)
    INK = (28, 33, 40)
    MUTED = (98, 108, 122)
    LINE = (232, 236, 242)
    RED = (220, 38, 38)
    RED_SOFT = (255, 238, 238)
    BLUE = (37, 99, 235)
    BLUE_SOFT = (235, 243, 255)
    GOLD = (246, 185, 47)
    SILVER = (158, 169, 184)
    BRONZE = (196, 126, 72)
    ROW_ODD = (255, 255, 255)
    ROW_EVN = (248, 250, 252)

    img = Image.new("RGB", (W, IMG_H), PAPER)
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype(FONT_BOLD, 34)
        font_date  = ImageFont.truetype(FONT_REG,  18)
        font_name  = ImageFont.truetype(FONT_BOLD, 20)
        font_code  = ImageFont.truetype(FONT_REG,  14)
        font_pct   = ImageFont.truetype(FONT_BOLD, 24)
        font_price = ImageFont.truetype(FONT_BOLD, 16)
        font_rank  = ImageFont.truetype(FONT_BOLD, 18)
        font_badge = ImageFont.truetype(FONT_BOLD, 12)
    except Exception:
        font_title = font_date = font_name = font_code = font_pct = font_price = font_rank = font_badge = ImageFont.load_default()

    draw.rounded_rectangle([(22, 18), (W - 22, HEADER_H - 18)], radius=18, fill=WHITE, outline=LINE, width=2)
    draw.rounded_rectangle([(44, 38), (122, 74)], radius=18, fill=RED_SOFT)
    draw.text((62, 47), "HOT", font=font_badge, fill=RED)

    title = "PTS 値上がり率ランキング"
    bbox = draw.textbbox((0, 0), title, font=font_title)
    draw.text(((W - (bbox[2] - bbox[0])) // 2, 32), title, font=font_title, fill=INK)

    dbbox = draw.textbbox((0, 0), date_str, font=font_date)
    draw.text(((W - (dbbox[2] - dbbox[0])) // 2, 78), date_str + " 夜", font=font_date, fill=MUTED)

    draw.rounded_rectangle([(W - 134, 38), (W - 44, 74)], radius=18, fill=BLUE_SOFT)
    draw.text((W - 112, 47), "UP!", font=font_badge, fill=BLUE)

    COL_RANK = 34
    COL_NAME = 98
    COL_PCT  = 478
    COL_PRC  = 604
    medals = [GOLD, SILVER, BRONZE]

    for i, r in enumerate(ranking):
        y = HEADER_H + i * ROW_H
        draw.rectangle([(22, y), (W - 22, y + ROW_H)], fill=ROW_ODD if i % 2 == 0 else ROW_EVN)
        draw.line([(44, y + ROW_H - 1), (W - 44, y + ROW_H - 1)], fill=LINE)
        cy = y + ROW_H // 2

        badge_color = medals[i] if i < 3 else (255, 214, 102)
        draw.ellipse([(COL_RANK, cy - 19), (COL_RANK + 38, cy + 19)], fill=badge_color)
        rank_text = str(i + 1)
        rb = draw.textbbox((0, 0), rank_text, font=font_rank)
        draw.text((COL_RANK + 19 - (rb[2] - rb[0]) / 2, cy - 10), rank_text, font=font_rank, fill=WHITE)

        name = r["name"][:9] + "…" if len(r["name"]) > 10 else r["name"]
        draw.text((COL_NAME, cy - 18), name, font=font_name, fill=INK)
        draw.text((COL_NAME, cy + 8), f"コード {r['code']}", font=font_code, fill=MUTED)

        pct = r.get("pct", "")
        pb = draw.textbbox((0, 0), pct, font=font_pct)
        draw.rounded_rectangle([(COL_PCT - 12, cy - 24), (COL_PCT + (pb[2] - pb[0]) + 12, cy + 18)], radius=12, fill=RED_SOFT)
        draw.text((COL_PCT, cy - 19), pct, font=font_pct, fill=RED)
        draw.text((COL_PRC, cy - 9), r.get("price", ""), font=font_price, fill=INK)

    draw.rectangle([(0, IMG_H - FOOTER_H), (W, IMG_H)], fill=WHITE)
    draw.line([(22, IMG_H - FOOTER_H), (W - 22, IMG_H - FOOTER_H)], fill=LINE)
    draw.ellipse([(34, IMG_H - 31), (50, IMG_H - 15)], fill=RED_SOFT)
    draw.text((39, IMG_H - 30), "!", font=font_badge, fill=RED)
    draw.text((58, IMG_H - 29), "出来高1,000株未満は除外  /  S高は前日終値ベース参考値", font=font_code, fill=MUTED)

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
    add_top_reasons(ranking, top_n=3)

    txt_path = os.path.join(SAVE_DIR, f"{file_date}.txt")
    img_path = os.path.join(SAVE_DIR, f"{file_date}.png")

    save_text(ranking, date_str, fetch_time, txt_path)
    print(f"テキスト保存: {txt_path}")

    save_image(ranking, date_str, img_path)
    print(f"画像保存:     {img_path}")


if __name__ == "__main__":
    main()
