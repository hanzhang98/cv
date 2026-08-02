from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Allow `python -m cli` from bot/ with src on path
SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rich.console import Console
from rich.table import Table

from pipeline import IdeaPipeline

console = Console()


async def cmd_digest(theme: str | None, limit: int, as_json: bool) -> None:
    pipe = IdeaPipeline()
    ideas = await pipe.digest(theme_id=theme, limit=limit)
    if as_json:
        payload = [
            {
                "score": i.score,
                "noise": i.noise_score,
                "title": i.item.title,
                "source": i.item.source_name,
                "url": i.item.url,
                "themes": [h.theme_id for h in i.theme_hits],
                "rationale": i.rationale,
            }
            for i in ideas
        ]
        console.print_json(json.dumps(payload))
        return

    table = Table(title="Investment idea digest", show_lines=True)
    table.add_column("Score", justify="right", width=6)
    table.add_column("Noise", justify="right", width=5)
    table.add_column("Theme", width=22)
    table.add_column("Title")
    table.add_column("Source", width=16)
    for i in ideas:
        theme_label = i.primary_theme or "—"
        table.add_row(
            f"{i.score:.2f}",
            f"{i.noise_score:.2f}",
            theme_label,
            i.item.title[:80],
            i.item.source_name[:16],
        )
    console.print(table)
    for i in ideas:
        if i.rationale:
            console.print(f"• [dim]{i.item.title[:60]}[/dim]: {i.rationale}")


async def cmd_themes() -> None:
    pipe = IdeaPipeline()
    for tid, label, desc in pipe.list_themes():
        console.print(f"[bold]{tid}[/bold] — {label}\n  {desc}\n")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Investment ideas CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_digest = sub.add_parser("digest", help="Score and print idea digest")
    p_digest.add_argument("--theme", default=None, help="Theme id filter")
    p_digest.add_argument("-n", "--limit", type=int, default=12)
    p_digest.add_argument("--json", action="store_true")

    sub.add_parser("themes", help="List themes")

    args = parser.parse_args(argv)
    if args.cmd == "digest":
        asyncio.run(cmd_digest(args.theme, args.limit, args.json))
    elif args.cmd == "themes":
        asyncio.run(cmd_themes())


if __name__ == "__main__":
    main()
