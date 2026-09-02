# Laptopjacht

Finds well-priced laptops on [Marktplaats](https://www.marktplaats.nl) under €600, scores
them by value, and serves them to a small Android app.

Built for one specific question: *which second-hand laptop gives the most gaming +
development machine per euro right now?*

---

## How it works

```
GitHub Actions (every 6h)          data branch              Android app
┌──────────────────────┐          ┌──────────────┐         ┌──────────────────┐
│ scraper/run.py       │  push -f │ listings.json│  HTTPS  │ native fetch     │
│  harvest → parse →   │─────────▶│  (~300 KB    │────────▶│  → disk cache    │
│  score               │          │   gzipped)   │         │  → WebView UI    │
└──────────────────────┘          └──────────────┘         └──────────────────┘
```

The phone never scrapes Marktplaats itself. Actions does that on a schedule and publishes a
single JSON snapshot; the app just downloads it. That means Marktplaats changing its markup
breaks *one Python file*, not the installed app.

### Why value is measured the way it is

A listing's `deal` score is its **GPU class median ÷ its asking price**, where the median is
computed across every other listing in the same snapshot with the same GPU. `1.60×` means
other RTX 3050 machines are asking 1.6× as much.

Because the snapshot only contains listings ≤ €600, this measures *cheapness within budget* —
not a discount against the whole market. Listings whose GPU class has fewer than 8 comparable
listings fall back to a spec-based estimate instead, and are labelled `spec` rather than `class`.

### What gets filtered out

| Removed | Why |
|---|---|
| Everything outside category 339 | Graphics cards, desktops, monitors, chargers and bags all match "laptop" searches |
| `condition: Niet werkend` / `Defect` | Seller has declared it broken — this is a *field*, not just text |
| "vanaf €…" dealer ads | Bulk listings whose shown price isn't the price of any actual machine |
| Price ≤ €40 or > €600 | Accessories below, out of budget above |

Auction-style and damage-flagged listings are **kept but labelled**, so you can decide.

### Known limits

- **Specs are parsed from seller free text.** Marktplaats' own `memoryRAM` field is ignored:
  1,403 of 1,516 sellers left it on the "8 GB" default. `RAM ?` means the seller never said.
- **Listings go stale fast.** The app's freshness filter defaults to the last week.
- **Actions runners may get rate-limited.** `run.py` exits non-zero rather than publish a
  near-empty snapshot, so the app keeps serving the last good data.
- Nothing here verifies a seller's honesty or a battery's health. It is a shortlist to go
  check, not a guarantee.

---

## The app

Plain `WebView` + one Java file, no dependencies. Listing data is fetched **natively**
(`HttpURLConnection`) rather than from JavaScript, so no CORS policy applies, and cached to
disk so the app opens instantly with no signal.

- **Refresh** — the ↻ button, any time
- **On open** — auto-refreshes when the cache is older than 30 minutes
- **Offline** — shows the last downloaded snapshot with an "updated N h ago" stamp

### Install

Download the latest APK:

**https://github.com/Deunnis/marktplaats-laptopjacht/releases/latest/download/laptopjacht.apk**

It's debug-signed for sideloading — Android will ask you to allow "install unknown apps" for
your browser the first time. Every push to `android/` rebuilds and republishes it.

---

## Repo layout

| Path | What |
|---|---|
| `scraper/run.py` | Harvest → parse → score. Pure stdlib, no dependencies. |
| `.github/workflows/scrape.yml` | Every 6h + manual. Publishes the `data` branch. |
| `.github/workflows/android.yml` | Builds the APK, republishes the `latest` release. |
| `android/` | The app. `assets/index.html` is the whole UI. |
| `docs/index.html` | Same UI for the browser, if you enable GitHub Pages. |
| `data` branch | Single force-pushed commit, so 4 snapshots a day never grow the repo. |

## Running it yourself

```bash
python3 scraper/run.py          # writes data/listings.json
cd android && ./gradlew assembleRelease
```

Needs Python 3.9+ and the Android SDK (compileSdk 34). No other dependencies.
