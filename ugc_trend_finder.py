#!/usr/bin/env python3
"""
UGC Trend Finder
================
Looks at what is selling on the Roblox marketplace right now (accessories and
clothing), finds the themes that are in demand, compares that with how many new
items are being uploaded for each theme, and suggests items you could make.

Only uses Python's standard library, so there is nothing to install.

Usage:
    python ugc_trend_finder.py                 # fetch live data, build report, open it
    python ugc_trend_finder.py --pages 5       # look deeper into each list (slower)
    python ugc_trend_finder.py --include-roblox   # also count items made by Roblox itself
    python ugc_trend_finder.py --only accessories # or: --only clothing
    python ugc_trend_finder.py --from-snapshot data/snapshot_....json   # rebuild a report offline

Important: Roblox does not publish exact sales numbers. This tool uses the
order of the "bestselling" lists, favorites and upload activity as signals.
It gives data-backed ideas, not guaranteed sales.
"""

import argparse
import glob
import html
import json
import math
import os
import random
import re
import statistics
import sys
import time
import webbrowser
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

VERSION = "1.7"
API = "https://catalog.roblox.com/v1/search/items/details"
UA = "UGC-Trend-Finder/1.0 (personal market research tool)"
HERE = os.path.dirname(os.path.abspath(__file__))

CATEGORIES = {"accessories": 11, "clothing": 3}

# Which catalog lists we read. "demand" lists say what people buy,
# the "supply" list says what creators are uploading right now.
LISTS = {
    "sales_day":  {"label": "Bestselling (past day)",  "role": "demand", "weight": 1.5,
                   "params": {"SortType": 2, "SortAggregation": 1}},
    "sales_week": {"label": "Bestselling (past week)", "role": "demand", "weight": 1.0,
                   "params": {"SortType": 2, "SortAggregation": 3}},
    "fav_week":   {"label": "Most favorited (past week)", "role": "demand", "weight": 0.5,
                   "params": {"SortType": 1, "SortAggregation": 3}},
    "newest":     {"label": "Recently updated / new uploads", "role": "supply", "weight": 0.0,
                   "params": {"SortType": 3}},
}

# Roblox asset type id -> (key, label, group, blender?)
ASSET_TYPES = {
    8:  ("hat", "Hat", "Head", True),
    41: ("hair", "Hair", "Hair", True),
    42: ("face_acc", "Face accessory", "Face", True),
    43: ("neck", "Neck accessory", "Neck", True),
    44: ("shoulder", "Shoulder accessory", "Shoulder", True),
    45: ("front", "Front accessory", "Front", True),
    46: ("back", "Back accessory", "Back", True),
    47: ("waist", "Waist accessory", "Waist", True),
    64: ("lc_tshirt", "Layered T-shirt", "Clothing", True),
    65: ("lc_shirt", "Layered shirt", "Clothing", True),
    66: ("lc_pants", "Layered pants", "Clothing", True),
    67: ("lc_jacket", "Layered jacket", "Clothing", True),
    68: ("lc_sweater", "Layered sweater", "Clothing", True),
    69: ("lc_shorts", "Layered shorts", "Clothing", True),
    70: ("shoes", "Shoes", "Shoes", True),
    71: ("shoes", "Shoes", "Shoes", True),
    72: ("lc_dress", "Layered dress / skirt", "Clothing", True),
    76: ("eyebrows", "Eyebrows", "Face", True),
    77: ("eyelashes", "Eyelashes", "Face", True),
    2:  ("classic_tshirt", "Classic T-shirt (2D)", "Classic", False),
    11: ("classic_shirt", "Classic shirt (2D)", "Classic", False),
    12: ("classic_pants", "Classic pants (2D)", "Classic", False),
}
TYPE_INFO = {}
for _id, (_k, _l, _g, _b) in ASSET_TYPES.items():
    TYPE_INFO[_k] = {"label": _l, "group": _g, "blender": _b}

# ---------------------------------------------------------------- word lists
STOP = set("""a an the of and or with for to in on at by from my your our his her its it is are be
this that these those x vs ft feat pls plz i me you we they not no so very too
""".split())
GENERIC = set("""ugc roblox limited limiteds accessory accessories item items version edition v1 v2 v3 v4
free new cheap sale best cool epic rare set pack bundle collection style styled aesthetic outfit
fit fits original og remake classic basic simple remastered updated update ver copy variant tm official premium
""".split())
# Type words: dropped as single-word themes (they just repeat the item type)
# but allowed inside two-word themes like "cowboy hat".
TYPE_WORDS = set("""hat hats hair hairs hairstyle shirt shirts pants tshirt tee top tops shoes shoe
accessory face back waist neck shoulder front clothing clothes layered
""".split())
COLORS = {
    "black": "black", "white": "white", "red": "red", "blue": "blue", "green": "green",
    "pink": "pink", "purple": "purple", "yellow": "yellow", "orange": "orange",
    "brown": "brown", "grey": "grey", "gray": "grey", "gold": "gold", "golden": "gold",
    "silver": "silver", "cyan": "cyan", "teal": "teal", "navy": "navy", "beige": "beige",
    "cream": "cream", "lavender": "lavender", "mint": "mint", "rainbow": "rainbow",
    "pastel": "pastel", "neon": "neon", "violet": "purple", "crimson": "red",
    "magenta": "pink", "lilac": "lavender", "blonde": "blonde", "brunette": "brown",
    "ginger": "ginger", "chrome": "chrome", "holographic": "holographic",
}
COLOR_SWATCH = {
    "black": "#1d1d1f", "white": "#f4f4f4", "red": "#d33b3b", "blue": "#3a6fd8",
    "green": "#3aa35b", "pink": "#ee7fb5", "purple": "#8a5cd6", "yellow": "#f1c93b",
    "orange": "#ef8a33", "brown": "#8a5a3b", "grey": "#8e8e93", "gold": "#d4a72c",
    "silver": "#c0c4cc", "cyan": "#35c4d8", "teal": "#2a9d8f", "navy": "#23355c",
    "beige": "#dccaa6", "cream": "#f3e8cf", "lavender": "#b9a6e8", "mint": "#9fe3c4",
    "rainbow": "linear-gradient(90deg,#e44,#f93,#fd3,#4c6,#39f,#96f)",
    "pastel": "linear-gradient(90deg,#fbc,#bdf,#cfc)", "neon": "#39ff88",
    "blonde": "#f0d58a", "ginger": "#c8622c", "chrome": "linear-gradient(90deg,#999,#eee,#888)",
    "holographic": "linear-gradient(90deg,#f9c,#9cf,#cf9,#fc9)",
}
ALIASES = {"headphone": "headphones", "earbud": "earbuds", "wing": "wings", "horn": "horns",
           "kitty": "cat", "kitten": "cat", "bunny": "bunny", "bunnies": "bunny",
           "rabbit": "bunny", "cats": "cat", "bows": "bow", "flowers": "flower",
           "hearts": "heart", "stars": "star", "sunglass": "sunglasses", "glass": "glasses",
           "y2": "y2k", "plushie": "plush", "plushy": "plush", "emo": "emo"}

# Object words: themes that only make sense on certain item types.
OBJECT_GROUPS = {
    "Hair": "hair hairstyle ponytail ponytails pigtails bangs bun buns braids braid curls curly wavy mullet wolfcut fringe updo afro locs dreads".split(),
    "Head": "hat cap beanie crown helmet beret headband tiara halo horns ears antenna bucket fedora cowboy visor hood bonnet headphones earbuds earmuffs".split(),
    "Face": "glasses sunglasses mask shades goggles blush freckles eyepatch piercing piercings lashes eyebrows".split(),
    "Neck": "scarf necklace chain chains choker tie collar bandana".split(),
    "Back": "wings backpack cape sword katana guitar bag quiver".split(),
    "Waist": "belt tail tails".split(),
    "Front": "badge".split(),
    "Clothing": "hoodie jacket sweater jeans skirt dress shorts overalls jersey vest coat cardigan tracksuit uniform corset".split(),
    "Shoes": "sneakers boots heels sandals slippers crocs trainers".split(),
}
OBJECT_WORD_GROUP = {}
for _g, _ws in OBJECT_GROUPS.items():
    for _w in _ws:
        OBJECT_WORD_GROUP.setdefault(_w, set()).add(_g)
OBJECT_WORD_GROUP["tail"].add("Back")
OBJECT_WORD_GROUP["bag"].add("Shoulder")
OBJECT_WORD_GROUP["ears"].add("Hair")


PLURAL = {"hair": "hair items", "lc_pants": "layered pants", "lc_shorts": "layered shorts",
          "lc_dress": "layered dresses / skirts", "shoes": "shoes", "classic_pants": "classic pants (2D)",
          "eyebrows": "eyebrows", "eyelashes": "eyelashes", "classic_tshirt": "classic T-shirts (2D)",
          "classic_shirt": "classic shirts (2D)"}


def plural(k):
    if k in PLURAL:
        return PLURAL[k]
    lab = TYPE_INFO[k]["label"].lower()
    return lab[:-1] + "ies" if lab.endswith("y") else lab + "s"


class ScanCancelled(Exception):
    pass


# The app swaps these hooks out to show progress in its window.
HOOKS = {"log": lambda m: print(m, flush=True), "cancel": None, "event": None}


def log(msg):
    HOOKS["log"](msg)


def emit(event):
    """Structured progress events for the app (waits, steps, page progress)."""
    fn = HOOKS.get("event")
    if fn:
        try:
            fn(event)
        except Exception:
            pass


def check_cancel():
    ev = HOOKS.get("cancel")
    if ev is not None and ev.is_set():
        raise ScanCancelled()


def sleep(seconds):
    end = time.time() + seconds
    while True:
        check_cancel()
        left = end - time.time()
        if left <= 0:
            return
        time.sleep(min(0.2, left))


# ---------------------------------------------------------------- fetching
class BadRequest(Exception):
    pass


# Every request to Roblox goes through throttle(), which keeps a steady gap
# between requests. If Roblox still says "slow down" (429), the gap grows for
# the rest of the scan and we pause for a while before trying again.
RATE = {"gap": 3.0, "last": 0.0, "max_gap": 20.0}


def throttle():
    gap = RATE["gap"] * random.uniform(1.0, 1.35)
    wait = RATE["last"] + gap - time.time()
    if wait > 0:
        sleep(wait)
    RATE["last"] = time.time()


def get_json(url, tries=7):
    last = None
    for attempt in range(tries):
        throttle()
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except HTTPError as e:
            last = e
            if e.code == 400:
                raise BadRequest(str(e))
            if e.code in (429, 500, 502, 503, 504):
                ra = e.headers.get("Retry-After") if e.headers else None
                if e.code == 429:
                    RATE["gap"] = min(RATE["max_gap"], RATE["gap"] * 1.6)
                    base = 30 * 2 ** attempt
                else:
                    base = 5 * 2 ** attempt
                try:
                    wait = max(float(ra), base) if ra else base
                except ValueError:
                    wait = base
                wait = min(wait, 240) + random.uniform(0, 3)
                emit({"type": "wait", "seconds": round(wait), "reason": "rate_limit" if e.code == 429 else "server"})
                if e.code == 429:
                    log(f"    Roblox asked us to slow down. Pausing {wait:.0f}s, then continuing "
                        f"more slowly ({RATE['gap']:.1f}s between requests).")
                else:
                    log(f"    Roblox had a hiccup ({e.code}). Retrying in {wait:.0f}s...")
                sleep(wait)
                continue
            raise
        except (URLError, TimeoutError, ConnectionError) as e:
            last = e
            wait = min(60, 5 * 2 ** attempt)
            emit({"type": "wait", "seconds": round(wait), "reason": "network"})
            log(f"    Network hiccup ({e}); retrying in {wait}s...")
            sleep(wait)
    raise RuntimeError(f"Giving up after {tries} tries: {last}")


def fetch_list(category_id, params, pages, delay=None, on_page=None):
    """Returns a list of raw item dicts in the order Roblox ranks them.
    on_page(pages_fetched) is called after every page."""
    out = []
    cursor = None
    limit = 120
    page = 0
    while page < pages:
        check_cancel()
        q = {"Category": category_id, "Limit": limit}
        q.update(params)
        if cursor:
            q["Cursor"] = cursor
        url = API + "?" + urlencode(q)
        try:
            data = get_json(url)
        except BadRequest:
            if limit != 30:
                limit = 30          # some endpoints only accept smaller pages
                pages = pages * 4
                continue
            raise
        out.extend(data.get("data") or [])
        cursor = data.get("nextPageCursor")
        page += 1
        if on_page:
            on_page(page)
        if not cursor:
            break
    return out


THUMB_API = "https://thumbnails.roblox.com/v1/assets"


def fetch_thumbnails(ids):
    """Returns {asset_id: image_url} using Roblox's thumbnail service (one request per 100 ids)."""
    out = {}
    ids = [i for i in dict.fromkeys(ids) if i]
    for n in range(0, len(ids), 100):
        chunk = ids[n:n + 100]
        q = {"assetIds": ",".join(str(i) for i in chunk), "size": "420x420", "format": "Png",
             "isCircular": "false", "returnPolicy": "PlaceHolder"}
        try:
            data = get_json(THUMB_API + "?" + urlencode(q), tries=3)
        except ScanCancelled:
            raise
        except Exception as e:
            log(f"    Couldn't load item pictures ({e}); continuing without them.")
            continue
        for row in data.get("data") or []:
            if row.get("state") == "Completed" and row.get("imageUrl"):
                out[row.get("targetId")] = row["imageUrl"]
    return out


# ---------------------------------------------------------------- parsing
WORD_RE = re.compile(r"[a-z0-9]+")


def extract_words(name):
    s = (name or "").lower().replace("'", "").replace("’", "")
    s = s.replace("y2k", " y2k ")
    words = [ALIASES.get(w, w) for w in WORD_RE.findall(s)]
    colors = {COLORS[w] for w in words if w in COLORS}
    themes = set()
    for w in words:
        if (len(w) < 3 and w != "y2k") or w.isdigit() or w in STOP or w in GENERIC \
                or w in COLORS or w in TYPE_WORDS:
            continue
        themes.add(w)
    for a, b in zip(words, words[1:]):
        bad = lambda w: (w in STOP or w in GENERIC or w in COLORS or w.isdigit() or len(w) < 2)
        if bad(a) or bad(b) or a == b:
            continue
        if a in TYPE_WORDS and b in TYPE_WORDS:
            continue
        themes.add(a + " " + b)
    return themes, colors


def parse_time(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize(raw):
    if raw.get("itemType") != "Asset":
        return None
    at = raw.get("assetType")
    if at not in ASSET_TYPES:
        return None          # skips gear, heads, emotes, bundles, etc.
    key, label, group, _ = ASSET_TYPES[at]
    price = raw.get("price")
    if price is None:
        price = raw.get("lowestPrice")
    creator = raw.get("creatorName") or "?"
    return {
        "id": raw.get("id"),
        "name": raw.get("name") or "",
        "type": key,
        "price": price,
        "favs": raw.get("favoriteCount") or 0,
        "creator": creator,
        "by_roblox": creator.lower() == "roblox" and raw.get("creatorTargetId") in (1, None),
        "created": raw.get("itemCreatedUtc"),
        "limited": bool(raw.get("collectibleItemId")) and bool(raw.get("totalQuantity")),
    }


# ---------------------------------------------------------------- analysis
def rank_weight(rank):
    return 1.0 / (1.0 + rank / 25.0)


def quantiles(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return (vals[0], vals[0], vals[0])
    q = statistics.quantiles(vals, n=4, method="inclusive")
    return (q[0], q[1], q[2])


def nice_price(p):
    if p is None:
        return None
    p = max(5, p)
    if p < 50:
        return int(round(p / 5.0) * 5)
    if p < 200:
        return int(round(p / 10.0) * 10)
    return int(round(p / 25.0) * 25)


def analyze(records, appearances, include_roblox=False, prev_ranks=None, now=None,
            min_items=3, types_filter=None):
    now = now or datetime.now(timezone.utc)
    prev_ranks = prev_ranks or {}
    fresh_cut = now - timedelta(days=30)

    def use(rec):
        if rec is None:
            return False
        if not include_roblox and rec["by_roblox"]:
            return False
        if types_filter and TYPE_INFO[rec["type"]]["group"] not in types_filter \
                and rec["type"] not in types_filter:
            return False
        return True

    words = {}
    for iid, rec in records.items():
        words[iid] = extract_words(rec["name"])

    demand_total = 0.0
    list_totals = Counter()
    theme_d = defaultdict(float)
    theme_list = defaultdict(Counter)
    theme_items = defaultdict(set)
    theme_best = {}
    theme_type_d = defaultdict(float)
    type_d = defaultdict(float)
    color_d = defaultdict(float)
    theme_color = defaultdict(Counter)
    item_best = {}
    item_weight = defaultdict(float)

    supply_n = 0
    theme_s = Counter()
    theme_type_s = Counter()
    type_s = Counter()
    color_s = Counter()
    seen_supply = set()

    word_items = defaultdict(set)
    for ap in appearances:
        rec = records.get(ap["id"])
        if not use(rec):
            continue
        role = LISTS[ap["list"]]["role"]
        if role == "demand":
            for w in set(ALIASES.get(x, x) for x in WORD_RE.findall(rec["name"].lower().replace("'", ""))):
                word_items[w].add(ap["id"])
        themes, colors = words[ap["id"]]
        if role == "demand":
            w = LISTS[ap["list"]]["weight"] * rank_weight(ap["rank"])
            demand_total += w
            list_totals[ap["list"]] += w
            type_d[rec["type"]] += w
            item_weight[ap["id"]] += w
            item_best[ap["id"]] = min(item_best.get(ap["id"], 10 ** 9), ap["rank"])
            for c in colors:
                color_d[c] += w
            for t in themes:
                theme_d[t] += w
                theme_list[t][ap["list"]] += w
                theme_items[t].add(ap["id"])
                theme_type_d[(t, rec["type"])] += w
                for c in colors:
                    theme_color[t][c] += w
        else:
            if ap["id"] in seen_supply:
                continue
            seen_supply.add(ap["id"])
            supply_n += 1
            type_s[rec["type"]] += 1
            for c in colors:
                color_s[c] += 1
            for t in themes:
                theme_s[t] += 1
                theme_type_s[(t, rec["type"])] += 1

    if demand_total <= 0:
        raise RuntimeError("No usable bestseller data was found. Try again later or use --include-roblox.")

    has_supply = supply_n > 0
    has_day = list_totals["sales_day"] > 0 and list_totals["sales_week"] > 0
    eps_supply = 1.0 / max(supply_n, 1)

    # ---- theme stats
    stats = {}
    for t, d in theme_d.items():
        items = theme_items[t]
        if len(items) < min_items:
            continue
        if " " in t:
            # keep two-word themes only when the words really belong together
            # ("cat ears" yes, "cute emo" no)
            a, b = t.split(" ", 1)
            base = min(len(word_items[a]) or len(items), len(word_items[b]) or len(items))
            if len(items) < 0.4 * base:
                continue
        creators = Counter(records[i]["creator"] for i in items)
        if len(creators) < 2:
            continue
        dshare = d / demand_total
        sshare = theme_s[t] / supply_n if has_supply else 0.0
        ratio = dshare / (sshare + eps_supply) if has_supply else 1.0
        if has_day:
            s = 0.002
            day = theme_list[t]["sales_day"] / list_totals["sales_day"]
            wk = theme_list[t]["sales_week"] / list_totals["sales_week"]
            momentum = (day + s) / (wk + s)
        else:
            momentum = 1.0
        fresh = sum(1 for i in items if (parse_time(records[i]["created"]) or now - timedelta(days=999)) >= fresh_cut) / len(items)
        top_creator, top_n = creators.most_common(1)[0]
        dom = top_n / len(items)
        opp = (dshare ** 0.6) * (min(ratio, 6.0) ** 0.4) \
            * (0.75 + 0.25 * min(momentum, 2.0)) * (0.85 + 0.4 * fresh) \
            * (1.0 - 0.35 * max(0.0, dom - 0.5))
        stats[t] = {
            "theme": t, "demand": d, "dshare": dshare, "n_items": len(items),
            "n_creators": len(creators), "supply": theme_s[t], "sshare": sshare,
            "ratio": ratio, "momentum": momentum, "fresh": fresh, "opp_raw": opp,
            "top_creator": top_creator, "dominance": dom,
        }

    # drop single words that are mostly just part of a two-word phrase
    for t in list(stats):
        if " " in t:
            continue
        for b in stats:
            if " " in b and t in b.split() and len(theme_items[b]) >= 0.8 * len(theme_items[t]):
                stats.pop(t, None)
                break

    ranked = sorted(stats.values(), key=lambda s: -s["opp_raw"])
    top_opp = ranked[0]["opp_raw"] if ranked else 1.0
    for i, s in enumerate(ranked):
        s["opp"] = round(100 * s["opp_raw"] / top_opp)
        s["rank"] = i + 1
        pr = prev_ranks.get(s["theme"])
        s["change"] = (pr - s["rank"]) if pr else None
        s["new_entry"] = bool(prev_ranks) and pr is None
        tt = sorted(((theme_type_d[(s["theme"], k)], k) for k in TYPE_INFO if theme_type_d[(s["theme"], k)] > 0), reverse=True)
        s["types"] = [(k, v / s["demand"]) for v, k in tt]
        colors = theme_color[s["theme"]].most_common(4)
        s["colors"] = [c for c, _ in colors]
        ex = sorted(theme_items[s["theme"]], key=lambda i: -item_weight[i])
        s["examples"] = ex[:6]

    # ---- type stats
    type_rows = []
    type_prices = {}
    for k in TYPE_INFO:
        if type_d[k] <= 0 and type_s[k] <= 0:
            continue
        prices = [records[i]["price"] for i in item_weight
                  if records[i]["type"] == k and records[i]["price"] and item_best.get(i, 999) < 200]
        q = quantiles(prices)
        type_prices[k] = q
        dsh = type_d[k] / demand_total
        ssh = type_s[k] / supply_n if has_supply else 0
        type_rows.append({
            "type": k, "label": TYPE_INFO[k]["label"], "blender": TYPE_INFO[k]["blender"],
            "dshare": dsh, "sshare": ssh,
            "ratio": dsh / (ssh + eps_supply) if has_supply else 1.0,
            "price_q": q, "n_prices": len(prices),
        })
    type_rows.sort(key=lambda r: -r["dshare"])
    type_rank = {r["type"]: i + 1 for i, r in enumerate(type_rows)}
    type_share = {r["type"]: r["dshare"] for r in type_rows}

    # ---- ideas
    ideas = []
    for s in ranked[:35]:
        t = s["theme"]
        allowed = set()
        for w in t.split():
            allowed |= OBJECT_WORD_GROUP.get(w, set())
        for k, info in TYPE_INFO.items():
            if allowed and info["group"] not in allowed:
                continue
            tsh = type_share.get(k, 0)
            if tsh < 0.012:
                continue
            dt = theme_type_d[(t, k)]
            st = theme_type_s[(t, k)]
            n_tt = sum(1 for i in theme_items[t] if records[i]["type"] == k)
            fit = dt / s["demand"]
            if n_tt >= 3:
                kind = "proven"
                score = s["opp_raw"] * (0.35 + fit) * (0.6 + 3 * tsh) / (1 + 0.45 * st)
            else:
                if s["n_items"] < 4 or (not allowed and tsh < 0.03):
                    continue
                kind = "gap"
                score = s["opp_raw"] * (0.5 + 0.1 * n_tt) * (0.6 + 3 * tsh) / (1 + 0.45 * st)
            ideas.append({"theme": t, "type": k, "kind": kind, "score": score, "fit": fit, "n_tt": n_tt,
                          "supply_tt": st, "stat": s})
    ideas.sort(key=lambda x: -x["score"])
    picked, per_theme, per_type = [], Counter(), Counter()
    for idea in ideas:
        if per_theme[idea["theme"]] >= 2 or per_type[idea["type"]] >= 3:
            continue
        picked.append(idea)
        per_theme[idea["theme"]] += 1
        per_type[idea["type"]] += 1
        if len(picked) >= 12:
            break
    top_score = picked[0]["score"] if picked else 1
    global_colors = [c for c, _ in sorted(color_d.items(), key=lambda kv: -kv[1])[:6]]

    for idea in picked:
        s, k, t = idea["stat"], idea["type"], idea["theme"]
        idea["score_pct"] = round(100 * idea["score"] / top_score)
        tt_prices = [records[i]["price"] for i in theme_items[t] if records[i]["type"] == k and records[i]["price"]]
        q = type_prices.get(k)
        if len(tt_prices) >= 3:
            med = statistics.median(tt_prices)
            lo, hi = med * 0.8, med * 1.15
        elif q:
            lo, hi = q[0], q[1]
        else:
            lo = hi = None
        idea["price"] = (nice_price(lo), nice_price(hi)) if lo is not None else None
        idea["colors"] = s["colors"][:3] or global_colors[:3]
        ex_same = [i for i in s["examples"] if records[i]["type"] == k]
        ex_other = [i for i in s["examples"] if records[i]["type"] != k]
        idea["examples"] = (ex_same + ex_other)[:3]
        n = s["n_items"]
        idea["confidence"] = "High" if n >= 10 and s["n_creators"] >= 4 else ("Medium" if n >= 5 else "Low")
        label = plural(k)
        r = []
        r.append(f"“{t}” items take {n} bestseller spots, spread over {s['n_creators']} different creators.")
        if idea["kind"] == "proven":
            r.append(f"{idea['n_tt']} of those bestsellers are already {label}, so buyers want this combo.")
        else:
            few = "No" if idea["n_tt"] == 0 else f"Only {idea['n_tt']}"
            r.append(f"{few} bestselling {label} use this theme yet, while {label} are the #{type_rank.get(k, '?')} selling type. That's an open gap.")
        if has_supply:
            if idea["supply_tt"] == 0:
                r.append(f"None of the {supply_n} newest uploads are {t} {label}, so competition is low.")
            else:
                if idea["supply_tt"] == 1:
                    one = TYPE_INFO[k]["label"].lower()
                    r.append(f"Only 1 of the {supply_n} newest uploads is a {t} {one}.")
                else:
                    r.append(f"Only {idea['supply_tt']} of the {supply_n} newest uploads are {t} {label}.")
        if s["momentum"] >= 1.2:
            r.append(f"Selling {s['momentum']:.1f}× faster today than its weekly average: it's rising.")
        elif s["momentum"] <= 0.75:
            r.append("It's cooling down slightly today, so move fast or add a twist.")
        if s["fresh"] >= 0.3:
            r.append(f"{round(100 * s['fresh'])}% of its bestsellers are under 30 days old, so new items can still break through.")
        if s["dominance"] > 0.5:
            r.append(f"Note: {s['top_creator']} owns {round(100 * s['dominance'])}% of these bestsellers.")
        if s.get("change"):
            if s["change"] > 0:
                r.append(f"Up {s['change']} places since your last run.")
        idea["reasons"] = r

    fresh_hits = []
    for iid, wgt in sorted(item_weight.items(), key=lambda kv: -kv[1]):
        rec = records[iid]
        ct = parse_time(rec["created"])
        if ct and ct >= fresh_cut:
            fresh_hits.append(iid)
        if len(fresh_hits) >= 16:
            break

    colors = []
    for c, d in sorted(color_d.items(), key=lambda kv: -kv[1])[:14]:
        dsh = d / demand_total
        ssh = color_s[c] / supply_n if has_supply else 0
        colors.append({"color": c, "dshare": dsh, "sshare": ssh,
                       "ratio": dsh / (ssh + eps_supply) if has_supply else 1.0})

    top_items = [iid for iid, _ in sorted(item_weight.items(), key=lambda kv: -kv[1])[:16]]
    return {
        "themes": ranked, "types": type_rows, "ideas": picked, "fresh": fresh_hits, "top_items": top_items,
        "colors": colors, "supply_n": supply_n, "has_supply": has_supply, "has_day": has_day,
        "n_demand_items": len(item_weight), "item_best": item_best,
    }


# ---------------------------------------------------------------- report
def esc(s):
    return html.escape(str(s), quote=True)


def item_link(rec):
    return f"https://www.roblox.com/catalog/{rec['id']}"


def fmt_price(p):
    if p is None:
        return "off-sale"
    if p == 0:
        return "Free"
    return f"{p:,} R$"


def swatch(c):
    bg = COLOR_SWATCH.get(c, "#999")
    return f'<span class="chip"><i style="background:{bg}"></i>{esc(c)}</span>'


def bar(pct, cls=""):
    pct = max(2, min(100, pct))
    return f'<span class="bar {cls}"><span style="width:{pct:.0f}%"></span></span>'


def thumb_img(thumbs, iid, cls="thumb"):
    url = (thumbs or {}).get(iid)
    return f'<img class="{cls}" src="{esc(url)}" alt="" loading="lazy">' if url else ""


def build_report(result, records, meta, thumbs=None):
    R = result
    ideas_html = []
    for n, idea in enumerate(R["ideas"], 1):
        k = idea["type"]
        info = TYPE_INFO[k]
        price = idea["price"]
        if price:
            ptxt = f"{price[0]:,} R$" if price[0] == price[1] else f"{price[0]:,}–{price[1]:,} R$"
        else:
            ptxt = "not enough price data"
        exs = "".join(
            f'<li>{thumb_img(thumbs, i)}<a href="{item_link(records[i])}" target="_blank" rel="noopener">{esc(records[i]["name"])}</a>'
            f'<span class="muted"> · {esc(TYPE_INFO[records[i]["type"]]["label"])} · {fmt_price(records[i]["price"])}</span></li>'
            for i in idea["examples"])
        reasons = "".join(f"<li>{esc(r)}</li>" for r in idea["reasons"])
        kind = "Proven combo" if idea["kind"] == "proven" else "Open gap"
        badge2 = "" if info["blender"] else '<span class="tag warn">2D, not Blender</span>'
        ideas_html.append(f"""
<article class="idea">
  <div class="idea-top">
    <span class="num">{n}</span>
    <div>
      <h3>{esc(idea['theme'].title())} <span class="muted">·</span> {esc(info['label'])}</h3>
      <div class="tags"><span class="tag {'ok' if idea['kind']=='proven' else 'gap'}">{kind}</span>
      <span class="tag">Confidence: {idea['confidence']}</span>{badge2}</div>
    </div>
    <div class="score"><b>{idea['score_pct']}</b><span>score</span></div>
  </div>
  <div class="facts">
    <div><span class="k">Suggested price</span><span class="v">{ptxt}</span></div>
    <div><span class="k">Colors to try</span><span class="v">{''.join(swatch(c) for c in idea['colors']) or '—'}</span></div>
  </div>
  <h4>Why</h4><ul class="reasons">{reasons}</ul>
  <h4>Look at these for reference</h4><ul class="examples">{exs}</ul>
</article>""")

    theme_rows = []
    for s in R["themes"][:40]:
        if s["change"] is None:
            ch = '<span class="tag new">new</span>' if s["new_entry"] else '<span class="muted">—</span>'
        elif s["change"] > 0:
            ch = f'<span class="up">▲ {s["change"]}</span>'
        elif s["change"] < 0:
            ch = f'<span class="down">▼ {-s["change"]}</span>'
        else:
            ch = '<span class="muted">=</span>'
        m = s["momentum"]
        mt = f'<span class="up">↑ {m:.1f}×</span>' if m >= 1.2 else (f'<span class="down">↓ {m:.1f}×</span>' if m <= 0.8 else f'<span class="muted">{m:.1f}×</span>')
        if not R["has_day"]:
            mt = '<span class="muted">—</span>'
        comp = "Low" if s["ratio"] >= 2 else ("Medium" if s["ratio"] >= 1 else "High")
        top_types = ", ".join(TYPE_INFO[k]["label"] for k, _ in s["types"][:2])
        theme_rows.append(f"""<tr>
<td class="num-c">{s['rank']}</td>
<td><b>{esc(s['theme'])}</b><div class="muted small">{esc(top_types)}</div></td>
<td>{bar(s['opp'])}<span class="small">{s['opp']}</span></td>
<td class="num-c">{s['n_items']}</td>
<td>{mt}</td>
<td><span class="comp comp-{comp.lower()}">{comp}</span> <span class="muted small">({s['supply']} new)</span></td>
<td class="num-c">{round(100*s['fresh'])}%</td>
<td class="num-c">{ch}</td></tr>""")

    maxd = max((r["dshare"] for r in R["types"]), default=1) or 1
    type_rows = []
    for r in R["types"]:
        q = r["price_q"]
        ptxt = f"{nice_price(q[0]):,}–{nice_price(q[2]):,} R$ <span class='muted small'>(median {nice_price(q[1]):,})</span>" if q else "—"
        tag = ""
        if R["has_supply"] and r["ratio"] >= 1.5:
            tag = '<span class="tag ok">under-supplied</span>'
        elif R["has_supply"] and r["ratio"] <= 0.6:
            tag = '<span class="tag warn">crowded</span>'
        type_rows.append(f"""<tr><td><b>{esc(r['label'])}</b> {tag}</td>
<td>{bar(100*r['dshare']/maxd)}<span class="small">{100*r['dshare']:.1f}%</span></td>
<td>{bar(100*r['sshare']/maxd, 'alt')}<span class="small">{100*r['sshare']:.1f}%</span></td>
<td>{ptxt}</td></tr>""")

    fresh_html = []
    for iid in R["fresh"]:
        rec = records[iid]
        ct = parse_time(rec["created"])
        age = (meta["now_dt"] - ct).days if ct else "?"
        fresh_html.append(f"""<li>{thumb_img(thumbs, iid, "fthumb")}<a href="{item_link(rec)}" target="_blank" rel="noopener">{esc(rec['name'])}</a>
<div class="muted small">{esc(TYPE_INFO[rec['type']]['label'])} · {fmt_price(rec['price'])} · {esc(rec['creator'])} · {age} days old · best rank #{R['item_best'][iid]+1}</div></li>""")

    maxc = max((c["dshare"] for c in R["colors"]), default=1) or 1
    color_rows = "".join(
        f"""<tr><td>{swatch(c['color'])}</td><td>{bar(100*c['dshare']/maxc)}<span class="small">{100*c['dshare']:.1f}%</span></td>
<td>{bar(100*c['sshare']/maxc,'alt')}<span class="small">{100*c['sshare']:.1f}%</span></td>
<td>{'<span class="tag ok">buy more than made</span>' if R['has_supply'] and c['ratio']>=1.5 else ''}</td></tr>"""
        for c in R["colors"])

    lists_used = ", ".join(LISTS[l]["label"] for l in meta["lists"])
    notes = []
    if not R["has_supply"]:
        notes.append("The new-uploads list couldn't be loaded, so competition scores are missing this run.")
    if not R["has_day"]:
        notes.append("The daily bestseller list couldn't be loaded, so momentum is missing this run.")
    notes_html = "".join(f'<p class="note">{esc(n)}</p>' for n in notes)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UGC Trend Report</title>
<style>
:root {{
  --bg:#f6f5f2; --card:#ffffff; --ink:#1c1b19; --muted:#6c6a64; --line:#e4e1da;
  --accent:#e2462f; --accent2:#2f6fe2; --ok:#1f8a4c; --okbg:#e3f4ea; --warn:#9a6200; --warnbg:#fbefd6;
  --gap:#6a3fd1; --gapbg:#eee7fb; --barbg:#efece6;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#141412; --card:#1e1d1b; --ink:#f0eee9; --muted:#a19e96; --line:#34322e;
    --accent:#ff6a52; --accent2:#6d9bff; --ok:#5fd08e; --okbg:#1c3326; --warn:#f0b54d; --warnbg:#3a2d12;
    --gap:#b294ff; --gapbg:#2b2240; --barbg:#2b2926; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
.wrap {{ max-width:1180px; margin:0 auto; padding:28px 16px 60px; }}
header h1 {{ font-size:30px; margin:0 0 4px; letter-spacing:-.02em; }}
header p {{ margin:0; color:var(--muted); }}
.stats {{ display:flex; flex-wrap:wrap; gap:10px; margin:18px 0 6px; }}
.stat {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:10px 14px; }}
.stat b {{ display:block; font-size:22px; }}
.stat span {{ color:var(--muted); font-size:13px; }}
h2 {{ font-size:21px; margin:36px 0 4px; }}
.sub {{ color:var(--muted); margin:0 0 14px; }}
.ideas {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(340px,1fr)); gap:14px; }}
.idea {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; }}
.idea-top {{ display:flex; gap:12px; align-items:flex-start; }}
.idea-top > div:nth-child(2) {{ flex:1; min-width:0; }}
.num {{ flex:none; width:28px; height:28px; border-radius:50%; background:var(--accent); color:#fff; display:grid; place-items:center; font-weight:700; font-size:14px; }}
.idea h3 {{ margin:0 0 6px; font-size:17px; line-height:1.3; }}
.score {{ text-align:center; }}
.score b {{ display:block; font-size:22px; color:var(--accent); line-height:1; }}
.score span {{ font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }}
.tags {{ display:flex; flex-wrap:wrap; gap:6px; }}
.tag {{ font-size:12px; padding:2px 8px; border-radius:99px; background:var(--barbg); color:var(--muted); white-space:nowrap; }}
.tag.ok {{ background:var(--okbg); color:var(--ok); }}
.tag.gap {{ background:var(--gapbg); color:var(--gap); }}
.tag.warn {{ background:var(--warnbg); color:var(--warn); }}
.tag.new {{ background:var(--gapbg); color:var(--gap); }}
.facts {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; margin:14px 0 4px; padding:10px 12px; background:var(--bg); border-radius:10px; }}
.facts .k {{ display:block; font-size:12px; color:var(--muted); }}
.facts .v {{ font-weight:600; display:flex; flex-wrap:wrap; gap:4px; }}
.idea h4 {{ margin:12px 0 4px; font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }}
.idea ul {{ margin:0; padding-left:18px; }}
.idea li {{ margin:3px 0; }}
.thumb {{ width:34px; height:34px; border-radius:8px; background:var(--bg); vertical-align:middle; margin-right:8px; object-fit:contain; }}
.fthumb {{ width:100%; aspect-ratio:1; object-fit:contain; background:var(--bg); border-radius:10px; margin-bottom:8px; display:block; }}
.examples a, .fresh a {{ color:var(--accent2); text-decoration:none; }}
.examples a:hover, .fresh a:hover {{ text-decoration:underline; }}
.chip {{ display:inline-flex; align-items:center; gap:5px; font-size:13px; font-weight:500; padding:1px 8px 1px 3px; border:1px solid var(--line); border-radius:99px; background:var(--card); }}
.chip i {{ width:13px; height:13px; border-radius:50%; display:inline-block; border:1px solid rgba(0,0,0,.15); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; overflow:hidden; }}
.scroll {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th {{ text-align:left; font-size:12px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; padding:10px 12px; border-bottom:1px solid var(--line); white-space:nowrap; }}
td {{ padding:9px 12px; border-bottom:1px solid var(--line); vertical-align:middle; }}
tr:last-child td {{ border-bottom:0; }}
.num-c {{ text-align:center; }}
.bar {{ display:inline-block; width:90px; height:8px; background:var(--barbg); border-radius:99px; overflow:hidden; vertical-align:middle; margin-right:8px; }}
.bar span {{ display:block; height:100%; background:var(--accent); border-radius:99px; }}
.bar.alt span {{ background:var(--accent2); }}
.muted {{ color:var(--muted); }}
.small {{ font-size:12px; }}
.up {{ color:var(--ok); font-weight:600; white-space:nowrap; }}
.down {{ color:var(--accent); font-weight:600; white-space:nowrap; }}
.comp {{ font-weight:600; }}
.comp-low {{ color:var(--ok); }} .comp-medium {{ color:var(--warn); }} .comp-high {{ color:var(--accent); }}
.fresh {{ list-style:none; padding:0; margin:0; display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:10px; }}
.fresh li {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:10px 12px; }}
.legend {{ display:flex; gap:16px; font-size:13px; color:var(--muted); margin:0 0 10px; flex-wrap:wrap; }}
.legend i {{ display:inline-block; width:12px; height:8px; border-radius:4px; margin-right:6px; }}
.note {{ background:var(--warnbg); color:var(--warn); padding:10px 14px; border-radius:10px; }}
.how {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:6px 20px; }}
.how dt {{ font-weight:700; margin-top:12px; }}
.how dd {{ margin:2px 0 12px; color:var(--muted); }}
footer {{ margin-top:30px; color:var(--muted); font-size:13px; }}
@media (max-width:520px) {{ .ideas {{ grid-template-columns:1fr; }} .facts {{ grid-template-columns:1fr; }} header h1 {{ font-size:24px; }} }}
</style></head>
<body><div class="wrap">
<header>
  <h1>UGC Trend Report</h1>
  <p>{esc(meta['when'])} · {esc(meta['scope'])}</p>
  <div class="stats">
    <div class="stat"><b>{R['n_demand_items']}</b><span>bestselling items analyzed</span></div>
    <div class="stat"><b>{R['supply_n']}</b><span>newest uploads checked</span></div>
    <div class="stat"><b>{len(R['themes'])}</b><span>themes found</span></div>
    <div class="stat"><b>{len(R['ideas'])}</b><span>item ideas</span></div>
  </div>
  {notes_html}
</header>

<h2>What to make next</h2>
<p class="sub">Ranked ideas: themes buyers want, on item types where there isn't much competition yet. “Proven combo” means this theme already sells as this item type; “Open gap” means the theme is hot elsewhere but barely exists as this type.</p>
<section class="ideas">{''.join(ideas_html) or '<p>No ideas this run — try more pages with <code>--pages 5</code>.</p>'}</section>

<h2>Trending themes</h2>
<p class="sub">Words and phrases from item names, scored by demand vs. competition.</p>
<div class="card scroll"><table>
<thead><tr><th>#</th><th>Theme</th><th>Opportunity</th><th>Bestsellers</th><th>Momentum</th><th>Competition</th><th>New (&lt;30d)</th><th>Since last run</th></tr></thead>
<tbody>{''.join(theme_rows)}</tbody></table></div>

<h2>Item types</h2>
<p class="sub">How much of the buying goes to each type, compared with how much of the new uploads are that type.</p>
<div class="legend"><span><i style="background:var(--accent)"></i>Share of sales demand</span><span><i style="background:var(--accent2)"></i>Share of new uploads</span></div>
<div class="card scroll"><table>
<thead><tr><th>Type</th><th>Demand</th><th>New uploads</th><th>Bestseller price range</th></tr></thead>
<tbody>{''.join(type_rows)}</tbody></table></div>

<h2>New items already selling well</h2>
<p class="sub">Created in the last 30 days and already in the bestseller lists. Study what they did right.</p>
<ul class="fresh">{''.join(fresh_html) or '<li>None found this run.</li>'}</ul>

<h2>Colors</h2>
<p class="sub">Colors named in item titles, demand vs. new uploads.</p>
<div class="legend"><span><i style="background:var(--accent)"></i>Share of sales demand</span><span><i style="background:var(--accent2)"></i>Share of new uploads</span></div>
<div class="card scroll"><table>
<thead><tr><th>Color</th><th>Demand</th><th>New uploads</th><th></th></tr></thead>
<tbody>{color_rows}</tbody></table></div>

<h2>How the scores work</h2>
<dl class="how">
<dt>Demand</dt><dd>Where an item sits in the bestseller lists (past day, past week) and the most-favorited list. Higher spots count more. Roblox doesn't share exact sales numbers, so ranking position is the signal.</dd>
<dt>Competition</dt><dd>How often a theme shows up among the newest uploads. Lots of demand with few new uploads means low competition.</dd>
<dt>Momentum</dt><dd>How strongly a theme sells today compared with its weekly average. Above 1× means it's rising.</dd>
<dt>New (&lt;30d)</dt><dd>How many of the theme's bestsellers are brand new. High numbers mean newcomers can still break in.</dd>
<dt>Since last run</dt><dd>Change in theme rank compared with the previous time you ran the tool. Run it every few days to see real trends.</dd>
<dt>Keep in mind</dt><dd>Themes come from item names, so brand-new trends need a few days to show up. Always check the example items before you start modeling, and never copy someone's design or use brands and characters you don't own. That gets items taken down.</dd>
</dl>
<footer>Lists used: {esc(lists_used)}. UGC Trend Finder v{VERSION}. Made-by-Roblox items are {'included' if meta['include_roblox'] else 'excluded'}.</footer>
</div></body></html>"""


# ---------------------------------------------------------------- main
def latest_snapshot(data_dir, exclude=None):
    files = sorted(glob.glob(os.path.join(data_dir, "snapshot_*.json")))
    files = [f for f in files if os.path.abspath(f) != os.path.abspath(exclude or "")]
    return files[-1] if files else None


def summarize(result, records, meta, report_path, thumbs=None):
    """Small JSON the app uses to show ideas and history without re-scanning."""
    thumbs = thumbs or {}

    def ex(i):
        r = records[i]
        return {"id": i, "name": r["name"], "url": item_link(r), "type": TYPE_INFO[r["type"]]["label"],
                "price": fmt_price(r["price"]), "creator": r["creator"], "thumb": thumbs.get(i),
                "created": r.get("created")}
    ideas = []
    for idea in result["ideas"]:
        ideas.append({
            "theme": idea["theme"], "type": TYPE_INFO[idea["type"]]["label"],
            "blender": TYPE_INFO[idea["type"]]["blender"], "kind": idea["kind"],
            "score": idea["score_pct"], "price": idea["price"], "colors": idea["colors"],
            "confidence": idea["confidence"], "reasons": idea["reasons"],
            "examples": [ex(i) for i in idea["examples"]],
            "image": next((thumbs[i] for i in idea["examples"] if thumbs.get(i)), None),
        })
    themes = [{"theme": t["theme"], "opp": t["opp"], "n": t["n_items"], "momentum": round(t["momentum"], 2),
               "competition": "Low" if t["ratio"] >= 2 else ("Medium" if t["ratio"] >= 1 else "High"),
               "change": t["change"], "fresh": round(t["fresh"], 2)}
              for t in result["themes"][:40]]
    return {"when": meta["when"], "scope": meta["scope"], "report": os.path.basename(report_path),
            "n_items": result["n_demand_items"], "n_new": result["supply_n"],
            "ideas": ideas, "themes": themes,
            "top_items": [ex(i) for i in result.get("top_items", [])],
            "fresh_items": [ex(i) for i in result.get("fresh", [])[:12]]}


_SNAP_CACHE = {}


def _snapshot_signals(path, include_roblox=False):
    """Demand signals from one saved scan: each theme's and item's share of all
    bestseller activity (in %), and how its past-day sales compare with its past-week sales."""
    key = (path, os.path.getmtime(path), include_roblox)
    if key in _SNAP_CACHE:
        return _SNAP_CACHE[key]
    with open(path, encoding="utf-8") as f:
        snap = json.load(f)
    records = snap.get("records") or {}
    qualified = set((snap.get("theme_ranks") or {}).keys())
    total, day_total, week_total = 0.0, 0.0, 0.0
    t_w, t_day, t_week, t_items, t_creators = (defaultdict(float), defaultdict(float), defaultdict(float),
                                              defaultdict(set), defaultdict(set))
    i_w, i_day, i_week = defaultdict(float), defaultdict(float), defaultdict(float)
    words = {}
    for ap in snap.get("appearances") or []:
        spec = LISTS.get(ap.get("list"))
        if not spec or spec["role"] != "demand":
            continue
        rec = records.get(str(ap["id"]))
        if not rec or (rec.get("by_roblox") and not include_roblox):
            continue
        w = spec["weight"] * rank_weight(ap["rank"])
        total += w
        iid = str(ap["id"])
        i_w[iid] += w
        if ap["list"] == "sales_day":
            day_total += w
            i_day[iid] += w
        elif ap["list"] == "sales_week":
            week_total += w
            i_week[iid] += w
        if iid not in words:
            words[iid] = extract_words(rec.get("name", ""))[0]
        for t in words[iid]:
            t_w[t] += w
            t_items[t].add(iid)
            t_creators[t].add(rec.get("creator"))
            if ap["list"] == "sales_day":
                t_day[t] += w
            elif ap["list"] == "sales_week":
                t_week[t] += w

    def mom(day, week):
        if not day_total or not week_total:
            return None
        s = 0.002
        return round((day / day_total + s) / (week / week_total + s), 2)

    themes = {}
    if total:
        for t, w in t_w.items():
            ok = (t in qualified) if qualified else (len(t_items[t]) >= 3 and len(t_creators[t]) >= 2)
            if ok:
                themes[t] = {"v": round(100 * w / total, 3), "m": mom(t_day[t], t_week[t]), "n": len(t_items[t])}
    items = {iid: {"v": round(100 * w / total, 3), "m": mom(i_day[iid], i_week[iid])}
             for iid, w in i_w.items()} if total else {}
    info = {}
    for iid in items:
        r = records[iid]
        info[iid] = {"name": r.get("name", ""), "type": TYPE_INFO.get(r.get("type"), {}).get("label", ""),
                     "price": fmt_price(r.get("price")), "creator": r.get("creator"), "favs": r.get("favs") or 0,
                     "url": item_link(r)}
    out = {"t": snap.get("created"), "cats": sorted(snap.get("categories") or []),
           "themes": themes, "items": items, "info": info}
    _SNAP_CACHE.clear() if len(_SNAP_CACHE) > 400 else None
    _SNAP_CACHE[key] = out
    return out


def momentum_history(data_dir, include_roblox=False, max_points=90, top=40):
    """Builds the momentum charts from every saved scan (newest scope only, so numbers compare)."""
    files = sorted(glob.glob(os.path.join(data_dir, "snapshot_*.json")))[-max_points * 2:]
    snaps = []
    for p in files:
        try:
            snaps.append(_snapshot_signals(p, include_roblox))
        except Exception:
            continue
    snaps = [s for s in snaps if s["t"]]
    if not snaps:
        return {"points": [], "themes": [], "items": []}
    scope = snaps[-1]["cats"]
    snaps = [s for s in snaps if s["cats"] == scope][-max_points:]
    snaps.sort(key=lambda s: s["t"])

    def series(kind):
        best = defaultdict(float)
        for i, s in enumerate(snaps):
            recent = 1.0 + 0.5 * (i == len(snaps) - 1)      # favour what matters now
            for k, d in s[kind].items():
                best[k] = max(best[k], d["v"] * recent)
        keys = [k for k, _ in sorted(best.items(), key=lambda kv: -kv[1])[:top]]
        out = []
        for k in keys:
            row = {"key": k, "v": [], "m": []}
            for s in snaps:
                d = s[kind].get(k)
                row["v"].append(d["v"] if d else 0.0)
                row["m"].append(d["m"] if d else None)
            if kind == "items":
                last = next(s["info"][k] for s in reversed(snaps) if k in s["info"])
                row.update(last)
                row["id"] = k
                row["favs_hist"] = [s["info"][k]["favs"] if k in s["info"] else None for s in snaps]
            else:
                row["name"] = k
                row["n"] = next((s["themes"][k]["n"] for s in reversed(snaps) if k in s["themes"]), 0)
            out.append(row)
        return out

    return {"points": [s["t"] for s in snaps], "scope": " + ".join(c.title() for c in scope),
            "themes": series("themes"), "items": series("items")}


def default_out_dir():
    """Where the app keeps its reports: Documents/UGC Trend Finder."""
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    base = docs if os.path.isdir(docs) else os.path.expanduser("~")
    return os.path.join(base, "UGC Trend Finder")


def estimate_seconds(pages, n_categories, gap):
    requests = pages * n_categories * len(LISTS)
    return requests * (gap * 1.18 + 0.7)


def run_scan(pages=3, only=None, include_roblox=False, blender_only=False, delay=3.0,
             out=None, from_snapshot=None, progress=None):
    """Runs a full scan and writes the report. Returns (report_path, summary).
    progress(done, total) is called after every page; richer events go to HOOKS["event"]."""
    out = out or HERE
    data_dir = os.path.join(out, "data")
    rep_dir = os.path.join(out, "reports")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(rep_dir, exist_ok=True)
    now = datetime.now(timezone.utc)
    progress = progress or (lambda d, t: None)
    RATE["gap"] = max(1.5, float(delay))
    RATE["last"] = 0.0

    if from_snapshot:
        with open(from_snapshot, encoding="utf-8") as f:
            snap = json.load(f)
        records = {int(k): v for k, v in snap["records"].items()}
        appearances = snap["appearances"]
        now = parse_time(snap["created"]) or now
        snap_path = from_snapshot
        cats = snap.get("categories", list(CATEGORIES))
    else:
        cats = [only] if only else list(CATEGORIES)
        log(f"UGC Trend Finder v{VERSION}: reading the Roblox marketplace...")
        records, appearances = {}, []
        # one step per page of every list, plus one for item pictures
        total = len(cats) * len(LISTS) * pages + 1
        state = {"done": 0}

        def advance(n, label, page=None):
            state["done"] = min(total - 1, state["done"] + n)
            progress(state["done"], total)
            emit({"type": "progress", "done": state["done"], "total": total, "label": label,
                  "page": page, "pages": pages})

        emit({"type": "start", "total": total, "gap": RATE["gap"],
              "estimate": estimate_seconds(pages, len(cats), RATE["gap"])})
        progress(0, total)
        for cat in cats:
            for lname, spec in LISTS.items():
                check_cancel()
                params = dict(spec["params"])
                label = f"{cat.title()} · {spec['label']}"
                log(f"  {cat}: {spec['label']}")
                emit({"type": "step", "label": label, "done": state["done"], "total": total})
                fetched = {"n": 0}

                def on_page(n, label=label):
                    if n <= pages:
                        fetched["n"] = n
                        advance(1, label, n)
                try:
                    raw = fetch_list(CATEGORIES[cat], params, pages, on_page=on_page)
                except ScanCancelled:
                    raise
                except Exception as e:
                    log(f"    Skipped ({e})")
                    raw = []
                if fetched["n"] < pages:          # list ended early or was skipped
                    advance(pages - fetched["n"], label)
                kept = 0
                for rank, r in enumerate(raw):
                    rec = normalize(r)
                    if not rec or rec["id"] is None:
                        continue
                    records[rec["id"]] = rec
                    appearances.append({"list": lname, "cat": cat, "rank": rank, "id": rec["id"]})
                    kept += 1
                if raw:
                    log(f"    {len(raw)} items ({kept} usable)")
        if not appearances:
            raise RuntimeError("Couldn't get any data from Roblox. Check your internet connection "
                               "and try again in a few minutes.")
        stamp = now.astimezone().strftime("%Y-%m-%d_%H%M%S")
        snap_path = os.path.join(data_dir, f"snapshot_{stamp}.json")
        snap = {"created": now.isoformat(), "categories": cats,
                "records": {str(k): v for k, v in records.items()}, "appearances": appearances}

    log("Analyzing themes, prices and competition...")
    emit({"type": "step", "label": "Analyzing themes, prices and competition"})
    prev_path = latest_snapshot(data_dir, exclude=snap_path)
    prev_ranks = {}
    if prev_path and not from_snapshot:
        try:
            with open(prev_path, encoding="utf-8") as f:
                prev_ranks = json.load(f).get("theme_ranks", {})
        except Exception:
            prev_ranks = {}

    types_filter = None
    if blender_only:
        types_filter = {k for k, v in TYPE_INFO.items() if v["blender"]}
    result = analyze(records, appearances, include_roblox=include_roblox,
                     prev_ranks=prev_ranks, now=now, types_filter=types_filter)

    if not from_snapshot:
        snap["theme_ranks"] = {s["theme"]: s["rank"] for s in result["themes"]}
        with open(snap_path, "w", encoding="utf-8") as f:
            json.dump(snap, f)

    local = now.astimezone()
    meta = {
        "when": local.strftime("%A %d %B %Y, %H:%M"),
        "now_dt": now,
        "scope": " + ".join(c.title() for c in cats) + (" (Blender items only)" if blender_only else ""),
        "lists": list(LISTS),
        "include_roblox": include_roblox,
    }
    thumbs = {}
    if not from_snapshot:
        emit({"type": "step", "label": "Loading item pictures"})
        log("Loading item pictures...")
        want = []
        for idea in result["ideas"]:
            want += idea["examples"][:3]
        want += result["top_items"] + result["fresh"][:12]
        thumbs = fetch_thumbnails(want)
        emit({"type": "progress", "done": total, "total": total, "label": "Finishing up"})
        progress(total, total)
    page = build_report(result, records, meta, thumbs)
    stamp = local.strftime("%Y-%m-%d_%H%M%S")
    out_file = os.path.join(rep_dir, f"ugc_trends_{stamp}.html")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(page)
    summary = summarize(result, records, meta, out_file, thumbs)
    with open(os.path.join(rep_dir, f"ugc_trends_{stamp}.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)

    log("")
    log("Top ideas:")
    for i, idea in enumerate(summary["ideas"][:5], 1):
        log(f"  {i}. {idea['theme'].title()} — {idea['type']}")
    log(f"Report saved: {out_file}")
    return out_file, summary


def main():
    ap = argparse.ArgumentParser(description="Find trending Roblox UGC themes and item ideas.")
    ap.add_argument("--pages", type=int, default=3, help="pages of 120 items per list (default 3)")
    ap.add_argument("--only", choices=["accessories", "clothing"], help="only look at one category")
    ap.add_argument("--include-roblox", action="store_true", help="count items made by Roblox itself")
    ap.add_argument("--blender-only", action="store_true", help="skip classic 2D clothing")
    ap.add_argument("--delay", type=float, default=3.0, help="seconds between requests (default 3)")
    ap.add_argument("--from-snapshot", help="rebuild a report from a saved snapshot, no internet needed")
    ap.add_argument("--no-open", action="store_true", help="don't open the report in the browser")
    ap.add_argument("--out", default=HERE, help="folder for reports and data (default: next to this script)")
    args = ap.parse_args()
    try:
        out_file, _ = run_scan(pages=args.pages, only=args.only, include_roblox=args.include_roblox,
                               blender_only=args.blender_only, delay=args.delay, out=args.out,
                               from_snapshot=args.from_snapshot)
    except RuntimeError as e:
        log(f"\n{e}")
        sys.exit(1)
    if not args.no_open:
        webbrowser.open("file://" + os.path.abspath(out_file))


if __name__ == "__main__":
    main()
