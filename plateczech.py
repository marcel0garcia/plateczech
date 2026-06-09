#!/usr/bin/env python3
"""FLORIDA PLATECZECH — Florida Vanity Plate Availability Scanner"""

import math
import os
import time

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.prompt import Prompt, Confirm
from rich.align import Align
from rich.rule import Rule
from rich import box

from storage.database import init_db
from scanner import SearchTask
from storage import queries
from generator.patterns import estimate_pattern_count
from scraper.session import PlateSession
from scraper.checker import check_batch
from scraper.rate_limiter import RateLimiter
from config import WORDLIST_PATH, BATCH_SIZE

console = Console()

# (label, display, min_delay, max_delay)
SPEEDS = [
    ("Fast",     "1.0–2.0s  ~200 plates/min", 1.0, 2.0),
    ("Standard", "1.5–3.0s  ~130 plates/min", 1.5, 3.0),
    ("Careful",  "3.0–6.0s  ~65  plates/min", 3.0, 6.0),
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _banner():
    console.clear()
    console.print()
    t = Text()
    t.append("  F L O R I D A  ", style="bold white")
    t.append("P L A T E C Z E C H  ", style="bold yellow")
    console.print(Align.center(Panel(t, border_style="blue", padding=(0, 6))))
    console.print(Align.center(Text("Florida Vanity Plate Availability Scanner", style="dim cyan")))
    console.print()


def _ask_int(prompt: str, default: int, lo: int, hi: int) -> int:
    while True:
        raw = Prompt.ask(prompt, default=str(default)).strip()
        if raw.isdigit() and lo <= int(raw) <= hi:
            return int(raw)
        console.print(f"  [red]Enter a number from {lo} to {hi}.[/red]")


def _count_words(min_len: int, max_len: int) -> int:
    n = 0
    try:
        with open(WORDLIST_PATH) as f:
            for line in f:
                w = line.strip().upper()
                if min_len <= len(w) <= max_len and w.isalpha():
                    n += 1
    except FileNotFoundError:
        pass
    return n


def _count_numeric(min_d: int, max_d: int) -> int:
    return sum(10 ** i for i in range(min_d, max_d + 1))


def _count_alpha(min_l: int, max_l: int) -> int:
    return sum(26 ** i for i in range(min_l, max_l + 1))


def _fmt_time(total: int, min_delay: float, max_delay: float) -> str:
    avg = (min_delay + max_delay) / 2
    seconds = math.ceil(total / BATCH_SIZE) * avg
    minutes = seconds / 60
    if minutes < 1:
        return "< 1 min"
    elif minutes < 60:
        return f"~{int(minutes)} min"
    else:
        return f"~{minutes / 60:.1f} hrs"


def _size_color(total: int) -> str:
    if total < 1_000:
        return "green"
    elif total < 10_000:
        return "yellow"
    elif total < 100_000:
        return "bold yellow"
    return "bold red"


def _pick_speed() -> tuple[str, float, float]:
    console.print()
    console.print("  Scan speed:")
    for i, (name, disp, _, __) in enumerate(SPEEDS, 1):
        rec = "  [dim](recommended)[/dim]" if i == 2 else ""
        console.print(f"  [cyan]{i}[/cyan]  {name:<10}{disp}{rec}")
    console.print()
    s = Prompt.ask("  Speed", choices=["1", "2", "3"], default="2")
    name, _, mn, mx = SPEEDS[int(s) - 1]
    return name, mn, mx


def _confirm_scan(label: str, total: int, speed_name: str, min_delay: float, max_delay: float) -> bool:
    color = _size_color(total)
    est = _fmt_time(total, min_delay, max_delay)

    console.print()
    console.print(Rule(style="dim"))
    console.print()
    console.print(f"  Scan:          [bold]{label}[/bold]")
    console.print(f"  Combinations:  [{color}]{total:,}[/{color}]")
    console.print(f"  Speed:         [bold]{speed_name}[/bold]  [dim]({min_delay:.1f}–{max_delay:.1f}s/batch)[/dim]")
    console.print(f"  Est. time:     [bold]{est}[/bold]")
    console.print()

    if total >= 100_000:
        console.print("  [bold red]  Very large scan.[/bold red] This could run for hours.")
        console.print("  [dim]  Narrow your length range or use a pattern instead.[/dim]")
    elif total >= 10_000:
        console.print("  [yellow]  Large scan — grab a coffee.[/yellow]")

    console.print()
    console.print("  [dim]  Plates checked in the last 24h are automatically skipped.[/dim]")
    console.print("  [dim]  Longer plate lengths multiply combinations exponentially.[/dim]")
    console.print("  [bold yellow]  VPN recommended[/bold yellow][dim] — repeated requests from the same IP[/dim]")
    console.print("  [dim]  may trigger rate-limiting from the Florida DMV.[/dim]")
    console.print()

    return Confirm.ask("  Start scan?", default=True)


def _render_scan(task: SearchTask, total: int, label: str) -> Panel:
    stats = task.get_status()
    checked = stats["checked"]
    available = stats["available"]
    rate = stats["rate"]
    current = stats.get("current_plate") or "…"
    running = stats["running"]
    recent = stats.get("recent_found", [])

    pct = min(checked / total, 1.0) if total else 0
    bar_width = 38
    filled = int(bar_width * pct)
    bar = "█" * filled + "░" * (bar_width - filled)

    body = Text()
    body.append(f"\n  {bar}  ", style="cyan")
    body.append(f"{pct * 100:5.1f}%", style="bold yellow")
    body.append(f"  {checked:,}", style="white")
    if total:
        body.append(f" / {total:,}", style="dim")
    body.append("\n\n")

    body.append("  Checked  ", style="dim")
    body.append(f"{checked:,}   ", style="bold white")
    body.append("Available  ", style="dim")
    body.append(f"{available}   ", style="bold green")
    body.append("Rate  ", style="dim")
    body.append(f"{rate:.1f}/min   ", style="bold cyan")
    body.append("Current  ", style="dim")
    body.append(f"{current}\n", style="bold yellow")

    if recent:
        body.append("\n  Found:  ", style="dim")
        for p in recent[:10]:
            body.append(f" {p} ", style="bold black on green")
        body.append("\n")

    body.append("\n")
    if running:
        body.append("  Ctrl+C to stop\n", style="dim")
    else:
        body.append("  Scan complete!\n", style="bold green")

    return Panel(body, title=f"[bold cyan]SCANNING  ·  {label}[/bold cyan]", border_style="cyan", padding=(0, 1))


def _run_scan(config: dict, label: str, total: int, min_delay: float, max_delay: float) -> tuple[dict, str | None]:
    task = SearchTask()
    task.start(config)

    try:
        with Live(console=console, refresh_per_second=4, screen=False) as live:
            while task.running:
                live.update(_render_scan(task, total, label))
                time.sleep(0.25)
            live.update(_render_scan(task, total, label))
    except KeyboardInterrupt:
        task.stop()
        console.print("\n  [yellow]Scan stopped.[/yellow]")

    s = task.get_status()
    console.print(
        f"\n  Done.  Checked [cyan]{s['checked']:,}[/cyan] plates this session  ·  "
        f"[bold green]{s['available']}[/bold green] available found\n"
    )
    return s, task.session_id


def _show_session_results(session_id: str | None):
    """Show available plates from this scan session and the database path."""
    if not session_id:
        return

    plates = queries.get_session_available(session_id)
    db_path = os.path.abspath("plates.db")

    console.print(Rule("[bold green]AVAILABLE FROM THIS SCAN[/bold green]", style="green"))
    console.print()

    if not plates:
        console.print("  [dim]No available plates found in this session.[/dim]")
    else:
        table = Table(
            box=box.ROUNDED,
            border_style="green",
            header_style="bold green",
            title=f"[bold]{len(plates)} plate{'s' if len(plates) != 1 else ''} available[/bold]",
            show_lines=False,
        )
        table.add_column("PLATE", style="bold yellow", min_width=8)
        table.add_column("LEN", justify="center", style="dim", min_width=4)
        table.add_column("TYPE", style="dim", min_width=10)
        table.add_column("CHECKED AT", style="dim", min_width=18)

        for p in plates:
            ts = (p.get("checked_at") or "")[:19].replace("T", " ")
            table.add_row(
                p["plate"],
                str(p.get("plate_length") or len(p["plate"])),
                p.get("plate_type") or "—",
                ts,
            )
        console.print(table)

    console.print(f"\n  [dim]Results saved to:[/dim]  [bold cyan]{db_path}[/bold cyan]")
    console.print()


# ── scan sub-flows ────────────────────────────────────────────────────────────

def _scan_numeric() -> bool:
    console.print()
    console.print("  [bold]Numeric[/bold] — zero-padded number plates  (e.g. 07, 007, 2024)")
    console.print("  [dim]Digit counts:  2 = 100  ·  3 = 1,000  ·  4 = 10,000  ·  5 = 100,000[/dim]")
    console.print()
    min_d = _ask_int("  Min digits", default=2, lo=2, hi=7)
    max_d = _ask_int("  Max digits", default=3, lo=min_d, hi=7)
    total = _count_numeric(min_d, max_d)
    speed_name, min_delay, max_delay = _pick_speed()
    if not _confirm_scan(f"Numeric  {min_d}–{max_d} digits", total, speed_name, min_delay, max_delay):
        return False
    config = {
        "numeric": True, "numeric_min_len": min_d, "numeric_max_len": max_d,
        "min_delay": min_delay, "max_delay": max_delay,
    }
    _, sid = _run_scan(config, f"NUMERIC  {min_d}–{max_d} digits", total, min_delay, max_delay)
    _show_session_results(sid)
    return True


def _scan_alpha() -> bool:
    console.print()
    console.print("  [bold]Alpha[/bold] — pure letter plates  (e.g. OO, ZZZ, XAX, AXX, TOO, MIAMI)")
    console.print("  [dim]Only letters — great for vanity and personalized plates.[/dim]")
    console.print("  [dim]Letter counts:  2 = 676  ·  3 = 17,576  ·  4 = 456,976[/dim]")
    console.print("  [dim]Tip: start at 2–3 letters. 4+ is a very large scan.[/dim]")
    console.print()
    min_a = _ask_int("  Min letters", default=2, lo=2, hi=7)
    max_a = _ask_int("  Max letters", default=3, lo=min_a, hi=7)
    total = _count_alpha(min_a, max_a)
    speed_name, min_delay, max_delay = _pick_speed()
    if not _confirm_scan(f"Alpha  {min_a}–{max_a} letters", total, speed_name, min_delay, max_delay):
        return False
    config = {
        "alpha": True, "alpha_min_len": min_a, "alpha_max_len": max_a,
        "min_delay": min_delay, "max_delay": max_delay,
    }
    _, sid = _run_scan(config, f"ALPHA  {min_a}–{max_a} letters", total, min_delay, max_delay)
    _show_session_results(sid)
    return True


def _scan_words() -> bool:
    console.print()
    console.print("  [bold]Words[/bold] — real dictionary words  (e.g. ACE, COOL, WOLF, BLAZE)")
    console.print("  [dim]Pulls from the built-in wordlist — curated, cleaner than raw alpha.[/dim]")
    console.print()
    min_w = _ask_int("  Min letters", default=3, lo=2, hi=7)
    max_w = _ask_int("  Max letters", default=5, lo=min_w, hi=7)
    total = _count_words(min_w, max_w)
    if total == 0:
        console.print("  [yellow]No words found in that range.[/yellow]")
        time.sleep(1.5)
        return False
    speed_name, min_delay, max_delay = _pick_speed()
    if not _confirm_scan(f"Words  {min_w}–{max_w} letters  ({total:,} words)", total, speed_name, min_delay, max_delay):
        return False
    config = {
        "words": True, "words_min_len": min_w, "words_max_len": max_w,
        "min_delay": min_delay, "max_delay": max_delay,
    }
    _, sid = _run_scan(config, f"WORDS  {min_w}–{max_w} letters", total, min_delay, max_delay)
    _show_session_results(sid)
    return True


def _scan_pattern() -> bool:
    console.print()
    console.print("  [bold]Pattern[/bold] — define your own search with wildcards:")
    console.print("  [bold]?[/bold] = any letter or digit   [bold]#[/bold] = digit only   [bold]@[/bold] = letter only")
    console.print("  Examples:  [bold yellow]OO?[/bold yellow]   [bold yellow]FL###[/bold yellow]   [bold yellow]X?X[/bold yellow]   [bold yellow]@@@@[/bold yellow]   [bold yellow]007?[/bold yellow]   [bold yellow]MIAMI[/bold yellow]")
    console.print()
    pat = Prompt.ask("  Pattern").strip().upper()
    if not pat:
        return False
    if len(pat) < 2:
        console.print("[red]  Minimum 2 characters (Florida plate minimum).[/red]")
        time.sleep(2)
        return False
    total = estimate_pattern_count(pat)
    if total == 0:
        console.print("[red]  Invalid pattern — use letters, digits, ?, #, @  (max 7 chars)[/red]")
        time.sleep(2)
        return False
    speed_name, min_delay, max_delay = _pick_speed()
    if not _confirm_scan(f"Pattern: {pat}", total, speed_name, min_delay, max_delay):
        return False
    config = {
        "pattern": True, "pattern_string": pat,
        "min_delay": min_delay, "max_delay": max_delay,
    }
    _, sid = _run_scan(config, f"PATTERN: {pat}", total, min_delay, max_delay)
    _show_session_results(sid)
    return True


def _scan_sweep() -> bool:
    console.print()
    console.print("  [bold]Full Sweep[/bold] — Numeric (2–3 digits) + Words (3–5 letters)")
    console.print("  [dim]Best starting point for a broad first pass at clean short plates.[/dim]")
    console.print()
    speed_name, min_delay, max_delay = _pick_speed()
    total = _count_numeric(2, 3) + _count_words(3, 5)
    if not _confirm_scan("Full Sweep  (Numeric 2–3 + Words 3–5)", total, speed_name, min_delay, max_delay):
        return False
    config = {
        "numeric": True, "numeric_min_len": 2, "numeric_max_len": 3,
        "words": True, "words_min_len": 3, "words_max_len": 5,
        "min_delay": min_delay, "max_delay": max_delay,
    }
    _, sid = _run_scan(config, "FULL SWEEP", total, min_delay, max_delay)
    _show_session_results(sid)
    return True


# ── scan menu ─────────────────────────────────────────────────────────────────

def menu_scan():
    _banner()
    console.print(Rule("[bold]SELECT SCAN TYPE[/bold]", style="cyan"))
    console.print()
    console.print("  [bold cyan]1[/bold cyan]  Numeric      Zero-padded numbers   (07, 007, 2024)")
    console.print("  [bold cyan]2[/bold cyan]  Alpha        Pure letters           (OO, ZZZ, XAX, TOO)")
    console.print("  [bold cyan]3[/bold cyan]  Words        Dictionary words       (ACE, WOLF, BLAZE)")
    console.print("  [bold cyan]4[/bold cyan]  Pattern      Custom wildcard         (OO?, FL###, X?X)")
    console.print("  [bold cyan]5[/bold cyan]  Full Sweep   Numeric + Words         (broad first scan)")
    console.print("  [bold cyan]b[/bold cyan]  Back")
    console.print()

    choice = Prompt.ask("  Select", choices=["1", "2", "3", "4", "5", "b"], default="b")
    if choice == "b":
        return

    if choice == "1":
        _scan_numeric()
    elif choice == "2":
        _scan_alpha()
    elif choice == "3":
        _scan_words()
    elif choice == "4":
        _scan_pattern()
    elif choice == "5":
        _scan_sweep()


# ── single plate check ────────────────────────────────────────────────────────

def menu_check():
    _banner()
    console.print(Rule("[bold]CHECK A PLATE[/bold]", style="cyan"))
    console.print()
    console.print("  Live DMV lookup for any Florida vanity plate.")
    console.print()
    raw = Prompt.ask("  Plate").strip().upper()
    if not raw or not raw.isalnum() or len(raw) < 2 or len(raw) > 7:
        console.print("[red]  Invalid — 2–7 letters and numbers only.[/red]")
        time.sleep(2)
        return

    cached = queries.get_plate(raw)
    if cached:
        _show_plate_result(raw, cached["status"], cached.get("checked_at", ""), from_cache=True)
        Prompt.ask("\n  Enter to continue", default="")
        return

    console.print(f"\n  Looking up [bold yellow]{raw}[/bold yellow] …")
    try:
        ps = PlateSession()
        ps.get_tokens()
        results = check_batch([raw], ps, RateLimiter(0, 0))
        if results:
            r = results[0]
            queries.insert_results([r])
            _show_plate_result(raw, r["status"], r.get("checked_at", ""), from_cache=False)
    except Exception as e:
        console.print(f"[red]  Error: {e}[/red]")

    Prompt.ask("\n  Enter to continue", default="")


def _show_plate_result(plate: str, status: str, checked_at: str, from_cache: bool):
    console.print()
    color = "bold green" if status == "AVAILABLE" else "bold red" if status == "UNAVAILABLE" else "yellow"
    cache_note = "  [dim](cached)[/dim]" if from_cache else ""
    ts = (checked_at or "")[:19].replace("T", " ")
    console.print(
        Panel(
            f"\n  [bold yellow]{plate}[/bold yellow]   [{color}]{status}[/{color}]{cache_note}\n"
            f"  [dim]{ts}[/dim]\n",
            border_style="green" if status == "AVAILABLE" else "red",
            padding=(0, 2),
        )
    )


# ── results browser ───────────────────────────────────────────────────────────

def menu_results():
    _banner()
    console.print(Rule("[bold]AVAILABLE PLATES[/bold]", style="cyan"))
    console.print()

    console.print("  Filter by type: [cyan]a[/cyan]=all  [cyan]n[/cyan]=numeric  [cyan]l[/cyan]=alpha  [cyan]w[/cyan]=word  [cyan]p[/cyan]=pattern")
    ftype = Prompt.ask("  Type", choices=["a", "n", "l", "w", "p"], default="a")
    type_map = {"a": None, "n": "numeric", "l": "alpha", "w": "word", "p": "pattern"}
    plate_type = type_map[ftype]

    max_len_str = Prompt.ask("  Max length  [Enter=any]", default="").strip()
    max_len = int(max_len_str) if max_len_str.isdigit() else None

    search_str = Prompt.ask("  Contains    [Enter=skip]", default="").strip()

    filters: dict = {}
    if plate_type:
        filters["plate_type"] = plate_type
    if max_len:
        filters["max_length"] = max_len
    if search_str:
        filters["search"] = search_str

    console.print()
    result = queries.get_available_plates(filters=filters, sort="length_asc", limit=200)
    plates = result["plates"]
    total = result["total"]

    if not plates:
        console.print("  [yellow]No available plates match your filters.[/yellow]")
    else:
        table = Table(
            box=box.ROUNDED,
            border_style="cyan",
            header_style="bold cyan",
            title=f"[bold]AVAILABLE[/bold]  ·  {total:,} plates",
            show_lines=False,
        )
        table.add_column("PLATE", style="bold yellow", min_width=8)
        table.add_column("LEN", justify="center", style="dim", min_width=4)
        table.add_column("TYPE", style="dim", min_width=10)
        table.add_column("CHECKED AT", style="dim", min_width=18)

        for p in plates:
            ts = (p.get("checked_at") or "")[:19].replace("T", " ")
            table.add_row(
                p["plate"],
                str(p.get("plate_length") or len(p["plate"])),
                p.get("plate_type") or "—",
                ts,
            )

        console.print(table)
        if total > len(plates):
            console.print(f"\n  [dim]Showing {len(plates)} of {total:,}. Use filters to narrow down.[/dim]")

    console.print()
    Prompt.ask("  Enter to continue", default="")


# ── reverify ──────────────────────────────────────────────────────────────────

def menu_reverify():
    _banner()
    console.print(Rule("[bold]REVERIFY AVAILABLE PLATES[/bold]", style="cyan"))
    console.print()
    console.print("  Re-checks every plate currently marked AVAILABLE against the live DMV.")
    console.print("  Use this to confirm plates are still open before claiming them.")
    console.print()

    result = queries.get_available_plates(limit=10_000)
    plates_to_check = [p["plate"] for p in result["plates"]]
    total = len(plates_to_check)

    if not plates_to_check:
        console.print("  [yellow]No available plates in the database yet.[/yellow]")
        console.print("  [dim]Run a scan first.[/dim]")
        console.print()
        Prompt.ask("  Enter to continue", default="")
        return

    est = _fmt_time(total, 1.5, 3.0)
    console.print(f"  Plates to check:  [cyan]{total}[/cyan]   Estimated: [bold]{est}[/bold]")
    console.print()

    if not Confirm.ask("  Start reverification?", default=True):
        return

    try:
        ps = PlateSession()
        ps.get_tokens()
    except Exception as e:
        console.print(f"[red]  Could not reach DMV: {e}[/red]")
        Prompt.ask("  Enter to continue", default="")
        return

    rl = RateLimiter(1.5, 3.0)
    still_ok: list[str] = []
    now_taken: list[str] = []
    checked = 0

    try:
        with Live(console=console, refresh_per_second=4, screen=False) as live:
            for i in range(0, total, BATCH_SIZE):
                batch = plates_to_check[i:i + BATCH_SIZE]
                results = check_batch(batch, ps, rl)
                queries.insert_results(results)

                for r in results:
                    checked += 1
                    if r["status"] == "AVAILABLE":
                        still_ok.append(r["plate"])
                    elif r["status"] == "UNAVAILABLE":
                        now_taken.append(r["plate"])

                pct = checked / total
                bw = 38
                bar = "█" * int(bw * pct) + "░" * (bw - int(bw * pct))

                body = Text()
                body.append(f"\n  {bar}  ", style="cyan")
                body.append(f"{pct * 100:5.1f}%  {checked}/{total}\n\n", style="yellow")
                body.append("  Still available  ", style="dim")
                body.append(f"{len(still_ok)}   ", style="bold green")
                body.append("Now taken  ", style="dim")
                body.append(f"{len(now_taken)}\n\n", style="bold red")
                if batch:
                    body.append("  Current  ", style="dim")
                    body.append(f"{batch[0]}\n", style="bold yellow")

                live.update(Panel(body, title="[bold cyan]REVERIFYING[/bold cyan]", border_style="cyan", padding=(0, 1)))
                rl.wait()
    except KeyboardInterrupt:
        console.print("\n  [yellow]Stopped.[/yellow]")

    console.print(
        f"\n  [bold green]{len(still_ok)} still available[/bold green]  ·  "
        f"[bold red]{len(now_taken)} now taken[/bold red]\n"
    )

    if still_ok:
        console.print(Rule("[bold green]CONFIRMED AVAILABLE[/bold green]", style="green"))
        console.print()
        table = Table(box=box.ROUNDED, border_style="green", header_style="bold green", show_lines=False)
        table.add_column("PLATE", style="bold yellow", min_width=8)
        table.add_column("LEN", justify="center", style="dim", min_width=4)
        for plate in still_ok:
            table.add_row(plate, str(len(plate)))
        console.print(table)
        console.print()

    console.print(f"  [dim]Updated results saved to:[/dim]  [bold cyan]{os.path.abspath('plates.db')}[/bold cyan]")
    console.print()
    Prompt.ask("  Enter to continue", default="")


# ── stats ─────────────────────────────────────────────────────────────────────

def menu_stats():
    _banner()
    console.print(Rule("[bold]DATABASE STATS[/bold]", style="cyan"))
    console.print()

    stats = queries.get_stats()
    last_run = queries.get_last_scanner_run()
    last_checked = queries.get_last_checked_at()

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column(style="dim cyan", min_width=24)
    table.add_column(style="bold white", justify="right")

    table.add_row("Total plates checked", f"{stats['total_checked']:,}")
    table.add_row("Available", f"[bold green]{stats.get('available', 0):,}[/bold green]")
    table.add_row("Unavailable", f"{stats['by_status'].get('UNAVAILABLE', 0):,}")
    table.add_row("Errors / unknown", f"{stats['by_status'].get('ERROR', 0):,}")
    table.add_row("", "")

    for ptype, count in sorted(stats.get("by_type", {}).items()):
        table.add_row(f"  by type: {ptype}", f"{count:,}")

    if last_run or last_checked:
        table.add_row("", "")
    if last_run:
        table.add_row("Last scan completed", last_run[:19].replace("T", " "))
    if last_checked:
        table.add_row("Last plate checked", last_checked[:19].replace("T", " "))

    console.print(table)
    console.print()
    console.print(f"  [dim]Database file:[/dim]  [bold cyan]{os.path.abspath('plates.db')}[/bold cyan]")
    console.print()
    Prompt.ask("  Enter to continue", default="")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    init_db()

    while True:
        _banner()
        stats = queries.get_stats()
        last_checked = queries.get_last_checked_at()

        console.print(Rule("[bold cyan]MAIN MENU[/bold cyan]"))
        console.print()

        available = stats.get("available", 0)
        if last_checked:
            last_ts = last_checked[:10]
            console.print(
                f"  Available: [bold green]{available:,}[/bold green] plates  "
                f"·  Last scan: [dim]{last_ts}[/dim]"
            )
        else:
            console.print("  [dim]No scans on record yet — start a scan to find available plates.[/dim]")

        console.print()
        console.print("  [bold cyan]1[/bold cyan]  Start a scan")
        console.print("  [bold cyan]2[/bold cyan]  Check a single plate    [dim](live DMV lookup)[/dim]")
        console.print("  [bold cyan]3[/bold cyan]  View available plates")
        console.print("  [bold cyan]4[/bold cyan]  Reverify available       [dim](confirm plates are still open)[/dim]")
        console.print("  [bold cyan]5[/bold cyan]  Stats")
        console.print("  [bold cyan]q[/bold cyan]  Quit")
        console.print()

        choice = Prompt.ask("  Select", choices=["1", "2", "3", "4", "5", "q"], default="q")

        if choice == "1":
            menu_scan()
        elif choice == "2":
            menu_check()
        elif choice == "3":
            menu_results()
        elif choice == "4":
            menu_reverify()
        elif choice == "5":
            menu_stats()
        elif choice == "q":
            console.print("\n  [dim]Good luck hunting.[/dim]\n")
            break


if __name__ == "__main__":
    main()
