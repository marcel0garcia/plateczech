# Florida Plateczech

A terminal-based tool for checking the availability of Florida vanity license plates against the Florida DMV.

<img width="859" height="312" alt="image" src="https://github.com/user-attachments/assets/89212d60-a915-4e94-89ff-a6f7c4fbccbb" />

## Features

- **Numeric scan** — zero-padded number plates (07, 007, 2024)
- **Alpha scan** — pure letter plates (OO, ZZZ, XAX, TOO, MIAMI)
- **Word scan** — dictionary words from a built-in wordlist (ACE, WOLF, BLAZE)
- **Pattern scan** — custom wildcards (`OO?`, `FL###`, `X?X`, `@@@@`)
- **Full sweep** — numeric + words in one pass
- **Single plate check** — live DMV lookup for any specific plate
- **Reverify** — re-check all AVAILABLE plates to confirm they're still open
- **Results browser** — filter by type, length, or text
- Persistent SQLite database — results survive between sessions
- Configurable scan speed (Fast / Standard / Careful)
- Live progress display with real-time found-plate feed

## Requirements

- Python 3.10+
- Florida plates only (checks the FL DMV at `services.flhsmv.gov`)

## Setup

```bash
git clone https://github.com/yourusername/plateczech.git
cd plateczech
pip install -r requirements.txt
python3 plateczech.py
```

## Usage

```
  1  Start a scan
  2  Check a single plate    (live DMV lookup)
  3  View available plates
  4  Reverify available       (confirm plates are still open)
  5  Stats
  q  Quit
```

### Scan types

| Type | Description | Example |
|---|---|---|
| Numeric | Zero-padded numbers | `07`, `007`, `2024` |
| Alpha | Pure letters | `OO`, `ZZZ`, `XAX`, `TOO` |
| Words | Dictionary wordlist | `ACE`, `WOLF`, `BLAZE` |
| Pattern | Custom wildcards | `OO?`, `FL###`, `X?X` |
| Full Sweep | Numeric 2–3 + Words 3–5 | broad first pass |

### Pattern wildcards

| Symbol | Matches |
|---|---|
| `?` | Any letter or digit |
| `#` | Digit only (0–9) |
| `@` | Letter only (A–Z) |
| literal | Exact character |

### Notes

- Florida vanity plates are 2–7 characters
- Plates checked in the last 24 hours are automatically skipped on re-scans
- **VPN recommended** — repeated requests from the same IP may trigger rate-limiting from the Florida DMV
- Longer plate lengths multiply combinations exponentially (3 letters = 17k, 4 = 457k)
- Results are saved to `plates.db` in your working directory

## Project structure

```
plateczech.py       # CLI entry point
scanner.py          # Background scan engine (SearchTask)
config.py           # DMV URL, request headers, delays, paths
scraper/
  session.py        # ASP.NET session + ViewState token management
  checker.py        # Batch plate checker (5 plates per POST)
  rate_limiter.py   # Jitter-based rate limiting + backoff
generator/
  combinations.py   # Plate generators: numeric, alpha, words
  patterns.py       # Pattern DSL (?, #, @)
  wordlist.py       # Wordlist loader
storage/
  database.py       # SQLite init + connection
  queries.py        # All DB queries
data/
  wordlist.txt      # Dictionary wordlist
```

## Disclaimer

This tool queries the public Florida DMV vanity plate availability checker at a rate-limited pace. Use responsibly. The authors are not affiliated with the Florida DMV.
