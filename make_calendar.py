#!/usr/bin/env python3
"""
決算カレンダー生成スクリプト
- 日本株: irbank.net
- 米国株: Yahoo Finance
- 公開: GitHub Pages（.env に GITHUB_TOKEN / GITHUB_REPO を設定すると自動アップロード）
"""

import requests
from bs4 import BeautifulSoup
import calendar, time, os, re
from datetime import datetime, timedelta
import pytz

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

JST     = pytz.timezone("Asia/Tokyo")
TODAY   = datetime.now(JST).date()
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "ja,en;q=0.9",
}
# カレンダーに常に上位表示する注目銘柄
US_MAJOR = {"AAPL","MSFT","GOOGL","GOOG","AMZN","META","TSLA","NVDA","NFLX","JPM","BAC","WMT","V","MA","BABA","DIS","UBER","ARM","AMD","INTC"}
JP_MAJOR = {"7203","9984","6758","8306","7974","6861","8035","9432","9433","6501","4063","7267","4502","6367","2914"}
SHOW_TOP = 10  # カレンダーセルに表示する上位件数（残りは折りたたみ）

# ─────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────

def parse_us_mcap(s):
    try:
        s = s.replace(",","").strip()
        if s.endswith("T"): return float(s[:-1]) * 1e12
        if s.endswith("B"): return float(s[:-1]) * 1e9
        if s.endswith("M"): return float(s[:-1]) * 1e6
        return float(s)
    except: return 0

def parse_jp_mcap(s):
    try:
        s = s.replace(",", "").strip()
        total = 0.0
        if "兆" in s:
            cho, s = s.split("兆", 1)
            total += float(cho) * 1e12
        if "億" in s:
            oku, s = s.split("億", 1)
            total += float(oku) * 1e8
            return total
        if total > 0:
            return total
        return float(s)
    except: return 0

def extract_jp_time(s):
    # 主表示の発表目安を優先し、括弧内の過去実績はフォールバックとして扱う
    main = re.split(r"[（(]", s, 1)[0]
    m = re.search(r"\d{1,2}:\d{2}", main)
    if m:
        return m.group(0)
    m = re.search(r"\d{1,2}:\d{2}", s)
    return m.group(0) if m else ""

def time_sort_value(s):
    m = re.match(r"^(\d{1,2}):(\d{2})$", s or "")
    if not m:
        return 24 * 60 + 1
    return int(m.group(1)) * 60 + int(m.group(2))

# ─────────────────────────────────────────────
# 日本株: irbank.net
# ─────────────────────────────────────────────

def fetch_irbank_dates():
    """irbank トップページにリンクされた日付 ＋ 直近90日の平日を返す"""
    dates = set()
    try:
        r = requests.get("https://irbank.net/market/kessan", headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.find_all("a"):
            m = re.search(r"kessan\?y=(\d{4}-\d{2}-\d{2})", a.get("href",""))
            if m:
                d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                if d >= TODAY:
                    dates.add(d)
    except Exception as e:
        print(f"  irbank日付取得失敗: {e}")
    for i in range(90):
        d = TODAY + timedelta(i)
        if d.weekday() < 5:
            dates.add(d)
    return sorted(dates)

def fetch_irbank_day(date):
    url = f"https://irbank.net/market/kessan?y={date.strftime('%Y-%m-%d')}"
    stocks = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "lxml")
        table = soup.find("table")
        if not table: return stocks
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 2: continue
            code     = cells[0].get_text(strip=True)
            name     = cells[1].get_text(strip=True)
            kind     = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            time_raw = cells[3].get_text(strip=True) if len(cells) > 3 else ""
            mcap_raw = cells[4].get_text(strip=True) if len(cells) > 4 else ""
            mcap_val = parse_jp_mcap(mcap_raw)
            stocks.append({
                "code": code, "name": name, "kind": kind,
                "time": extract_jp_time(time_raw), "mcap_raw": mcap_raw,
                "mcap_val": mcap_val, "major": code in JP_MAJOR, "market": "jp",
            })
        stocks.sort(key=lambda s: (time_sort_value(s["time"]), -s["mcap_val"]))
    except Exception as e:
        print(f"  irbank {date} 取得失敗: {e}")
    return stocks

def fetch_traders_times():
    """Traders Web の決算発表予定時刻を {date: {code: time}} で返す"""
    times = {}
    url = "https://www.traders.co.jp/market_jp/earnings_calendar"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "lxml")
        lines = [x.strip() for x in soup.get_text("\n").splitlines() if x.strip()]
        i = 0
        while i < len(lines) - 3:
            date_m = re.fullmatch(r"(\d{2})/(\d{2})", lines[i])
            time_m = re.fullmatch(r"-|\d{1,2}:\d{2}", lines[i + 1])
            code_m = re.search(r"\((\d{4}|\d{3}[A-Z])/[^)]*\)", lines[i + 3])
            if date_m and time_m and code_m:
                month = int(date_m.group(1))
                day = int(date_m.group(2))
                year = TODAY.year + (1 if month < TODAY.month - 6 else 0)
                d = datetime(year, month, day).date()
                t = "" if lines[i + 1] == "-" else lines[i + 1]
                times.setdefault(d, {})[code_m.group(1)] = t
                i += 4
                continue
            i += 1
    except Exception as e:
        print(f"  Traders時刻取得失敗: {e}")
    return times

# ─────────────────────────────────────────────
# 米国株: Nasdaq公式API（登録不要）
# ─────────────────────────────────────────────

NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}
TIME_MAP = {
    "time-pre-market":  "BMO",
    "time-after-hours": "AMC",
    "time-not-supplied": "",
}

def parse_nasdaq_mcap(s):
    """'$1,234,567,890' -> float"""
    try:
        return float(s.replace("$","").replace(",","").strip())
    except:
        return 0

def fmt_mcap(v):
    """数値 -> 表示文字列 '1.2T' / '800B' / '500M'"""
    if v >= 1e12: return f"{v/1e12:.1f}T"
    if v >= 1e9:  return f"{v/1e9:.0f}B"
    if v >= 1e6:  return f"{v/1e6:.0f}M"
    return str(int(v))

def fetch_nasdaq_day(date):
    url = f"https://api.nasdaq.com/api/calendar/earnings?date={date.strftime('%Y-%m-%d')}"
    stocks = []
    try:
        r = requests.get(url, headers=NASDAQ_HEADERS, timeout=15)
        rows = (r.json().get("data") or {}).get("rows") or []
        for row in rows:
            ticker   = row.get("symbol", "")
            name     = row.get("name", "")
            mcap_val = parse_nasdaq_mcap(row.get("marketCap", ""))
            mcap_raw = fmt_mcap(mcap_val) if mcap_val else ""
            eps_est  = row.get("epsForecast", "")
            ct       = TIME_MAP.get(row.get("time", ""), "")
            if mcap_val >= 1e9 or ticker in US_MAJOR:
                stocks.append({
                    "ticker": ticker, "name": name, "call_time": ct,
                    "eps_est": eps_est, "mcap_raw": mcap_raw,
                    "mcap_val": mcap_val, "major": ticker in US_MAJOR, "market": "us",
                })
        stocks.sort(key=lambda s: -s["mcap_val"])
    except Exception as e:
        print(f"  Nasdaq API {date} 取得失敗: {e}")
    return stocks

# ─────────────────────────────────────────────
# 重要事項: SBI証券 経済指標（キーなし）
# ─────────────────────────────────────────────

EVENT_COUNTRY = {
    "日本": ("jp", "🇯🇵", "日本"),
    "米国": ("us", "🇺🇸", "米国"),
}

SBI_EVENT_URLS = [
    "https://www.sbisec.co.jp/ETGate/?OutSide=on&getFlg=on&_ControlID=WPLETmgR001Control&_PageID=WPLETmgR001Mdtl20&_ActionID=DefaultAID&_DataStoreID=DSWPLETmgR001Control&burl=iris_economicCalendar&cat1=market&cat2=economicCalender&dir=tl1-cal%7Ctl2-event%7Ctl3-week&file=index.html",
    "https://www.sbisec.co.jp/ETGate/?OutSide=on&getFlg=on&_ControlID=WPLETmgR001Control&_PageID=WPLETmgR001Mdtl20&_ActionID=DefaultAID&_DataStoreID=DSWPLETmgR001Control&burl=iris_economicCalendar&cat1=market&cat2=economicCalender&dir=tl1-cal%7Ctl2-event%7Ctl3-month&file=index.html",
]

IMPORTANT_EVENT_RE = re.compile(
    r"消費者物価|生産者物価|小売売上|雇用統計|非農業部門|失業率|"
    r"新規失業保険|FOMC|FRB|連邦公開市場|政策金利|日銀|金融政策|"
    r"GDP|国内総生産|貿易収支|経常収支|輸出|輸入|家計調査|"
    r"景気動向|景気一致|景気先行|景気ウォッチャー|マネーストック|"
    r"鉱工業生産|住宅着工|中古住宅|新築住宅|建設許可|"
    r"ISM|PMI|ミシガン|消費者信頼感|ニューヨーク連銀",
    re.I,
)

def sbi_event_date(month, day):
    year = TODAY.year
    if month < TODAY.month - 6:
        year += 1
    elif month > TODAY.month + 6:
        year -= 1
    return datetime(year, month, day).date()

def is_important_sbi_event(name):
    return bool(IMPORTANT_EVENT_RE.search(name or ""))

def fetch_important_events(start_date, end_date):
    """SBI証券の経済指標ページから日本/米国の重要イベントを返す"""
    events = {}
    seen = set()
    try:
        for url in SBI_EVENT_URLS:
            r = requests.get(url, headers=HEADERS, timeout=25)
            r.encoding = "shift_jis"
            soup = BeautifulSoup(r.text, "lxml")
            lines = [x.strip() for x in soup.get_text("\n").splitlines() if x.strip()]
            try:
                start_i = lines.index("直近の主要経済指標")
            except ValueError:
                start_i = 0
            current_date = None
            i = start_i + 1
            while i < len(lines):
                dm = re.fullmatch(r"(\d{1,2})/(\d{1,2})（.）", lines[i])
                if dm and i + 3 < len(lines) and lines[i + 1:i + 4] == ["時刻", "地域", "指標"]:
                    current_date = sbi_event_date(int(dm.group(1)), int(dm.group(2)))
                    i += 4
                    continue
                if (
                    current_date
                    and start_date <= current_date <= end_date
                    and re.fullmatch(r"\d{1,2}:\d{2}", lines[i])
                    and i + 2 < len(lines)
                ):
                    time_txt, country, name = lines[i], lines[i + 1], lines[i + 2]
                    if country in EVENT_COUNTRY and is_important_sbi_event(name):
                        code, flag, country_jp = EVENT_COUNTRY[country]
                        key = (current_date, time_txt, code, name)
                        if key not in seen:
                            seen.add(key)
                            events.setdefault(current_date, []).append({
                                "country": code,
                                "country_name": country_jp,
                                "flag": flag,
                                "name": name,
                                "time": time_txt,
                                "importance": 3,
                                "commentary": economic_commentary(name, country_jp),
                            })
                    i += 6
                    continue
                i += 1
        for items in events.values():
            items.sort(key=lambda x: (time_sort_value(x["time"]), x["country"], x["name"]))
    except Exception as e:
        print(f"  SBI経済指標 取得失敗: {e}")
    return events

def economic_commentary(name, country):
    n = name or ""
    jp = country == "日本"
    if re.search(r"消費者物価|CPI", n, re.I):
        return "インフレ圧力を見る最重要指標。予想より強いと金利上昇・株安材料になりやすいです。"
    if re.search(r"生産者物価|PPI", n, re.I):
        return "企業側の物価圧力を確認する指標。CPIに先行しやすく、インフレ観測に影響します。"
    if re.search(r"小売売上", n):
        return "個人消費の強さを測る指標。米国では景気・金利見通しに直結しやすいです。"
    if re.search(r"雇用統計|非農業部門|失業率|新規失業保険", n):
        return "雇用の強弱を示す指標。強すぎると利下げ期待後退、弱いと景気減速懸念につながります。"
    if re.search(r"FOMC|FRB|連邦公開市場|政策金利", n, re.I):
        return "金融政策イベント。声明文や発言で金利・為替・株式市場が大きく動くことがあります。"
    if re.search(r"日銀|金融政策", n):
        return "日本の金利・円相場に関わる重要イベント。銀行株や輸出株にも影響しやすいです。"
    if re.search(r"GDP|国内総生産", n, re.I):
        return "景気全体の温度感を示す指標。予想差が大きいと株式・為替の方向感に影響します。"
    if re.search(r"貿易収支|経常収支|輸出|輸入", n):
        return "外需と通貨需給を確認する指標。円相場や輸出関連株の材料になりやすいです。"
    if re.search(r"景気動向|景気一致|景気先行|景気ウォッチャー", n):
        return "景気の先行きや現状判断を見る指標。国内景気敏感株の見方に使われます。"
    if re.search(r"ISM|PMI|ミシガン|消費者信頼感|ニューヨーク連銀", n, re.I):
        return "景況感を測る指標。市場予想との差が大きいと米国株やドル円が反応しやすいです。"
    if re.search(r"住宅|建設許可", n):
        return "金利に敏感な住宅市場の指標。米国金利や景気減速の確認材料になります。"
    if re.search(r"家計調査", n):
        return "日本の個人消費を見る指標。内需関連や日銀の景気判断の補助材料になります。"
    return "市場が景気・金利・為替の見通しを確認する材料です。予想との差に注目です。"

# ─────────────────────────────────────────────
# 注目度: Yahoo!ファイナンス掲示板投稿数ランキング
# ─────────────────────────────────────────────

YAHOO_BBS_RANKS = {}
YAHOO_BBS_UPDATED = ""

def fetch_yahoo_bbs_ranking():
    """Yahoo!ファイナンスの日本株掲示板投稿数ランキングを {code: rank} で返す"""
    global YAHOO_BBS_UPDATED
    urls = [
        "https://finance.yahoo.co.jp/stocks/ranking/bbs?market=all",
        "https://finance.yahoo.co.jp/stocks/ranking/bbs?market=all&term=weekly",
    ]
    ranks = {}
    try:
        for url in urls:
            r = requests.get(url, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(r.text, "lxml")
            text = soup.get_text("\n")
            m = re.search(r"更新日時[：:]\s*([0-9/:\s]+)", text)
            if m and not YAHOO_BBS_UPDATED:
                YAHOO_BBS_UPDATED = m.group(1).strip()
            order = []
            for a in soup.find_all("a", href=True):
                m = re.search(r"/quote/([0-9A-Z]{3,5})\.T/?$", a["href"])
                if m:
                    code = m.group(1)
                    if code not in order:
                        order.append(code)
            for idx, code in enumerate(order[:50], 1):
                ranks[code] = min(ranks.get(code, 999), idx)
    except Exception as e:
        print(f"  Yahoo掲示板ランキング取得失敗: {e}")
    return ranks

# ─────────────────────────────────────────────
# HTML生成
# ─────────────────────────────────────────────

TIME_LABEL = {"BMO": "開場前", "AMC": "閉場後", "TAS": "取引中"}

def make_badge(s):
    if s["market"] == "jp":
        t = f' <span class="btime">{s["time"]}</span>' if s["time"] else ""
        tip = f'{s["name"]}（{s["code"]}）{s["kind"]} {s["mcap_raw"]}'
        cls = "bj major" if s["major"] else "bj"
        return f'<div class="{cls}" title="{tip}">🇯🇵 {s["name"]}{t}</div>'
    else:
        tl = TIME_LABEL.get(s["call_time"], s["call_time"])
        t = f' <span class="btime">{tl}</span>' if tl else ""
        tip = f'{s["name"]}（{s["ticker"]}）EPS予想:{s["eps_est"]} {s["mcap_raw"]}'
        cls = "bu major" if s["major"] else "bu"
        return f'<div class="{cls}" title="{tip}">🇺🇸 {s["ticker"]}{t}</div>'

def make_detail_row(s):
    if s["market"] == "jp":
        tl = s["time"] or "—"
        return f'<div class="dr"><span class="dc2">🇯🇵 {s["name"]}</span><span class="dt">{tl}</span><span class="dm">{s["mcap_raw"]}</span></div>'
    else:
        tl = TIME_LABEL.get(s["call_time"], s["call_time"]) or "—"
        return f'<div class="dr"><span class="dc2">🇺🇸 {s["ticker"]}</span><span class="dt">{tl}</span><span class="dm">{s["mcap_raw"]}</span></div>'

import json as _json

def build_files(all_events):
    """index.html（小・テンプレート）と data.js（大・データ）を返す"""
    updated   = datetime.now(JST).strftime("%Y/%m/%d %H:%M")
    data_ver  = datetime.now(JST).strftime("%Y%m%d%H%M")
    today_str = TODAY.strftime("%Y-%m-%d")
    total_jp  = sum(len(v.get("jp",[])) for v in all_events.values())
    total_us  = sum(len(v.get("us",[])) for v in all_events.values())
    total_imp = sum(len(v.get("events",[])) for v in all_events.values())

    # ── data.js 用データ構造 ──
    data = {}
    for dt, ev in all_events.items():
        key = dt.strftime("%Y-%m-%d")
        data[key] = {
            "jp": [{"code":s["code"],"name":s["name"],"kind":s["kind"],
                    "time":s["time"],"mcap":s["mcap_raw"],"mv":s["mcap_val"],
                    "major":s["major"],"buzz":YAHOO_BBS_RANKS.get(s["code"])} for s in ev.get("jp",[])],
            "us": [{"ticker":s["ticker"],"name":s["name"],"ct":s["call_time"],
                    "eps":s["eps_est"],"mcap":s["mcap_raw"],"mv":s["mcap_val"],
                    "major":s["major"]} for s in ev.get("us",[])],
            "events": [{"country":s["country"],"country_name":s["country_name"],
                        "flag":s["flag"],"name":s["name"],"time":s["time"],
                        "importance":s["importance"],"commentary":s.get("commentary","")} for s in ev.get("events",[])],
        }
    meta = {"updated": updated, "today": today_str,
            "total_jp": total_jp, "total_us": total_us,
            "total_events": total_imp, "top": SHOW_TOP,
            "bbs_updated": YAHOO_BBS_UPDATED}

    data_js = f"window.META={_json.dumps(meta,ensure_ascii=False)};\nwindow.DATA={_json.dumps(data,ensure_ascii=False,separators=(',',':'))};"

    # ── index.html（軽量テンプレート）──
    html = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>決算カレンダー</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f7f6f3;color:#1a1a1a;font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif;font-size:14px;line-height:1.5}

/* ── ヘッダー ── */
header{position:sticky;top:0;z-index:100;background:#fff;border-bottom:3px solid #f97316;padding:10px 20px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;box-shadow:0 2px 8px rgba(0,0,0,.06)}
header h1{font-size:1.15rem;font-weight:800;color:#1a1a1a;white-space:nowrap;letter-spacing:-.3px}
header h1 span{color:#f97316}
.hchips{display:flex;gap:6px;flex-wrap:wrap}
.hchip{padding:3px 10px;border-radius:20px;font-size:0.72rem;font-weight:700;border:1.5px solid}
.hchip-jp{background:#fff7ed;color:#c2410c;border-color:#fed7aa}
.hchip-us{background:#eff6ff;color:#1d4ed8;border-color:#bfdbfe}
.hchip-week{background:#f0fdf4;color:#15803d;border-color:#bbf7d0;font-size:0.68rem}
.search-wrap{margin-left:auto}
.search-box{background:#f3f4f6;border:1.5px solid #e5e7eb;border-radius:20px;padding:5px 14px;color:#1a1a1a;font-size:0.8rem;width:160px;outline:none;transition:.2s}
.search-box:focus{border-color:#f97316;width:200px;background:#fff}
.search-box::placeholder{color:#9ca3af}
.upd{color:#9ca3af;font-size:0.68rem;white-space:nowrap}
@media(max-width:600px){header{padding:8px 12px};.search-box{width:110px};.upd{display:none}}

/* ── メインタブ（JP / US / お気に入り）── */
.mtabs{display:flex;background:#fff;border-bottom:2px solid #e5e7eb;padding:0 16px;overflow-x:auto}
.mtab{padding:10px 18px;cursor:pointer;font-size:0.85rem;font-weight:600;color:#9ca3af;border-bottom:3px solid transparent;transition:.2s;white-space:nowrap;margin-bottom:-2px}
.mtab:hover{color:#f97316}
.mtab.active{color:#f97316;border-bottom-color:#f97316}
.mtab.active.us{color:#1d4ed8;border-bottom-color:#1d4ed8}
.fav-badge{background:#f97316;color:#fff;border-radius:10px;padding:0 5px;font-size:0.6rem;margin-left:3px}

/* ── マーケットパネル ── */
.mpanel{display:none}.mpanel.active{display:block}

/* ── サブタブ（カレンダー / 一覧）── */
.stabs{display:flex;background:#f7f6f3;border-bottom:1px solid #e5e7eb;padding:0 16px}
.stab{padding:8px 14px;cursor:pointer;font-size:0.78rem;font-weight:600;color:#9ca3af;border-bottom:2px solid transparent;transition:.15s;white-space:nowrap;margin-bottom:-1px}
.stab.active{color:#1a1a1a;border-bottom-color:#1a1a1a}

/* ── ビュー ── */
.view{display:none;padding:16px 20px}.view.active{display:block}

/* ── 注目決算カード ── */
.week-section{margin-bottom:20px}
.sec-head{display:flex;align-items:center;gap:8px;margin-bottom:12px}
.sec-num{background:#f97316;color:#fff;font-size:0.72rem;font-weight:800;width:22px;height:22px;border-radius:5px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.sec-title{font-size:0.88rem;font-weight:700;color:#1a1a1a}
.sec-sub{font-size:0.72rem;color:#9ca3af;margin-left:4px}
.spotlight{display:flex;gap:10px;flex-wrap:wrap}
.scard{background:#fff;border:1.5px solid #e5e7eb;border-radius:10px;padding:12px 14px;min-width:130px;max-width:165px;position:relative;transition:.15s;box-shadow:0 1px 4px rgba(0,0,0,.05)}
.scard:hover{border-color:#f97316;box-shadow:0 2px 8px rgba(249,115,22,.15)}
.scard.us:hover{border-color:#3b82f6;box-shadow:0 2px 8px rgba(59,130,246,.15)}
.sc-date{font-size:0.62rem;color:#9ca3af;margin-bottom:4px;font-weight:600}
.sc-name{font-size:0.88rem;font-weight:800;color:#1a1a1a;margin-bottom:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.scard.jp .sc-name{color:#c2410c}
.scard.us .sc-name{color:#1d4ed8}
.sc-sub{font-size:0.62rem;color:#6b7280;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc-time{margin-top:6px}
.tbmo{background:#f0fdf4;color:#15803d;font-size:0.6rem;font-weight:700;padding:2px 7px;border-radius:10px;border:1px solid #bbf7d0}
.tamc{background:#fff7ed;color:#c2410c;font-size:0.6rem;font-weight:700;padding:2px 7px;border-radius:10px;border:1px solid #fed7aa}
.sfav{position:absolute;top:8px;right:10px;font-size:0.85rem;cursor:pointer;color:#d1d5db}
.sfav.on{color:#f97316}
.scard.us .sfav.on{color:#3b82f6}

/* ── 朝イチダッシュボード ── */
.dash{padding:16px 20px 4px;background:#f7f6f3}
.dash-grid{display:grid;grid-template-columns:1fr;gap:14px;margin-bottom:14px}
.dash-card{background:#fff;border:1.5px solid #e5e7eb;border-radius:12px;padding:14px 16px;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.dash-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}
.dash-title{font-size:1rem;font-weight:900;color:#1a1a1a}
.dash-date{font-size:.74rem;color:#9ca3af;font-weight:700;white-space:nowrap}
.attention-block{margin-top:14px}
.attention-block:first-child{margin-top:0}
.attention-block-head{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:8px}
.attention-block-title{font-size:.9rem;font-weight:900;color:#1a1a1a}
.attention-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}
.attention-card{border:1.5px solid #e5e7eb;border-radius:10px;background:#fff;padding:11px 12px;cursor:pointer;min-height:108px;display:flex;flex-direction:column;gap:5px}
.attention-card:hover{border-color:#f97316;background:#fffbf7}
.attention-card.us:hover{border-color:#3b82f6;background:#eff6ff}
.att-top{display:flex;align-items:center;justify-content:space-between;gap:8px}
.att-rank{font-size:.7rem;font-weight:900;color:#f97316;background:#fff7ed;border:1px solid #fed7aa;border-radius:12px;padding:1px 7px;white-space:nowrap}
.att-place{font-size:.72rem;font-weight:900;color:#1a1a1a;background:#f3f4f6;border-radius:12px;padding:1px 7px;white-space:nowrap}
.att-name{font-size:.9rem;font-weight:900;color:#1a1a1a;line-height:1.35}
.att-code{font-size:.68rem;color:#9ca3af;margin-left:4px}
.att-meta,.att-reason{font-size:.72rem;color:#6b7280;line-height:1.45}
.att-reason{color:#374151}
.watch-share{margin-top:10px;font-size:.72rem;color:#6b7280}
.mini-btn{border:1.5px solid #e5e7eb;background:#fff;border-radius:8px;padding:5px 9px;font-size:.72rem;font-weight:800;color:#6b7280;cursor:pointer}
.mini-btn:hover{border-color:#f97316;color:#f97316}

/* ── 月ジャンプ ── */
.month-nav{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.mnbtn{padding:4px 16px;border-radius:20px;font-size:0.75rem;font-weight:600;cursor:pointer;border:1.5px solid #e5e7eb;background:#fff;color:#6b7280;transition:.15s}
.mnbtn:hover{border-color:#f97316;color:#f97316}
.mnbtn.active{background:#f97316;color:#fff;border-color:#f97316}
.mnbtn.active.us{background:#1d4ed8;border-color:#1d4ed8}

/* ── カレンダー ── */
.months{display:grid;grid-template-columns:1fr;gap:20px}
.month{background:#fff;border-radius:12px;padding:16px;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.month h3{font-size:1rem;font-weight:800;color:#1a1a1a;margin-bottom:10px;display:flex;align-items:center;gap:10px}
.month h3 .mc{font-size:0.72rem;color:#9ca3af;font-weight:500;background:#f3f4f6;padding:2px 8px;border-radius:10px}
.ghd{display:grid;grid-template-columns:repeat(7,1fr);gap:3px;margin-bottom:3px}
.wh{text-align:center;font-size:0.65rem;font-weight:700;color:#9ca3af;padding:3px}
.wh.sat{color:#3b82f6}.wh.sun{color:#ef4444}
.grid{display:grid;grid-template-columns:repeat(7,1fr);gap:3px}
.day{background:#f9fafb;border:1.5px solid #f3f4f6;border-radius:6px;padding:5px 4px;min-height:105px;overflow:hidden;transition:.1s}
.day:hover{border-color:#e5e7eb}
.empty{background:transparent;border:none;min-height:105px}
.day.past{opacity:.35}
.day.today{background:#fff7ed;border:2px solid #f97316}
.day.has{background:#fff;border-color:#e5e7eb}
.day.has.jp-only{border-left:3px solid #f97316}
.day.has.us-only{border-left:3px solid #3b82f6}
.day.has.both{border-left:3px solid #8b5cf6}
.dn{display:block;font-size:0.7rem;color:#6b7280;margin-bottom:3px;font-weight:700}
.day.today .dn{color:#f97316}
.dn.sat{color:#3b82f6}.dn.sun{color:#ef4444}
.bj,.bu{font-size:0.65rem;border-radius:4px;padding:2px 5px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;display:block}
.bj{background:#fff7ed;color:#c2410c;border-left:3px solid #f97316}
.bu{background:#eff6ff;color:#1d4ed8;border-left:3px solid #3b82f6}
.bj.major{background:#ffedd5;font-weight:700;color:#9a3412;border-left-color:#ea580c}
.bu.major{background:#dbeafe;font-weight:700;color:#1e40af;border-left-color:#2563eb}
.bj.dim,.bu.dim{opacity:.12}
.bcode{color:#9ca3af;font-size:0.55rem;margin-left:3px}
.btime{color:#9ca3af;font-size:0.57rem;margin-left:3px}
details.more{margin-top:3px}
details.more summary{font-size:0.58rem;color:#6b7280;cursor:pointer;padding:2px 5px;border-radius:4px;background:#f3f4f6;list-style:none;font-weight:600}
details.more summary:hover{background:#e5e7eb}
.dr{display:flex;gap:4px;padding:2px 0;font-size:0.58rem;border-bottom:1px solid #f3f4f6}
.dc2{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#374151}
.dt,.dm{color:#9ca3af;white-space:nowrap}

/* ── 一覧 ── */
table{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.06)}
th{text-align:left;padding:9px 12px;font-size:0.73rem;font-weight:700;color:#6b7280;border-bottom:2px solid #f3f4f6;background:#f9fafb;position:sticky;top:0}
td{padding:8px 12px;font-size:0.8rem;border-bottom:1px solid #f3f4f6;color:#374151}
tr:last-child td{border-bottom:none}
tr:hover td{background:#fafafa}
tr.mrow td:nth-child(2){font-weight:700;color:#1a1a1a}
.ldc{color:#9ca3af;white-space:nowrap;font-size:0.72rem}.ltc{color:#9ca3af;font-size:0.72rem}

/* ── お気に入り ── */
.fav-wrap{display:flex;flex-direction:column;gap:10px}
.fav-item{background:#fff;border:1.5px solid #e5e7eb;border-radius:10px;padding:12px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px;box-shadow:0 1px 4px rgba(0,0,0,.04)}
.fi-name{font-size:0.9rem;font-weight:700;color:#1a1a1a}
.fi-sub{font-size:0.72rem;color:#6b7280;margin-top:2px}
.fi-right{text-align:right;white-space:nowrap}
.fi-date{font-size:0.8rem;font-weight:700;color:#1a1a1a}
.fi-days{font-size:0.68rem;color:#15803d;font-weight:600;margin-top:2px}
.fi-del{font-size:0.7rem;color:#d1d5db;cursor:pointer;margin-top:4px}
.fi-del:hover{color:#ef4444}
.fav-empty{text-align:center;color:#9ca3af;padding:48px 20px;font-size:0.88rem;background:#fff;border-radius:10px;border:1.5px dashed #e5e7eb}
.fav-tools{display:flex;justify-content:flex-end;margin-bottom:10px}
footer{margin-top:40px;padding:20px;border-top:1px solid #e5e7eb;background:#f9fafb;text-align:center;font-size:0.7rem;color:#9ca3af;line-height:1.8}
footer a{color:#9ca3af;text-decoration:underline}

/* ── 詳細モーダル ── */
.modal{position:fixed;inset:0;background:rgba(17,24,39,.38);display:none;align-items:center;justify-content:center;z-index:200;padding:20px}
.modal.show{display:flex}
.modal-card{background:#fff;border-radius:12px;box-shadow:0 18px 50px rgba(0,0,0,.22);width:min(520px,100%);max-height:82vh;overflow:auto}
.modal-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;padding:16px 18px;border-bottom:1px solid #f3f4f6}
.modal-title{font-size:1rem;font-weight:900;color:#1a1a1a;line-height:1.4}.modal-sub{font-size:.75rem;color:#9ca3af;margin-top:3px}
.modal-close{border:none;background:#f3f4f6;color:#6b7280;border-radius:8px;width:30px;height:30px;font-size:1rem;cursor:pointer}
.modal-body{padding:16px 18px}.md-row{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid #f9fafb;padding:8px 0;font-size:.82rem}.md-k{color:#9ca3af;font-weight:700}.md-v{font-weight:800;color:#1a1a1a;text-align:right}

/* ── 経済指標 ── */
.events-wrap{display:flex;flex-direction:column;gap:12px}
.events-cal{display:grid;grid-template-columns:1fr;gap:20px}
.event-agenda{display:none}
.events-empty{text-align:center;color:#9ca3af;padding:48px 20px;font-size:0.88rem;background:#fff;border-radius:10px;border:1.5px dashed #e5e7eb}
.event-item{display:flex;align-items:flex-start;gap:10px;padding:9px 14px;border-bottom:1px solid #f9fafb;font-size:0.84rem}
.event-item:last-child{border-bottom:none}
.event-time{font-size:0.76rem;color:#6b7280;font-weight:800;flex:0 0 3.2em;white-space:nowrap}
.event-flag{flex:0 0 1.5em;font-size:1rem;line-height:1.4}
.event-copy{flex:1;min-width:0;cursor:pointer}
.event-name{display:block;color:#1a1a1a;font-weight:800;line-height:1.5;min-width:0}
.event-note{display:block;color:#6b7280;font-size:.74rem;line-height:1.5;margin-top:2px}
.evflag{margin-right:3px}

/* ── アジェンダビュー（スマホ専用）── */
.agenda{display:none;flex-direction:column;gap:12px}
.ag-day{background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.ag-head{padding:10px 14px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #f3f4f6}
.ag-head-date{font-size:0.9rem;font-weight:800;color:#1a1a1a}
.ag-head-date.sat{color:#3b82f6}.ag-head-date.sun{color:#ef4444}
.ag-cnt{font-size:0.7rem;font-weight:600;color:#9ca3af;background:#f3f4f6;padding:2px 8px;border-radius:10px}
.ag-item{display:flex;align-items:flex-start;gap:10px;padding:9px 14px;border-bottom:1px solid #f9fafb;font-size:0.82rem}
.ag-item:last-child{border-bottom:none}
.ag-item.major-item{background:#fffbf7}
.ag-time{font-size:0.76rem;color:#6b7280;font-weight:800;flex:0 0 3.2em;white-space:nowrap}
.ag-names{flex:1;color:#1a1a1a;font-weight:600;line-height:1.55;min-width:0}
.ag-item.major-item .ag-names{color:#c2410c}
.ag-item.us-item .ag-names{color:#1d4ed8}
.ag-item.us-item.major-item .ag-names{color:#1e40af}
.ag-code{font-size:0.68rem;color:#9ca3af;margin-left:2px}
.ag-more{padding:8px 14px;font-size:0.75rem;color:#9ca3af;text-align:center;cursor:pointer;background:#f9fafb}
.ag-more:hover{background:#f3f4f6}
.ag-today .ag-head{background:#fff7ed;border-bottom-color:#fed7aa}
.ag-today .ag-head-date{color:#f97316}

/* ビュー切替ボタン（スマホのみ表示）*/
.view-toggle{display:none;gap:6px;margin-bottom:14px}
.vtbtn{flex:1;padding:8px;border-radius:8px;font-size:0.78rem;font-weight:600;cursor:pointer;border:1.5px solid #e5e7eb;background:#fff;color:#6b7280;text-align:center;transition:.15s}
.vtbtn.active{background:#f97316;color:#fff;border-color:#f97316}
.vtbtn.active.us{background:#1d4ed8;border-color:#1d4ed8}

@media(max-width:768px){
  /* ヘッダー */
  header{padding:8px 14px;gap:8px}
  header h1{font-size:1rem}
  .hchips{gap:4px}
  .hchip{font-size:0.65rem;padding:2px 8px}
  .hchip-week{display:none}
  .search-wrap{width:100%;margin-left:0;order:3;flex-basis:100%}
  .search-box{width:100%;border-radius:8px}
  .search-box:focus{width:100%}
  .upd{display:none}
  /* タブ */
  .mtabs{padding:0 10px}
  .mtab{padding:8px 12px;font-size:0.8rem}
  .stabs{padding:0 10px}
  /* パネル */
  .view{padding:12px 14px}
  /* カレンダー非表示、アジェンダ表示 */
  .month-nav{display:none}
  .months{display:none}
  .agenda{display:flex}
  .events-cal{display:none}
  .event-agenda{display:flex}
  .view-toggle{display:flex}
  /* 注目カード */
  .spotlight{gap:8px}
  .scard{min-width:calc(50% - 4px);max-width:calc(50% - 4px)}
  .dash{padding:12px 14px 0}.dash-grid{grid-template-columns:1fr}.dash-title{font-size:.92rem}
}

/* ── テーブルカレンダー ── */
.cal-tbl{width:100%;border-collapse:collapse;table-layout:fixed}
.cal-tbl th{background:#fef9c3;color:#555;font-size:0.78rem;font-weight:700;text-align:center;padding:7px 4px;border:1px solid #e2e8f0;letter-spacing:.5px}
.sc2{border:1px solid #e2e8f0;padding:6px 7px;vertical-align:top;min-height:85px;background:#fff}
.sc2.no-data{background:#f9fafb}
.sc2.empty-cell{background:#f1f5f9;border-color:#e2e8f0;min-height:85px}
.sc2.today{background:#fff7ed!important;border-color:#fbd38d!important}
.sc2.past{opacity:.4}
.dn2{font-size:0.68rem;color:#bbb;font-weight:700;margin-bottom:3px}
.tg{font-size:0.72rem;line-height:1.6;display:flex;gap:5px}
.tgt{color:#666;font-weight:700;white-space:nowrap;flex-shrink:0;min-width:2.8em}
.tgn{color:#1a1a1a}
.week-cur td.sc2{border-top:2px dashed #e53e3e!important;border-bottom:2px dashed #e53e3e!important}
.week-cur td.sc2:first-child{border-left:2px dashed #e53e3e!important}
.week-cur td.sc2:last-child{border-right:2px dashed #e53e3e!important}
.holiday-cell{background:#f0f0f0!important}
.holiday-label{font-size:0.72rem;color:#aaa;text-align:center;margin-top:10px;letter-spacing:.5px}
.tg-more{margin-top:3px}
.tg-more summary{font-size:0.65rem;color:#aaa;cursor:pointer;list-style:none;padding:1px 3px;display:inline-block}
.tg-more summary:hover{color:#555}
.tg-more summary::-webkit-details-marker{display:none}
.tgc{color:#bbb;font-size:0.65em;margin-left:2px}
@media(max-width:768px){.cal-tbl th,.tgt{font-size:0.65rem}.tgn{font-size:0.65rem}}
</style>
</head>
<body>

<header>
  <h1>📊 決算<span>カレンダー</span></h1>
  <div class="hchips">
    <span class="hchip hchip-jp" id="cjp"></span>
    <span class="hchip hchip-us" id="cus"></span>
    <span class="hchip hchip-week" id="cweek"></span>
  </div>
  <div class="search-wrap">
    <input class="search-box" type="search" placeholder="🔍 銘柄を検索..." id="searchBox" oninput="filterStocks(this.value)">
  </div>
  <span class="upd" id="upd"></span>
</header>

<div class="mtabs">
  <div class="mtab active" onclick="showMarket('jp',this)">🇯🇵 日本株</div>
  <div class="mtab" onclick="showMarket('us',this)">🇺🇸 米国株</div>
  <div class="mtab" onclick="showMarket('events',this)">📈 経済指標</div>
  <div class="mtab" onclick="showMarket('fav',this)">⭐ お気に入り<span class="fav-badge" id="fav-cnt" style="display:none"></span></div>
</div>

<section class="dash" id="dash">
  <div class="dash-grid">
    <div class="dash-card">
      <div class="dash-head"><div><div class="dash-title">注目ランキング</div><div class="dash-date" id="attention-source"></div></div></div>
      <div class="attention-block">
        <div class="attention-block-head"><div class="attention-block-title">明日の注目ランキング</div><div class="dash-date" id="attention-tomorrow-range"></div></div>
        <div class="attention-list" id="attention-tomorrow"></div>
      </div>
      <div class="attention-block">
        <div class="attention-block-head"><div class="attention-block-title">今週注目の銘柄</div><div class="dash-date" id="attention-week-range"></div></div>
        <div class="attention-list" id="attention-week"></div>
      </div>
      <div class="attention-block">
        <div class="attention-block-head"><div class="attention-block-title">来週の注目ランキング</div><div class="dash-date" id="attention-next-range"></div></div>
        <div class="attention-list" id="attention-next"></div>
      </div>
    </div>
  </div>
</section>

<!-- ── 日本株パネル ── -->
<div id="mpanel-jp" class="mpanel active">
  <div class="stabs">
    <div class="stab active" onclick="showView('jp','cal',this)">📅 カレンダー</div>
    <div class="stab" onclick="showView('jp','list',this)">📋 一覧</div>
  </div>
  <div id="view-jp-cal" class="view active">
    <div class="view-toggle" id="vtoggle-jp">
      <div class="vtbtn active" onclick="switchView('jp','agenda',this)">📋 一覧</div>
      <div class="vtbtn" onclick="switchView('jp','cal',this)">📅 カレンダー</div>
    </div>
    <div class="month-nav" id="nav-jp"></div>
    <div class="months" id="months-jp"></div>
    <div class="agenda" id="agenda-jp"></div>
  </div>
  <div id="view-jp-list" class="view">
    <div id="tbl-jp"></div>
  </div>
</div>

<!-- ── 米国株パネル ── -->
<div id="mpanel-us" class="mpanel">
  <div class="stabs">
    <div class="stab active" onclick="showView('us','cal',this)">📅 カレンダー</div>
    <div class="stab" onclick="showView('us','list',this)">📋 一覧</div>
  </div>
  <div id="view-us-cal" class="view active">
    <div class="view-toggle" id="vtoggle-us">
      <div class="vtbtn active us" onclick="switchView('us','agenda',this)">📋 一覧</div>
      <div class="vtbtn" onclick="switchView('us','cal',this)">📅 カレンダー</div>
    </div>
    <div class="month-nav" id="nav-us"></div>
    <div class="months" id="months-us"></div>
    <div class="agenda" id="agenda-us"></div>
  </div>
  <div id="view-us-list" class="view">
    <div id="tbl-us"></div>
  </div>
</div>

<!-- ── お気に入りパネル ── -->
<div id="mpanel-fav" class="mpanel">
  <div style="padding:16px 20px"><div class="fav-tools"><button class="mini-btn" onclick="copyWatchUrl()">ウォッチリストURLをコピー</button></div><div id="fav-list"></div></div>
</div>

<!-- ── 経済指標パネル ── -->
<div id="mpanel-events" class="mpanel">
  <div class="view active">
    <div class="week-section">
      <div class="sec-head"><div class="sec-num">1</div><span class="sec-title">経済指標カレンダー</span><span class="sec-sub" id="range-events"></span></div>
      <div class="month-nav" id="nav-events"></div>
      <div class="events-cal" id="months-events"></div>
      <div class="events-wrap event-agenda" id="events-list"></div>
    </div>
  </div>
</div>

<footer>
  📊 データ出典：<a href="https://irbank.net" target="_blank">irbank.net</a>（日本株）／ <a href="https://www.nasdaq.com" target="_blank">Nasdaq</a>（米国株）／ <a href="https://www.sbisec.co.jp" target="_blank">SBI証券</a>（経済指標）／ <a href="https://finance.yahoo.co.jp/stocks/ranking/bbs" target="_blank">Yahoo!ファイナンス</a>（掲示板投稿数ランキング）<br>
  本サイトの情報は自動取得であり、正確性・完全性を保証するものではありません。<br>
  掲載情報は予告なく変更・削除される場合があります。投資判断はご自身の責任で行ってください。
</footer>
<div class="modal" id="detail-modal" onclick="closeDetail(event)">
  <div class="modal-card" onclick="event.stopPropagation()">
    <div class="modal-head"><div><div class="modal-title" id="modal-title"></div><div class="modal-sub" id="modal-sub"></div></div><button class="modal-close" onclick="closeDetail()">×</button></div>
    <div class="modal-body" id="modal-body"></div>
  </div>
</div>
<script src="data.js?v=__DATA_VER__"></script>
<script>
const TL={BMO:"開場前",AMC:"閉場後",TAS:"取引中"};
const DAYS=["月","火","水","木","金","土","日"];
const WD=['日','月','火','水','木','金','土'];
const JP_HOLIDAYS=new Set(['2026-01-01','2026-01-02','2026-01-12','2026-02-11','2026-02-23','2026-03-20','2026-04-29','2026-05-04','2026-05-05','2026-05-06','2026-07-20','2026-08-11','2026-09-21','2026-09-23','2026-10-13','2026-11-03','2026-11-23','2026-12-31','2027-01-01','2027-01-02','2027-01-11','2027-02-11','2027-02-23']);
const US_HOLIDAYS=new Set(['2026-01-01','2026-01-19','2026-02-16','2026-04-03','2026-05-25','2026-07-03','2026-09-07','2026-11-26','2026-12-25','2027-01-01','2027-01-18','2027-02-15']);
const JP_US={'AAPL':'アップル','MSFT':'マイクロソフト','GOOGL':'アルファベット','GOOG':'アルファベット','AMZN':'アマゾン','META':'メタ','TSLA':'テスラ','NVDA':'エヌビディア','JPM':'JPモルガン','V':'ビザ','MA':'マスターカード','UNH':'ユナイテッドヘルス','JNJ':'J&J','XOM':'エクソンモービル','WMT':'ウォルマート','PG':'P&G','BAC':'バンク・オブ・アメリカ','HD':'ホームデポ','CVX':'シェブロン','ABBV':'アッヴィ','MRK':'メルク','KO':'コカ・コーラ','PEP':'ペプシコ','AVGO':'ブロードコム','COST':'コストコ','CRM':'セールスフォース','AMD':'AMD','INTC':'インテル','QCOM':'クアルコム','TXN':'テキサスインスツルメンツ','GS':'ゴールドマン・サックス','MS':'モルガン・スタンレー','C':'シティグループ','WFC':'ウェルズ・ファーゴ','NFLX':'ネットフリックス','ADBE':'アドビ','ORCL':'オラクル','IBM':'IBM','GE':'GE','F':'フォード','GM':'GM','BA':'ボーイング','CAT':'キャタピラー','HON':'ハネウェル','RTX':'レイセオン','LMT':'ロッキード・マーティン','UPS':'UPS','FDX':'フェデックス','DIS':'ディズニー','T':'AT&T','VZ':'ベライゾン','MCD':'マクドナルド','SBUX':'スターバックス','NKE':'ナイキ','AXP':'アメックス','PYPL':'ペイパル','UBER':'ウーバー','SHOP':'ショッピファイ','SNAP':'スナップ','SPOT':'スポティファイ','PLTR':'パランティア','RBLX':'ロブロックス','COIN':'コインベース','ABNB':'エアビーアンドビー','TSM':'TSMC','ASML':'ASML','NVO':'ノボノルディスク','TM':'トヨタ','SONY':'ソニー','HMC':'ホンダ','SMFG':'三井住友FG','MFG':'みずほFG','MTU':'三菱UFJ'};
let FAVS=new Set(JSON.parse(localStorage.getItem('ecfavs')||'[]'));

function saveFavs(){localStorage.setItem('ecfavs',JSON.stringify([...FAVS]));updateFavBadge();}
function favKey(s){return s.code!==undefined?'jp:'+s.code:'us:'+s.ticker;}
function updateFavBadge(){const n=FAVS.size;const el=document.getElementById('fav-cnt');el.textContent=n;el.style.display=n?'':'none';}
function dfmt(x){return`${x.getFullYear()}-${String(x.getMonth()+1).padStart(2,'0')}-${String(x.getDate()).padStart(2,'0')}`;}
function dlabel(ds){const d=new Date(ds+'T00:00:00');return`${d.getMonth()+1}月${d.getDate()}日（${WD[d.getDay()]}）`;}
function sortTimeVal(t){if(!t)return 9999;const m=String(t).match(/(\d{1,2}):(\d{2})/);return m?Number(m[1])*60+Number(m[2]):9999;}
function stockTime(m,s){return m==='jp'?(s.time||'—'):(TL[s.ct]||s.ct||'—');}
function stockCode(m,s){return m==='jp'?s.code:s.ticker;}
function stockName(m,s){return m==='jp'?s.name:(JP_US[s.ticker]||s.name||s.ticker);}
function dayItems(ds){
  const ev=DATA[ds]||{};
  const jp=[...(ev.jp||[])].sort((a,b)=>(b.mv||0)-(a.mv||0)).slice(0,6).map(s=>({type:'stock',market:'jp',id:s.code,time:stockTime('jp',s),label:s.name,meta:`${s.code} · ${s.mcap||''}`,major:s.major}));
  const us=[...(ev.us||[])].sort((a,b)=>(b.mv||0)-(a.mv||0)).slice(0,6).map(s=>({type:'stock',market:'us',id:s.ticker,time:stockTime('us',s),label:s.ticker,meta:`${JP_US[s.ticker]||s.name||''} · ${s.mcap||''}`,major:s.major}));
  const ex=(ev.events||[]).map((e,i)=>({type:'event',idx:i,time:e.time||'—',label:`${e.flag} ${e.name}`,meta:e.country_name}));
  return [...jp,...us,...ex].sort((a,b)=>sortTimeVal(a.time)-sortTimeVal(b.time));
}
function nextScheduleDate(){
  return Object.keys(DATA).sort().find(ds=>ds>=META.today&&dayItems(ds).length) || META.today;
}
function openDetail(type, ds, market, id){
  const ev=DATA[ds]||{};
  let title='', sub='', rows=[];
  if(type==='event'){
    const e=(ev.events||[])[Number(id)];
    if(!e)return;
    title=`${e.flag} ${e.name}`; sub=dlabel(ds);
    rows=[['日付',dlabel(ds)],['時刻',e.time||'—'],['国',e.country_name],['種別','経済指標'],['解説',e.commentary||'—']];
  }else{
    const s=((ev[market]||[]).find(x=>(market==='jp'?x.code:x.ticker)===id));
    if(!s)return;
    title=`${market==='jp'?'🇯🇵':'🇺🇸'} ${stockName(market,s)}`;
    sub=dlabel(ds);
    const same=[...(ev[market]||[])].filter(x=>x.major||Number(x.mv)>1e12).slice(0,5).map(x=>market==='jp'?x.name:x.ticker).join('、')||'—';
    rows=[['日付',dlabel(ds)],['発表時間',stockTime(market,s)],['コード',stockCode(market,s)],['時価総額',s.mcap||'—'],['同日大型銘柄',same]];
  }
  document.getElementById('modal-title').innerHTML=title;
  document.getElementById('modal-sub').textContent=sub;
  document.getElementById('modal-body').innerHTML=rows.map(r=>`<div class="md-row"><span class="md-k">${r[0]}</span><span class="md-v">${r[1]}</span></div>`).join('');
  document.getElementById('detail-modal').classList.add('show');
}
function closeDetail(ev){if(ev&&ev.target.id!=='detail-modal')return;document.getElementById('detail-modal').classList.remove('show');}
function importWatchFromUrl(){
  const p=new URLSearchParams(location.search); const w=p.get('watch'); if(!w)return;
  w.split(',').map(x=>x.trim()).filter(Boolean).forEach(x=>{
    const up=x.toUpperCase();
    let found=false;
    Object.values(DATA).forEach(ev=>{
      (ev.jp||[]).forEach(s=>{if(s.code===up){FAVS.add('jp:'+s.code);found=true;}});
      (ev.us||[]).forEach(s=>{if(s.ticker===up){FAVS.add('us:'+s.ticker);found=true;}});
    });
    if(!found&&/^[A-Z.]+$/.test(up))FAVS.add('us:'+up);
  });
  saveFavs();
}
function copyWatchUrl(){
  const codes=[...FAVS].map(k=>k.split(':')[1]).join(',');
  const u=new URL(location.href); if(codes)u.searchParams.set('watch',codes); else u.searchParams.delete('watch');
  navigator.clipboard?.writeText(u.toString());
}

function showMarket(m,el){
  document.querySelectorAll('.mpanel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.mtab').forEach(t=>t.classList.remove('active'));
  document.getElementById('mpanel-'+m).classList.add('active');
  el.classList.add('active');
  if(m==='us') el.classList.add('us');
  if(m==='fav') buildFavList();
}
function showView(market,view,el){
  const panel=document.getElementById('mpanel-'+market);
  panel.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
  panel.querySelectorAll('.stab').forEach(t=>t.classList.remove('active'));
  document.getElementById('view-'+market+'-'+view).classList.add('active');
  el.classList.add('active');
}

function filterStocks(q){
  q=q.toLowerCase().trim();
  document.querySelectorAll('.bj,.bu').forEach(el=>{
    if(!q){el.classList.remove('dim');return;}
    el.classList.toggle('dim',!(el.textContent+el.title).toLowerCase().includes(q));
  });
  document.querySelectorAll('#tbl-jp tr,#tbl-us tr').forEach(tr=>{
    if(tr.querySelector('th')){tr.style.display='';return;}
    tr.style.display=(!q||tr.textContent.toLowerCase().includes(q))?'':'none';
  });
  document.querySelectorAll('#events-list .ag-day').forEach(day=>{
    day.style.display=(!q||day.textContent.toLowerCase().includes(q))?'':'none';
  });
  document.querySelectorAll('#months-events .sc2').forEach(cell=>{
    if(cell.querySelector('.dn2')) cell.style.opacity=(!q||cell.textContent.toLowerCase().includes(q))?'':'0.18';
  });
}

function badgeJP(s){
  const t=s.time?`<span class="btime">${s.time}</span>`:'';
  const mc=s.major?'bj major':'bj';
  const tip=`${s.name}（${s.code}）${s.kind} ${s.mcap}`;
  return `<div class="${mc}" title="${tip}" data-fk="jp:${s.code}">${s.name}<span class="bcode">${s.code}</span>${t}</div>`;
}
function badgeUS(s){
  const tl=TL[s.ct]||s.ct||'';
  const t=tl?`<span class="btime">${tl}</span>`:'';
  const mc=s.major?'bu major':'bu';
  const tip=`${s.name}（${s.ticker}）EPS:${s.eps} ${s.mcap}`;
  return `<div class="${mc}" title="${tip}" data-fk="us:${s.ticker}">${s.ticker}${t}</div>`;
}
function drJP(s){return`<div class="dr"><span class="dc2">${s.name}</span><span class="dt">${s.time||'—'}</span><span class="dm">${s.mcap}</span></div>`;}
function drUS(s){const tl=TL[s.ct]||s.ct||'—';return`<div class="dr"><span class="dc2">${s.ticker}</span><span class="dt">${tl}</span><span class="dm">${s.mcap}</span></div>`;}

function buildTableCell(dateStr,ev,market){
  const isToday=dateStr===META.today;
  const isPast=dateStr<META.today;
  const day=parseInt(dateStr.slice(8));
  const holidays=market==='jp'?JP_HOLIDAYS:US_HOLIDAYS;
  if(holidays.has(dateStr)){
    return`<td class="sc2${isPast?' past':''} holiday-cell"><div class="dn2">${day}</div><div class="holiday-label">休場日</div></td>`;
  }
  const stocks=(ev&&ev[market])||[];
  const SHOW=10;
  const topEntries=stocks.map((s,i)=>({s,i})).sort((a,b)=>{
    const av=Number(a.s.mv)||0, bv=Number(b.s.mv)||0;
    if(bv!==av) return bv-av;
    return a.i-b.i;
  }).slice(0,SHOW);
  const topSet=new Set(topEntries.map(x=>x.i));
  const visible=topEntries.map(x=>x.s);
  const hidden=stocks.filter((_,i)=>!topSet.has(i));
  function sname(s){
    if(market==='jp') return `<span onclick="openDetail('stock','${dateStr}','jp','${s.code}')">${s.name}<span class="tgc">${s.code}</span></span>`;
    return `<span onclick="openDetail('stock','${dateStr}','us','${s.ticker}')">${JP_US[s.ticker]?`${s.ticker} ${JP_US[s.ticker]}`:s.ticker}</span>`;
  }
  function groupByTime(list){
    const g={};
    list.forEach(s=>{
      const t=market==='jp'?(s.time||''):(TL[s.ct]||s.ct||'');
      if(!g[t])g[t]=[];
      g[t].push(sname(s));
    });
    return g;
  }
  function renderGroups(g){
    return Object.keys(g).sort((a,b)=>!a?1:!b?-1:a.localeCompare(b)).map(t=>
      `<div class="tg"><span class="tgt">${t||'—'}</span><span class="tgn">${g[t].join('、')}</span></div>`
    ).join('');
  }
  let inner=`<div class="dn2">${day}</div>`;
  inner+=renderGroups(groupByTime(visible));
  if(hidden.length>0){
    inner+=`<details class="tg-more"><summary>＋${hidden.length}社</summary>${renderGroups(groupByTime(hidden))}</details>`;
  }
  const cls='sc2'+(isToday?' today':isPast?' past':'')+(stocks.length?'':' no-data');
  return`<td class="${cls}">${inner}</td>`;
}

function buildCalendar(market){
  const today=new Date(META.today+'T00:00:00');
  const ms=document.getElementById('months-'+market);
  const nav=document.getElementById('nav-'+market);
  const isUS=market==='us';
  const nowDate=new Date();
  const nowDow=nowDate.getDay();
  let curRef=new Date(nowDate.getFullYear(),nowDate.getMonth(),nowDate.getDate());
  if(nowDow===6) curRef.setDate(curRef.getDate()+2);
  else if(nowDow===0) curRef.setDate(curRef.getDate()+1);
  const curRefStr=dfmt(curRef);
  const monthIds=[];
  for(let mi=0;mi<3;mi++){
    const y=today.getFullYear(),mo=today.getMonth()+mi;
    const d=new Date(y,mo,1);
    const yr=d.getFullYear(),mth=d.getMonth();
    const ndays=new Date(yr,mth+1,0).getDate();
    const weeks=[];
    let wk=Array(5).fill(null);
    for(let dn=1;dn<=ndays;dn++){
      const ds=`${yr}-${String(mth+1).padStart(2,'0')}-${String(dn).padStart(2,'0')}`;
      const dow=new Date(ds+'T00:00:00').getDay();
      if(dow===0||dow===6)continue;
      const col=dow-1;
      if(col===0&&wk.some(x=>x)){weeks.push(wk);wk=Array(5).fill(null);}
      wk[col]=ds;
    }
    if(wk.some(x=>x))weeks.push(wk);
    let rows='';
    weeks.forEach(wk=>{
      const isCur=wk.some(ds=>ds===curRefStr);
      let cells='';
      wk.forEach(ds=>{cells+=ds?buildTableCell(ds,DATA[ds],market):'<td class="sc2 empty-cell"></td>';});
      rows+=`<tr${isCur?' class="week-cur"':''}>${cells}</tr>`;
    });
    let cnt=0;
    for(let dn=1;dn<=ndays;dn++){
      const ds=`${yr}-${String(mth+1).padStart(2,'0')}-${String(dn).padStart(2,'0')}`;
      const ev=DATA[ds];if(ev)cnt+=(ev[market]||[]).length;
    }
    const mid=`m${market}${yr}${String(mth+1).padStart(2,'0')}`;
    monthIds.push({id:mid,label:`${yr}年${mth+1}月`});
    const sec=document.createElement('div');
    sec.className='month';sec.id=mid;
    sec.innerHTML=`<h3>${yr}年${mth+1}月<span class="mc">${cnt}社</span></h3><table class="cal-tbl"><thead><tr><th>月</th><th>火</th><th>水</th><th>木</th><th>金</th></tr></thead><tbody>${rows}</tbody></table>`;
    ms.appendChild(sec);
  }
  monthIds.forEach((m,i)=>{
    const b=document.createElement('button');
    b.className='mnbtn'+(i===0?' active':'')+(isUS?' us':'');
    b.textContent=m.label;
    b.onclick=()=>{
      document.querySelectorAll('#nav-'+market+' .mnbtn').forEach(x=>x.classList.remove('active'));
      b.classList.add('active');
      document.getElementById(m.id).scrollIntoView({behavior:'smooth',block:'start'});
    };
    nav.appendChild(b);
  });
}

function buildSpotlight(market){
  const today=META.today;
  const d=new Date(today+'T00:00:00');
  const dow=(d.getDay()+6)%7;
  const ws=new Date(d); ws.setDate(d.getDate()-dow);
  const we=new Date(ws); we.setDate(ws.getDate()+13);
  const wsStr=dfmt(ws), weStr=dfmt(we);
  const rangeLabel=`${wsStr.slice(5).replace('-','/')} 〜 ${weStr.slice(5).replace('-','/')}`;
  document.getElementById('range-'+market).textContent=rangeLabel;
  let cards='';
  Object.keys(DATA).sort().forEach(ds=>{
    if(ds<today||ds>weStr) return;
    const ev=DATA[ds];
    const dd=new Date(ds+'T00:00:00');
    const dlabel=`${dd.getMonth()+1}月${dd.getDate()}日（${WD[dd.getDay()]}）`;
    (ev[market]||[]).forEach(s=>{
      if(!s.major) return;
      const k=favKey(s);
      const isFav=FAVS.has(k);
      const fstar=`<span class="sfav${isFav?' on':''}" data-fk="${k}" onclick="toggleFavCard(this)">${isFav?'★':'☆'}</span>`;
      if(market==='jp'){
        cards+=`<div class="scard jp"><div class="sc-date">${dlabel}</div><div class="sc-name">${s.name}</div><div class="sc-sub">${s.code} · ${s.mcap}</div><div class="sc-time">${s.time?`<span class="tamc">${s.time}</span>`:''}</div>${fstar}</div>`;
      } else {
        const tl=TL[s.ct]||s.ct||'';
        const tb=tl==='開場前'?`<span class="tbmo">${tl}</span>`:tl?`<span class="tamc">${tl}</span>`:'';
        cards+=`<div class="scard us"><div class="sc-date">${dlabel}</div><div class="sc-name">${s.ticker}</div><div class="sc-sub">${s.name} · ${s.mcap}</div><div class="sc-time">${tb}</div>${fstar}</div>`;
      }
    });
  });
  document.getElementById('spot-'+market).innerHTML=cards||'<span style="color:#9ca3af;font-size:0.82rem">主要銘柄の決算はありません</span>';
}

function toggleFavCard(el){
  const k=el.dataset.fk;
  if(FAVS.has(k)){FAVS.delete(k);el.textContent='☆';el.classList.remove('on');}
  else{FAVS.add(k);el.textContent='★';el.classList.add('on');}
  saveFavs();
}

function buildWeekChip(){
  const d=new Date(META.today+'T00:00:00');
  const dow=(d.getDay()+6)%7;
  const ws=new Date(d); ws.setDate(d.getDate()-dow);
  const we=new Date(ws); we.setDate(ws.getDate()+4);
  let jp=0,us=0;
  Object.keys(DATA).forEach(ds=>{
    if(ds<dfmt(ws)||ds>dfmt(we)) return;
    const ev=DATA[ds]; jp+=(ev.jp||[]).length; us+=(ev.us||[]).length;
  });
  document.getElementById('cweek').textContent=`今週 JP ${jp}社 / US ${us}社`;
}

function buildMarketDashboard(){
  const base=new Date(META.today+'T00:00:00');
  const monday=new Date(base); monday.setDate(base.getDate()-((base.getDay()+6)%7));
  const friday=new Date(monday); friday.setDate(monday.getDate()+4);
  const start=dfmt(base)>dfmt(monday)?base:monday;
  const source=META.bbs_updated?`Yahoo掲示板投稿数ランキング ${META.bbs_updated} 更新`:'Yahoo掲示板投稿数ランキング + 決算規模';
  document.getElementById('attention-source').textContent=source;
  function scoreJP(s, dayIndex){
    const buzz=s.buzz||0;
    const reasons=[];
    let raw=0;
    if(buzz){raw+=(110-buzz)*6; reasons.push(`Yahoo掲示板${buzz}位`);}
    if(s.major){raw+=80; reasons.push('主要銘柄');}
    raw+=Math.min(80,Math.log10(Number(s.mv)||1)*5);
    raw+=Math.max(0,6-dayIndex)*8;
    const score=Math.max(1,Math.min(100,Math.round(raw/8)));
    return {score,reasons:reasons.join(' · ')||'時価総額上位'};
  }
  function scoreUS(s, dayIndex){
    const reasons=[];
    let raw=0;
    if(s.major){raw+=75; reasons.push('主要米国株');}
    raw+=Math.min(75,Math.log10(Number(s.mv)||1)*5);
    raw+=Math.max(0,6-dayIndex)*6;
    const score=Math.max(1,Math.min(100,Math.round(raw/2)));
    return {score,reasons:reasons.join(' · ')||'時価総額上位'};
  }
  function collectPicks(fromDate, toDate){
    const picks=[];
    const from=new Date(fromDate+'T00:00:00');
    const to=new Date(toDate+'T00:00:00');
    for(let cur=new Date(from), i=0; cur<=to; cur.setDate(cur.getDate()+1), i++){
      const key=dfmt(cur);
      const ev=DATA[key]||{};
      (ev.jp||[]).forEach(s=>{
        if(!s.buzz&&!s.major&&Number(s.mv)<8e11) return;
        const scored=scoreJP(s,i);
        picks.push({market:'jp',id:s.code,name:s.name,code:s.code,ds:key,time:s.time||'—',score:scored.score,reason:scored.reasons,mcap:s.mcap||''});
      });
      (ev.us||[]).forEach(s=>{
        if(!s.major&&Number(s.mv)<2e11) return;
        const scored=scoreUS(s,i);
        picks.push({market:'us',id:s.ticker,name:s.ticker,code:s.ticker,ds:key,time:TL[s.ct]||s.ct||'—',score:scored.score,reason:scored.reasons,mcap:s.mcap||''});
      });
    }
    return picks.sort((a,b)=>b.score-a.score);
  }
  function renderRanking(elId, rangeId, titleEmpty, fromDate, toDate, limit){
    const picks=collectPicks(fromDate,toDate).slice(0,limit);
    document.getElementById(rangeId).textContent=fromDate===toDate?dlabel(fromDate):`${fromDate.slice(5).replace('-','/')} 〜 ${toDate.slice(5).replace('-','/')}`;
    document.getElementById(elId).innerHTML=picks.length?picks.map((x,idx)=>`<div class="attention-card ${x.market==='us'?'us':''}" onclick="openDetail('stock','${x.ds}','${x.market}','${x.id}')">
      <div class="att-top"><span class="att-place">${idx+1}位</span><span class="att-rank">注目度 ${x.score}/100</span></div>
      <div class="att-name">${x.market==='jp'?'🇯🇵':'🇺🇸'} ${x.name}<span class="att-code">${x.code}</span></div>
      <div class="att-meta">${dlabel(x.ds)} · ${x.time} · ${x.mcap}</div>
      <div class="att-reason">${x.reason}</div>
    </div>`).join(''):`<div class="events-empty">${titleEmpty}</div>`;
  }
  const tomorrow=new Date(base); tomorrow.setDate(base.getDate()+1);
  const nextMonday=new Date(monday); nextMonday.setDate(monday.getDate()+7);
  const nextFriday=new Date(nextMonday); nextFriday.setDate(nextMonday.getDate()+4);
  renderRanking('attention-tomorrow','attention-tomorrow-range','明日の注目銘柄はありません',dfmt(tomorrow),dfmt(tomorrow),5);
  renderRanking('attention-week','attention-week-range','今週注目の銘柄はありません',dfmt(start),dfmt(friday),10);
  renderRanking('attention-next','attention-next-range','来週の注目銘柄はありません',dfmt(nextMonday),dfmt(nextFriday),10);
}
function showDateDetail(ds){
  document.getElementById('modal-title').textContent=dlabel(ds);
  document.getElementById('modal-sub').textContent='予定一覧';
  document.getElementById('modal-body').innerHTML=dayItems(ds).slice(0,20).map(x=>`<div class="md-row"><span class="md-k">${x.time}</span><span class="md-v">${x.label}</span></div>`).join('');
  document.getElementById('detail-modal').classList.add('show');
}

function buildImportantEvents(){
  const today=META.today;
  const dsKeys=Object.keys(DATA).sort().filter(ds=>ds>=today&&((DATA[ds].events||[]).length));
  const list=document.getElementById('events-list');
  const months=document.getElementById('months-events');
  const nav=document.getElementById('nav-events');
  const range=document.getElementById('range-events');
  list.innerHTML='';
  months.innerHTML='';
  nav.innerHTML='';
  if(!dsKeys.length){
    range.textContent='日本・米国';
    months.innerHTML='<div class="events-empty">経済指標データはありません</div>';
    list.innerHTML='<div class="events-empty">経済指標データはありません</div>';
    return;
  }
  range.textContent=`${dsKeys[0].slice(5).replace('-','/')} 〜 ${dsKeys[dsKeys.length-1].slice(5).replace('-','/')} · ${META.total_events||0}件`;
  function eventName(e, ds, idx){
    return `<span onclick="openDetail('event','${ds}','',${idx})"><span class="evflag">${e.flag}</span>${e.name}</span>`;
  }
  function groupEvents(list, ds){
    return [...list].sort((a,b)=>{
      const av=Number(a.time?.replace(':',''))||9999;
      const bv=Number(b.time?.replace(':',''))||9999;
      if(av!==bv) return av-bv;
      return (a.country||'').localeCompare(b.country||'') || (a.name||'').localeCompare(b.name||'');
    }).map(e=>
      `<div class="tg"><span class="tgt">${e.time||'—'}</span><span class="tgn">${eventName(e,ds,(DATA[ds].events||[]).indexOf(e))}</span></div>`
    ).join('');
  }
  function eventCell(ds, yr, mth){
    const ev=DATA[ds];
    const items=(ev&&ev.events)||[];
    const day=parseInt(ds.slice(8));
    const isToday=ds===META.today;
    const isPast=ds<META.today;
    const cls='sc2'+(isToday?' today':isPast?' past':'')+(items.length?'':' no-data');
    return `<td class="${cls}"><div class="dn2">${day}</div>${groupEvents(items,ds)}</td>`;
  }
  const todayDate=new Date(today+'T00:00:00');
  const monthIds=[];
  for(let mi=0;mi<3;mi++){
    const base=new Date(todayDate.getFullYear(),todayDate.getMonth()+mi,1);
    const yr=base.getFullYear(), mth=base.getMonth();
    const ndays=new Date(yr,mth+1,0).getDate();
    const weeks=[];
    let wk=Array(5).fill(null);
    for(let dn=1;dn<=ndays;dn++){
      const ds=`${yr}-${String(mth+1).padStart(2,'0')}-${String(dn).padStart(2,'0')}`;
      const dow=new Date(ds+'T00:00:00').getDay();
      if(dow===0||dow===6) continue;
      const col=dow-1;
      if(col===0&&wk.some(x=>x)){weeks.push(wk);wk=Array(5).fill(null);}
      wk[col]=ds;
    }
    if(wk.some(x=>x)) weeks.push(wk);
    let rows='';
    weeks.forEach(wk=>{
      let cells='';
      wk.forEach(ds=>{cells+=ds?eventCell(ds,yr,mth):'<td class="sc2 empty-cell"></td>';});
      rows+=`<tr>${cells}</tr>`;
    });
    let cnt=0;
    for(let dn=1;dn<=ndays;dn++){
      const ds=`${yr}-${String(mth+1).padStart(2,'0')}-${String(dn).padStart(2,'0')}`;
      cnt+=((DATA[ds]||{}).events||[]).length;
    }
    const mid=`mevents${yr}${String(mth+1).padStart(2,'0')}`;
    monthIds.push({id:mid,label:`${yr}年${mth+1}月`});
    const sec=document.createElement('div');
    sec.className='month'; sec.id=mid;
    sec.innerHTML=`<h3>${yr}年${mth+1}月<span class="mc">${cnt}件</span></h3><table class="cal-tbl"><thead><tr><th>月</th><th>火</th><th>水</th><th>木</th><th>金</th></tr></thead><tbody>${rows}</tbody></table>`;
    months.appendChild(sec);
  }
  monthIds.forEach((m,i)=>{
    const b=document.createElement('button');
    b.className='mnbtn'+(i===0?' active':'');
    b.textContent=m.label;
    b.onclick=()=>{
      document.querySelectorAll('#nav-events .mnbtn').forEach(x=>x.classList.remove('active'));
      b.classList.add('active');
      document.getElementById(m.id).scrollIntoView({behavior:'smooth',block:'start'});
    };
    nav.appendChild(b);
  });
  let html='';
  dsKeys.forEach(ds=>{
    const d=new Date(ds+'T00:00:00');
    const dow=d.getDay();
    const isToday=ds===today;
    const label=`${d.getMonth()+1}月${d.getDate()}日（${WD[dow]}）`;
    const dateCls='ag-head-date'+(dow===6?' sat':dow===0?' sun':'');
    const dayCls='ag-day'+(isToday?' ag-today':'');
    const items=(DATA[ds].events||[]).map((e,idx)=>`
      <div class="event-item">
        <span class="event-time">${e.time||'—'}</span>
        <span class="event-flag">${e.flag}</span>
        <span class="event-copy" onclick="openDetail('event','${ds}','',${idx})">
          <span class="event-name">${e.name}</span>
          <span class="event-note">${e.commentary||''}</span>
        </span>
      </div>`).join('');
    html+=`<div class="${dayCls}">
      <div class="ag-head">
        <span class="${dateCls}">${label}</span>
        <span class="ag-cnt">${(DATA[ds].events||[]).length}件</span>
      </div>
      ${items}
    </div>`;
  });
  list.innerHTML=html;
}

function buildList(market){
  const isJP=market==='jp';
  const th=isJP
    ?'<tr><th>日付</th><th>企業名</th><th>コード</th><th>決算種別</th><th>発表時間</th><th>時価総額</th></tr>'
    :'<tr><th>日付</th><th>企業名</th><th>ティッカー</th><th>発表時間</th><th>EPS予想</th><th>時価総額</th></tr>';
  let rows='';
  Object.keys(DATA).sort().forEach(ds=>{
    if(ds<META.today) return;
    const d=new Date(ds+'T00:00:00');
    const label=`${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')}(${['日','月','火','水','木','金','土'][d.getDay()]})`;
    const ev=DATA[ds];
    if(isJP)(ev.jp||[]).forEach(s=>{
      const mk=s.major?'★ ':''; const rc=s.major?' class="mrow"':'';
      rows+=`<tr${rc}><td class="ldc">${label}</td><td>${mk}${s.name}</td><td class="ltc">${s.code}</td><td class="ltc">${s.kind}</td><td class="ltc">${s.time||'—'}</td><td class="ltc">${s.mcap}</td></tr>`;
    });
    else (ev.us||[]).forEach(s=>{
      const tl=TL[s.ct]||s.ct||'—'; const mk=s.major?'★ ':''; const rc=s.major?' class="mrow"':'';
      rows+=`<tr${rc}><td class="ldc">${label}</td><td>${mk}${s.name}</td><td class="ltc">${s.ticker}</td><td class="ltc">${tl}</td><td class="ltc">${s.eps||'—'}</td><td class="ltc">${s.mcap}</td></tr>`;
    });
  });
  if(!rows) rows='<tr><td colspan="6" style="text-align:center;color:#9ca3af;padding:24px">データなし</td></tr>';
  document.getElementById('tbl-'+market).innerHTML=`<table><thead>${th}</thead><tbody>${rows}</tbody></table>`;
}

function buildFavList(){
  if(!FAVS.size){
    document.getElementById('fav-list').innerHTML='<div class="fav-empty">★ お気に入りはまだありません<br><small style="display:block;margin-top:6px;color:#9ca3af">注目カードの☆をクリックして登録できます</small></div>';
    return;
  }
  const items=[];
  Object.keys(DATA).sort().forEach(ds=>{
    if(ds<META.today) return;
    const ev=DATA[ds];
    const d=new Date(ds+'T00:00:00');
    const diffDays=Math.round((d-new Date(META.today+'T00:00:00'))/86400000);
    const label=`${d.getMonth()+1}月${d.getDate()}日（${WD[d.getDay()]}）`;
    (ev.jp||[]).forEach(s=>{if(FAVS.has('jp:'+s.code)) items.push({label,diffDays,name:`🇯🇵 ${s.name}（${s.code}）`,sub:`${s.kind} · ${s.time||'時間未定'} · ${s.mcap}`,fk:'jp:'+s.code,ds,market:'jp',id:s.code});});
    (ev.us||[]).forEach(s=>{if(FAVS.has('us:'+s.ticker)) items.push({label,diffDays,name:`🇺🇸 ${s.name}（${s.ticker}）`,sub:`Q決算 · ${TL[s.ct]||s.ct||'時間未定'} · ${s.mcap}`,fk:'us:'+s.ticker,ds,market:'us',id:s.ticker});});
  });
  if(!items.length){document.getElementById('fav-list').innerHTML='<div class="fav-empty">登録銘柄の決算は取得期間にありません</div>';return;}
  document.getElementById('fav-list').innerHTML='<div class="fav-wrap">'+items.map(it=>`
    <div class="fav-item">
      <div onclick="openDetail('stock','${it.ds}','${it.market}','${it.id}')" style="cursor:pointer"><div class="fi-name">${it.name}</div><div class="fi-sub">${it.sub}</div></div>
      <div class="fi-right">
        <div class="fi-date">${it.label}</div>
        <div class="fi-days">📅 あと${it.diffDays}日</div>
        <div class="fi-del" onclick="removeFav('${it.fk}')">★ 解除</div>
      </div>
    </div>`).join('')+'</div>';
}
function removeFav(k){FAVS.delete(k);saveFavs();buildFavList();}

function buildAgenda(market){
  const isJP=market==='jp';
  const today=META.today;
  const top=META.top;
  function topByMcap(list){
    return list.map((s,i)=>({s,i})).sort((a,b)=>{
      const av=Number(a.s.mv)||0, bv=Number(b.s.mv)||0;
      if(bv!==av) return bv-av;
      return a.i-b.i;
    }).slice(0,top);
  }
  function stockLabel(s){
    if(isJP) return `${s.name}<span class="ag-code">${s.code}</span>`;
    return `${s.name}<span class="ag-code">${s.ticker}</span>`;
  }
  function groupByAgendaTime(list){
    const groups={};
    list.forEach(s=>{
      const t=isJP?(s.time||''):(TL[s.ct]||s.ct||'');
      if(!groups[t]) groups[t]=[];
      groups[t].push(s);
    });
    return Object.keys(groups).sort((a,b)=>!a?1:!b?-1:a.localeCompare(b)).map(t=>({time:t,stocks:groups[t]}));
  }
  function agendaGroups(list, extra){
    const extraAttrs=extra?' data-extra="1" style="display:none"':'';
    return groupByAgendaTime(list).map(g=>{
      const isMajor=g.stocks.some(s=>s.major);
      const names=g.stocks.map(stockLabel).join('、');
      return `<div class="ag-item${isJP?'':' us-item'}${isMajor?' major-item':''}"${extraAttrs}>
        <span class="ag-time">${g.time||'—'}</span>
        <span class="ag-names">${names}</span>
      </div>`;
    }).join('');
  }
  let html='';
  Object.keys(DATA).sort().forEach(ds=>{
    if(ds<today) return;
    const ev=DATA[ds];
    const stocks=(ev[market]||[]);
    if(!stocks.length) return;
    const d=new Date(ds+'T00:00:00');
    const dow=d.getDay();
    const isToday=ds===today;
    const dowLabel=['日','月','火','水','木','金','土'][dow];
    const dateCls='ag-head-date'+(dow===6?' sat':dow===0?' sun':'');
    const dayCls='ag-day'+(isToday?' ag-today':'');
    const label=`${d.getMonth()+1}月${d.getDate()}日（${dowLabel}）`;
    const topEntries=topByMcap(stocks);
    const topSet=new Set(topEntries.map(x=>x.i));
    const topStocks=topEntries.map(x=>x.s);
    const restStocks=stocks.filter((_,i)=>!topSet.has(i));
    const items=agendaGroups(topStocks,false);
    const hiddenItems=agendaGroups(restStocks,true);
    const rest=restStocks.length;
    const moreHtml=rest>0?`<div class="ag-more" data-count="${rest}" onclick="toggleAgendaMore(this)">＋${rest}社を表示</div>`:'';
    html+=`<div class="${dayCls}">
      <div class="ag-head">
        <span class="${dateCls}">${label}</span>
        <span class="ag-cnt">${stocks.length}社</span>
      </div>
      ${items}${hiddenItems}${moreHtml}
    </div>`;
  });
  document.getElementById('agenda-'+market).innerHTML=html||'<div style="text-align:center;color:#9ca3af;padding:32px">データなし</div>';
}

function toggleAgendaMore(btn){
  const day=btn.closest('.ag-day');
  const open=btn.dataset.open==='1';
  day.querySelectorAll('.ag-item[data-extra="1"]').forEach(el=>el.style.display=open?'none':'');
  btn.dataset.open=open?'0':'1';
  btn.textContent=open?`＋${btn.dataset.count}社を表示`:'閉じる';
}

function switchView(market,view,el){
  const toggle=document.getElementById('vtoggle-'+market);
  toggle.querySelectorAll('.vtbtn').forEach(b=>b.classList.remove('active'));
  el.classList.add('active');
  const months=document.getElementById('months-'+market);
  const agenda=document.getElementById('agenda-'+market);
  const nav=document.getElementById('nav-'+market);
  if(view==='agenda'){
    months.style.display='none';
    if(nav) nav.style.display='none';
    agenda.style.display='flex';
  } else {
    months.style.display='';
    if(nav) nav.style.display='';
    agenda.style.display='none';
  }
}

// 初期化
document.getElementById('cjp').textContent=`🇯🇵 日本株 ${META.total_jp}社`;
document.getElementById('cus').textContent=`🇺🇸 米国株 ${META.total_us}社`;
document.getElementById('upd').textContent=`最終更新: ${META.updated}　★=主要銘柄`;
importWatchFromUrl();
updateFavBadge();
buildWeekChip();
buildMarketDashboard();
buildCalendar('jp');
buildCalendar('us');
buildImportantEvents();
buildList('jp');
buildList('us');
buildAgenda('jp');
buildAgenda('us');
</script>
</body>
</html>"""

    html = html.replace("__DATA_VER__", data_ver)
    return html, data_js

# ─────────────────────────────────────────────
# GitHub Pages へ自動アップロード（オプション）
# ─────────────────────────────────────────────

def upload_to_github(html, data_js):
    import base64
    token = os.getenv("GITHUB_TOKEN", "")
    repo  = os.getenv("GITHUB_REPO", "")
    if not token or not repo:
        return None

    hdr = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

    def put_file(path, content_str):
        api = f"https://api.github.com/repos/{repo}/contents/{path}"
        r = requests.get(api, headers=hdr)
        sha = r.json().get("sha", "") if r.status_code == 200 else ""
        body = {"message": f"Update {path}",
                "content": base64.b64encode(content_str.encode()).decode()}
        if sha: body["sha"] = sha
        r = requests.put(api, headers=hdr, json=body)
        return r.status_code in (200, 201)

    ok1 = put_file("index.html", html)
    ok2 = put_file("data.js", data_js)
    if ok1 and ok2:
        user  = repo.split("/")[0]
        rname = repo.split("/")[1]
        return f"https://{user}.github.io/{rname}/"
    print(f"  GitHub アップロード失敗")
    return None

# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────

def main():
    import sys
    local_only = "--local" in sys.argv or os.getenv("GITHUB_ACTIONS") == "true"
    all_events = {}

    print("【日本株】irbank.net から取得中...")
    traders_times = fetch_traders_times()
    print(f"  Traders時刻 {sum(len(v) for v in traders_times.values())}件を取得")
    jp_dates = fetch_irbank_dates()
    print(f"  {len(jp_dates)} 日分をプローブ")
    for date in jp_dates:
        print(f"  {date.strftime('%m/%d')} ...", end="", flush=True)
        stocks = fetch_irbank_day(date)
        if stocks and date in traders_times:
            tmap = traders_times[date]
            for stock in stocks:
                if stock["code"] in tmap:
                    stock["time"] = tmap[stock["code"]]
            stocks.sort(key=lambda s: (time_sort_value(s["time"]), -s["mcap_val"]))
        if stocks:
            all_events.setdefault(date, {"jp":[],"us":[]})["jp"] = stocks
        print(f" {len(stocks)}社")
        time.sleep(0.8)

    print("\n【米国株】Nasdaq API から取得中...")
    weekdays = [TODAY + timedelta(i) for i in range(90) if (TODAY + timedelta(i)).weekday() < 5]
    for date in weekdays:
        print(f"  {date.strftime('%m/%d')} ...", end="", flush=True)
        stocks = fetch_nasdaq_day(date)
        if stocks:
            all_events.setdefault(date, {"jp":[],"us":[]})["us"] = stocks
        print(f" {len(stocks)}社")
        time.sleep(0.5)

    print("\n【重要事項】SBI証券 経済指標から取得中...")
    end_date = TODAY + timedelta(days=89)
    important_events = fetch_important_events(TODAY, end_date)
    imp_total = sum(len(v) for v in important_events.values())
    for date, events in important_events.items():
        all_events.setdefault(date, {"jp":[],"us":[]})["events"] = events
    print(f"  {imp_total}件")

    print("\n【注目度】Yahoo掲示板投稿数ランキングから取得中...")
    global YAHOO_BBS_RANKS
    YAHOO_BBS_RANKS = fetch_yahoo_bbs_ranking()
    print(f"  {len(YAHOO_BBS_RANKS)}銘柄")

    print("\nHTML生成中...")
    html, data_js = build_files(all_events)
    base = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(base, "earnings.html"), "w", encoding="utf-8") as f: f.write(html)
    with open(os.path.join(base, "data.js"),       "w", encoding="utf-8") as f: f.write(data_js)

    total = sum(len(v.get("jp",[])) + len(v.get("us",[])) for v in all_events.values())
    print(f"✅ 完成! {total}件 → earnings.html + data.js")

    if local_only:
        print("（GitHub自動更新モード：アップロードスキップ）")
        return

    url = upload_to_github(html, data_js)
    if url:
        print(f"🌐 GitHub Pages に公開済み: {url}")
        print(f"   ↑ このURLをXに貼り付ければ誰でも見られます")

if __name__ == "__main__":
    main()
