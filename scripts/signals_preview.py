"""Developer harness for the Signals Report pipeline — no real newsletter history required.

A fresh install has zero observation history, so without this script the trend prompt,
the metrics gates, and the report template are all impossible to exercise or tune for
about a week (FR-030, SC-011). `--synthesize N` fabricates plausible multi-sender
observations across rising, fading, new, and steady patterns so every report section has
something to show.

Usage:
    python scripts/signals_preview.py --synthesize 30 --no-llm   # metrics only, zero API calls
    python scripts/signals_preview.py --open                     # render + open in browser
    python scripts/signals_preview.py --db /path/to.db --synthesize 10

Defaults to a stable temp database shared across invocations in this dev session so a
`--synthesize` run followed by a plain run sees the same data. **Never** touches
`data/signals.db` — pass `--db` explicitly if you really want a different target, and the
script refuses if that target resolves to the real store.

Requires ANTHROPIC_API_KEY in .env for the (default) LLM-backed render; `--no-llm` skips it.
"""

from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from agent.knowledge.store import ObservationStore
from agent.trends.metrics import compute_brief
from agent.utils.config import SignalsConfig
from agent.utils.models import EntityMention, Idea, Summary

load_dotenv()

_DEFAULT_DB_PATH = str(Path(tempfile.gettempdir()) / "newsletter_digest_agent_signals_preview.db")
_REAL_STORE_PATH = str(Path("data/signals.db").resolve())

_SYNTH_SENDERS = [
    "alpha-brief@example.com",
    "beacon-weekly@example.com",
    "capital-notes@example.com",
    "delta-markets@example.com",
    "edgewise@example.com",
]

_SYNTH_NAMES = [
    ("Nvidia", "company"), ("Federal Reserve", "institution"), ("export controls", "policy"),
    ("TSMC", "company"), ("China", "country"), ("AI infrastructure", "sector"),
    ("Tesla", "company"), ("interest rates", "concept"), ("OpenAI", "company"),
    ("semiconductor tariffs", "policy"), ("crude oil", "asset"), ("data centers", "technology"),
    ("Apple", "company"), ("Microsoft", "company"), ("bond yields", "concept"),
    ("Rivian", "company"), ("EV subsidies", "policy"), ("United Airlines", "company"),
    ("jet fuel prices", "concept"), ("SpaceX", "company"), ("Amazon", "company"),
    ("cloud spending", "sector"), ("Meta", "company"), ("ad revenue", "concept"),
    ("ECB", "institution"), ("eurozone inflation", "concept"), ("Boeing", "company"),
    ("aircraft deliveries", "concept"), ("Saudi Arabia", "country"), ("OPEC+", "institution"),
]

_COMPANION = ("export controls", "policy")


def _record(store: ObservationStore, name: str, entity_type: str, sender: str, when: datetime,
            counter: int, companion: bool = False) -> None:
    entities = [EntityMention(name=name, entity_type=entity_type, sentiment=random.choice(["positive", "negative", "neutral"]))]
    if companion:
        entities.append(EntityMention(name=_COMPANION[0], entity_type=_COMPANION[1], sentiment="negative"))
    idea = Idea(title=f"{name} update", summary_text=f"Synthetic claim about {name}, sample #{counter}.", entities=tuple(entities))
    summary = Summary(
        email_id=f"synth-{counter}",
        sender=sender,
        subject=f"{name} coverage",
        summary_text="",
        word_count=0,
        generated_at=when,
        ideas=(idea,),
    )
    store.record_summary(summary)


def _schedule_for(category: str) -> list[tuple[int, int, int]]:
    """Return (days_ago, mentions_that_day, distinct_senders_that_day) tuples."""
    if category == "rising":
        return [
            (28, 1, 1), (24, 1, 1), (20, 1, 1), (17, 2, 1),  # distant history, for z-score baseline
            (12, 2, 2), (10, 2, 2), (8, 2, 2),                 # prior window
            (5, 3, 2), (4, 3, 3), (3, 4, 3), (2, 4, 3), (1, 5, 4), (0, 5, 4),  # current window
        ]
    if category == "fading":
        return [(12, 2, 2), (10, 3, 2), (8, 2, 2)]  # prior window only, nothing current
    if category == "new":
        return [(3, 2, 2), (1, 3, 3), (0, 2, 2)]  # current window only, nothing prior
    # steady — roughly constant across both windows, background realism
    return [(12, 1, 1), (10, 1, 2), (8, 1, 1), (5, 1, 1), (3, 1, 2), (1, 1, 1)]


def _synthesize(store: ObservationStore, count: int) -> None:
    pool = list(_SYNTH_NAMES)
    random.shuffle(pool)
    pool = (pool * ((count // len(pool)) + 1))[:count]
    categories = ["rising", "fading", "new", "steady"]
    now = datetime.now(timezone.utc)

    counter = 0
    for i, (name, entity_type) in enumerate(pool):
        category = categories[i % len(categories)]
        schedule = _schedule_for(category)
        for days_ago, mentions, sender_count in schedule:
            when = now - timedelta(days=days_ago, hours=random.randint(0, 20))
            for m in range(mentions):
                counter += 1
                sender = _SYNTH_SENDERS[(counter + m) % max(sender_count, 1) % len(_SYNTH_SENDERS)]
                companion = category == "rising" and days_ago <= 2
                _record(store, name, entity_type, sender, when, counter, companion=companion)

    print(f"Synthesized {count} entities across rising/fading/new/steady patterns ({counter} observations).")


def _synthesize_signal_calls(store: ObservationStore) -> None:
    """Insert a few back-dated signal_call rows so the Track Record section can be
    exercised without waiting a week. Uses tickers outside the profile so no
    network fetch is attempted; mention stats come from _synthesize output."""
    from agent.utils.models import SignalItem, SignalsReport

    now = datetime.now(timezone.utc)
    for days_ago, headline, entities in [
        (8, "Data center demand still climbing", ("Nvidia",)),
        (31, "Export controls tighten on semis", ("export controls",)),
        (2, "Too fresh to review", ("Tesla",)),
    ]:
        report_date = (now - timedelta(days=days_ago)).date()
        report = SignalsReport(
            generated_at=now,
            window_days=7,
            macro=None,
            opportunities=(
                SignalItem(headline=headline, body="Synthetic back-dated call.", confidence="HIGH", entities=entities),
            ),
        )
        store.record_signal_calls(report, report_date, ticker_for=lambda names: None)
    print("Synthesized 3 back-dated signal calls (8d, 31d due; 2d not yet due).")


def _print_brief(brief) -> None:
    print(
        f"\nBrief: {len(brief.trends)} entities, {len(brief.new_edges)} new co-occurrences, "
        f"cold_start={brief.is_cold_start}, total_observations={brief.total_observations}"
    )
    for t in brief.trends:
        flag = "NEW" if t.is_new else ("FADING" if t.is_fading else "")
        z = f"{t.z_score:.2f}" if t.z_score is not None else "n/a"
        print(
            f"  {t.name:28s} cur={t.current_count:3d} prior={t.prior_count:3d} "
            f"delta={t.delta:+3d} sources={t.source_breadth} z={z:>6s} {flag}"
        )
    if brief.new_edges:
        print("\nNew co-occurrences:")
        for e in brief.new_edges:
            print(f"  {e.entity_a} + {e.entity_b} ({e.count}x)")
    if brief.alias_candidates:
        print("\nAlias candidates:")
        for a, b in brief.alias_candidates:
            print(f"  '{a}' / '{b}'")


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview the Signals Report pipeline against synthetic or real history.")
    parser.add_argument("--synthesize", type=int, default=0, metavar="N", help="Generate N synthetic entities before computing the brief.")
    parser.add_argument("--no-llm", action="store_true", help="Compute and print the brief only; skip the TrendAnalyzer call.")
    parser.add_argument("--open", action="store_true", help="Open the rendered HTML report in the browser.")
    parser.add_argument("--db", default=_DEFAULT_DB_PATH, help=f"Store path (default: a stable temp file at {_DEFAULT_DB_PATH}).")
    args = parser.parse_args()

    if str(Path(args.db).resolve()) == _REAL_STORE_PATH:
        print("Refusing to use data/signals.db — pass a different --db path.", file=sys.stderr)
        sys.exit(1)

    store = ObservationStore(args.db)
    print(f"Using store: {args.db}")

    if args.synthesize:
        _synthesize(store, args.synthesize)
        _synthesize_signal_calls(store)

    now = datetime.now(timezone.utc)
    config = SignalsConfig()
    brief = compute_brief(store, config, now)
    _print_brief(brief)

    if args.no_llm:
        print("\n--no-llm: skipping TrendAnalyzer call.")
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\nANTHROPIC_API_KEY not set — cannot run TrendAnalyzer. Use --no-llm to skip.", file=sys.stderr)
        sys.exit(1)

    from agent.trends.analyzer import TrendAnalyzer
    from agent.digest.builder import build_signals

    from agent.trends.track_record import build_track_record

    class _NoopFetcher:
        """Preview fetcher — no network; the section exercises mention stats only."""

        def daily_closes(self, ticker, start, end):
            return []

    track_record = build_track_record(store, None, _NoopFetcher(), now)
    print(f"Track record: {len(track_record)} reviews")

    print("\nRunning TrendAnalyzer …")
    analyzer = TrendAnalyzer(api_key=api_key, config=config, user_profile=None)
    report = analyzer.analyze(brief, macro=None, track_record=track_record)
    print(
        f"Report: risks={len(report.risks)} opportunities={len(report.opportunities)} "
        f"emerging={len(report.emerging)} fading={len(report.fading)} watch={len(report.watch)}"
    )

    html = build_signals(report, now)
    outputs_dir = Path("test_outputs")
    outputs_dir.mkdir(exist_ok=True)
    out_path = outputs_dir / f"{now.strftime('%Y-%m-%d_%H%M%S')}_signals.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"\nReport rendered. HTML saved to {out_path}")

    if args.open:
        subprocess.run(["open", str(out_path)], check=False)


if __name__ == "__main__":
    main()
