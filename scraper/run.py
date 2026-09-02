#!/usr/bin/env python3
"""Harvest Marktplaats laptop listings, parse specs, score value, emit data/listings.json.

Runs on GitHub Actions every 6h. Pure stdlib - no dependencies to break.
"""
import json, re, time, os, sys, collections, statistics, datetime
import urllib.parse, urllib.request, urllib.error

BASE = "https://www.marktplaats.nl/lrp/api/search"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "listings.json")

LAPTOP_CAT = 339            # computers-en-software / windows-laptops
PRICE_RANGE = ["PriceCents:0:60000"]

GAMING_Q = ["gaming laptop", "rtx laptop", "gtx laptop", "asus rog", "lenovo legion",
            "acer nitro", "acer predator", "hp omen", "hp victus", "asus tuf",
            "msi gaming laptop", "gtx 1650", "gtx 1060", "rtx 3050", "rtx 2060",
            "gaming laptop nvidia", "laptop videokaart"]
DEV_Q = ["thinkpad", "dell latitude", "hp elitebook", "hp zbook", "dell precision",
         "laptop 16gb ram", "laptop i7", "laptop ryzen 7", "zakelijke laptop",
         "refurbished laptop"]


def fetch(params, tries=3):
    q = urllib.parse.urlencode(params, doseq=True)
    for a in range(tries):
        try:
            req = urllib.request.Request(BASE + "?" + q,
                                         headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=45) as f:
                return json.load(f)
        except Exception as e:
            if a == tries - 1:
                print(f"    fetch failed: {e}", file=sys.stderr)
                return None
            time.sleep(2 * (a + 1))
    return None


def harvest():
    seen = {}

    def run(tag, params, maxpages):
        got = 0
        for p in range(maxpages):
            pr = dict(params); pr["offset"] = p * 100; pr["limit"] = 100
            d = fetch(pr)
            if not d:
                break
            ls = d.get("listings", [])
            if not ls:
                break
            for l in ls:
                seen[l["itemId"]] = l
            got += len(ls)
            if (p + 1) * 100 >= min(d.get("totalResultCount", 0), maxpages * 100):
                break
            time.sleep(0.25)
        print(f"  {tag}: +{got} (unique {len(seen)})", flush=True)

    for q in GAMING_Q + DEV_Q:
        run(q, {"query": q, "attributeRanges[]": PRICE_RANGE,
                "searchInTitleAndDescription": "true"}, 4)
    run("category-newest", {"l1CategoryId": 322, "l2CategoryId": LAPTOP_CAT,
        "attributeRanges[]": PRICE_RANGE, "sortBy": "SORT_INDEX",
        "sortOrder": "DECREASING"}, 20)
    run("category-price-desc", {"l1CategoryId": 322, "l2CategoryId": LAPTOP_CAT,
        "attributeRanges[]": ["PriceCents:30000:60000"], "sortBy": "PRICE",
        "sortOrder": "DECREASING"}, 15)
    run("category-price-asc", {"l1CategoryId": 322, "l2CategoryId": LAPTOP_CAT,
        "attributeRanges[]": ["PriceCents:15000:60000"], "sortBy": "PRICE",
        "sortOrder": "INCREASING"}, 15)
    return list(seen.values())


# ---------------------------------------------------------------- parsing
GPU_TIERS = [
    (r'\brtx\s*-?\s*40(80|90)\b', 'RTX 4080/4090', 100, 700),
    (r'\brtx\s*-?\s*4070\b', 'RTX 4070', 92, 560),
    (r'\brtx\s*-?\s*4060\b', 'RTX 4060', 85, 480),
    (r'\brtx\s*-?\s*4050\b', 'RTX 4050', 78, 400),
    (r'\brtx\s*-?\s*3080\b', 'RTX 3080', 88, 520),
    (r'\brtx\s*-?\s*3070\b', 'RTX 3070', 82, 430),
    (r'\brtx\s*-?\s*3060\b', 'RTX 3060', 75, 360),
    (r'\brtx\s*-?\s*3050\s*ti\b', 'RTX 3050 Ti', 66, 290),
    (r'\brtx\s*-?\s*3050\b', 'RTX 3050', 62, 265),
    (r'\brtx\s*-?\s*2080\b', 'RTX 2080', 78, 380),
    (r'\brtx\s*-?\s*2070\b', 'RTX 2070', 72, 330),
    (r'\brtx\s*-?\s*2060\b', 'RTX 2060', 64, 285),
    (r'\bgtx\s*-?\s*1660\s*ti\b', 'GTX 1660 Ti', 60, 255),
    (r'\bgtx\s*-?\s*1650\s*ti\b', 'GTX 1650 Ti', 52, 215),
    (r'\bgtx\s*-?\s*1650\b', 'GTX 1650', 48, 190),
    (r'\bgtx\s*-?\s*1070\b', 'GTX 1070', 58, 240),
    (r'\bgtx\s*-?\s*1060\b', 'GTX 1060', 50, 195),
    (r'\bgtx\s*-?\s*1050\s*ti\b', 'GTX 1050 Ti', 36, 135),
    (r'\bgtx\s*-?\s*1050\b', 'GTX 1050', 30, 105),
    (r'\bgtx\s*-?\s*9[678]0m?\b', 'GTX 900M', 22, 70),
    (r'\bmx\s*-?\s*(450|350|330|250|150|130|110)\b', 'MX (entry)', 14, 40),
    (r'\b(quadro|rtx\s*a\d{3,4})\b', 'Quadro/RTX A', 30, 95),
    (r'\bradeon\s*rx\s*6\d{3}m?\b', 'Radeon RX 6000', 60, 250),
    (r'\b(780m|680m|660m)\b', 'Radeon 700M iGPU', 30, 80),
    (r'\b(iris\s*xe|uhd\s*graphics|hd\s*graphics|vega\s*\d|radeon\s*graphics)\b',
     'integrated', 5, 0),
]
GPU_EUR = {n: e for _, n, _, e in GPU_TIERS}

DEFECT = (r'(defect|kapot|niet werkend|werkt niet|voor onderdelen|start niet|boot niet|'
          r'barst|gebarsten|scherm stuk|beschadigd|bios ?(wachtwoord|password|locked)|'
          r'geen beeld|waterschade)')
BULK = (r'(vanaf\s*€|vanaf\s*\d|meerdere (beschikbaar|stuks)|op voorraad|partij|'
        r'diverse laptops|verschillende laptops|groothandel|per stuk)')
RISK = (r'(geen (lader|oplader|acculader)|accu (slecht|kapot|leeg)|batterij (slecht|kapot)|'
        r'scheur|deuk|krassen|barst|vlek|dode pixel|geen garantie|zonder lader|'
        r'niet getest|ongetest)')
AUCTION = r'\b(veiling|opbod)\b'

NL_M = {'jan': 1, 'feb': 2, 'mrt': 3, 'apr': 4, 'mei': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'okt': 10, 'nov': 11, 'dec': 12}


def age_days(s, today):
    s = (s or "").strip().lower()
    if 'vandaag' in s: return 0
    if 'gisteren' in s: return 1
    if 'eergisteren' in s: return 2
    m = re.match(r'(\d{1,2})\s+([a-z]{3})\.?\s*(\d{2})?', s)
    if m and NL_M.get(m.group(2)):
        y = 2000 + int(m.group(3)) if m.group(3) else today.year
        try:
            return (today - datetime.date(y, NL_M[m.group(2)], int(m.group(1)))).days
        except ValueError:
            return None
    return None


def gpu_of(t):
    for rx, name, tier, eur in GPU_TIERS:
        if re.search(rx, t):
            return name, tier
    return "", 0


def cpu_of(t):
    m = re.search(r'\bryzen\s*([3579])\s*(\d{4})\s*([hxsu]{0,2})', t)
    if m:
        fam, num, sfx = int(m.group(1)), m.group(2), m.group(3)
        gen = int(num[0]); hi = 'h' in sfx or 'x' in sfx
        base = {3: 70, 5: 110, 7: 160, 9: 210}[fam]
        base += {4: 0, 5: 25, 6: 45, 7: 70, 8: 95}.get(gen, 0) + (30 if hi else 0)
        return f"Ryzen {fam} {num}{sfx.upper()}", base
    m = re.search(r'\bi([3579])[\s-]*(\d{4,5})\s*([a-z]{0,2})', t)
    if m:
        fam, num, sfx = int(m.group(1)), m.group(2), m.group(3)
        g = int(num[:2]) if len(num) == 5 else int(num[0])
        if len(num) == 4 and g <= 1: g = 10
        base = {3: 45, 5: 85, 7: 130, 9: 180}[fam]
        base += max(0, (g - 6)) * 22 + (35 if sfx.startswith('h') else 0)
        return f"i{fam}-{num}{sfx.upper()}", base
    if re.search(r'\b(celeron|pentium|atom)\b', t):
        return "Celeron/Pentium", 0
    m = re.search(r'\b(i[3579])\b', t)
    if m:
        return m.group(1).upper() + " (gen?)", 50
    return "", 0


def ram_of(t, ea):
    if re.search(r'\d\s*/\s*\d{1,2}\s*/\s*\d{1,2}\s*gb', t) or re.search(r'\b8\s*/\s*16\b', t):
        return 0
    strong, weak = [], []
    for m in re.finditer(r'(\d{1,3})\s*gb\b', t):
        v = int(m.group(1))
        if v not in (4, 6, 8, 12, 16, 20, 24, 32, 48, 64):
            continue
        pre = t[max(0, m.start() - 30):m.start()]; post = t[m.end():m.end() + 22]
        if re.search(r'(ssd|hdd|nvme|opslag|schijf|m\.2|emmc|harde)', pre[-18:] + post):
            continue
        if re.search(r'(ram|geheugen|ddr\d?|werkgeheugen|memory)', pre[-18:] + post):
            strong.append(v)
        elif v in (8, 12, 16, 24, 32):
            weak.append(v)
    if strong: return max(strong)
    if weak: return max(weak)
    m = re.match(r'(\d{1,3})\s*GB', ea.get("memoryRAM", "") or "")
    return int(m.group(1)) if m else 0


def stor_of(t):
    gb, kind = 0, ""
    for m in re.finditer(r'(\d{1,4})\s*(gb|tb)\b', t):
        v = int(m.group(1)); u = m.group(2)
        win = t[max(0, m.start() - 22):m.end() + 22]
        if not re.search(r'(ssd|nvme|m\.2|hdd|opslag|schijf|harde|emmc)', win):
            continue
        vv = v * 1024 if u == 'tb' else v
        if vv > 4096: continue
        if vv > gb:
            gb = vv
            kind = "SSD" if re.search(r'(ssd|nvme|m\.2)', win) else "HDD"
    return gb, kind


def analyse(raw):
    today = datetime.datetime.utcnow().date()
    items = []
    for l in raw:
        if l.get("categoryId") != LAPTOP_CAT:
            continue
        pi = l.get("priceInfo") or {}
        price = (pi.get("priceCents") or 0) / 100
        if price <= 40 or price > 600:
            continue
        attrs = {a.get('key'): a.get('value') for a in (l.get('attributes') or [])}
        ea = {a.get('key'): a.get('value') for a in (l.get('extendedAttributes') or [])}
        cond = attrs.get("condition") or ea.get("condition") or ""
        if re.search(r'(niet werkend|defect)', cond.lower()):
            continue
        t = (l.get("title", "") + " " + l.get("description", "")).lower()
        if re.search(DEFECT, t) or re.search(BULK, t):
            continue
        loc = l.get("location") or {}
        g, gt = gpu_of(t); c, ce = cpu_of(t)
        ram = ram_of(t, ea); ssd, sk = stor_of(t)
        items.append(dict(
            t=l.get("title", "")[:120], p=round(price), pt=pi.get("priceType", ""),
            u="https://www.marktplaats.nl" + l.get("vipUrl", ""),
            city=loc.get("cityName") or "", ctry=loc.get("countryName") or "",
            abroad=bool(loc.get("abroad")), dt=l.get("date") or "",
            age=age_days(l.get("date") or "", today),
            cond=cond, dlv=(attrs.get("delivery") or ea.get("delivery") or "")
                         .replace("Ophalen of Verzenden", "Ophalen/Verzenden"),
            g=g, gt=gt, c=c, ce=ce, ram=ram, ssd=ssd, sk=sk,
            scr=ea.get("screenSize", ""),
            auc=bool(re.search(AUCTION, t)), risk=bool(re.search(RISK, t)),
        ))

    byc = collections.defaultdict(list)
    for o in items:
        if o["g"] and o["g"] != "integrated":
            byc[o["g"]].append(o["p"])
    med = {k: statistics.median(v) for k, v in byc.items() if len(v) >= 8}

    for o in items:
        v = 55 + GPU_EUR.get(o["g"], 0) + o["ce"]
        v += {0: 0, 4: 8, 6: 15, 8: 32, 12: 55, 16: 78, 20: 95,
              24: 110, 32: 145, 48: 180, 64: 220}.get(o["ram"], 0)
        v += 80 if o["ssd"] >= 1024 else 48 if o["ssd"] >= 512 else 26 if o["ssd"] >= 256 else 8 if o["ssd"] else 0
        cl = o["cond"].lower()
        if "nieuw" in cl and "zo goed" not in cl: v *= 1.12
        elif "zo goed als nieuw" in cl: v *= 1.05
        v *= 0.88
        o["cm"] = med.get(o["g"])
        o["deal"] = round(o["cm"] / o["p"], 2) if o["cm"] else round(v / o["p"], 2)
        o["cap"] = round(o["gt"] * 1.6 + o["ce"] * 0.35 + o["ram"] * 2.2 +
                         (12 if o["ssd"] >= 512 else 6 if o["ssd"] >= 256 else 0))
        o["tgtf"] = o["deal"] >= 2.4

    meta = dict(
        built=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        n=len(items), medians={k: int(v) for k, v in med.items()},
        nfixed=sum(1 for o in items if o["pt"] == "FIXED"),
        nbid=sum(1 for o in items if o["pt"] == "MIN_BID"))
    return dict(meta=meta, items=items)


if __name__ == "__main__":
    print("harvesting marktplaats...", flush=True)
    raw = harvest()
    if len(raw) < 200:
        print(f"ERROR: only {len(raw)} listings fetched - refusing to overwrite good data "
              "(Marktplaats may be blocking this runner)", file=sys.stderr)
        sys.exit(1)
    out = analyse(raw)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=True, separators=(",", ":"))
    m = out["meta"]
    print(f"wrote {OUT}: {m['n']} laptops ({m['nfixed']} fixed / {m['nbid']} bid), "
          f"{os.path.getsize(OUT)//1024} KB")
