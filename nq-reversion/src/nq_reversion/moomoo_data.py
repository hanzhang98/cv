from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def download_history(
    symbol: str,
    start: str,
    end: str,
    output: str | Path,
    host: str = "127.0.0.1",
    port: int = 11111,
) -> pd.DataFrame:
    """Download one exact futures contract through a local Moomoo OpenD.

    Contract symbols (for example ``US.NQ2612``) are required. This function
    intentionally does not manufacture a continuous contract because a
    hidden roll rule can create false mean-reversion signals.
    """
    if not symbol.startswith("US.NQ") or symbol.lower().endswith("main"):
        raise ValueError("use an exact NQ contract such as US.NQ2612, not a main contract")
    try:
        from moomoo import (  # type: ignore[import-not-found]
            AuType,
            KLType,
            OpenQuoteContext,
            RET_OK,
            Session,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Moomoo support is optional; install with: pip install -e '.[moomoo]'"
        ) from exc

    context: Any = OpenQuoteContext(host=host, port=port)
    pages: list[pd.DataFrame] = []
    page_key = None
    try:
        while True:
            result, data, page_key = context.request_history_kline(
                symbol,
                start=start,
                end=end,
                ktype=KLType.K_1M,
                autype=AuType.NONE,
                max_count=1000,
                page_req_key=page_key,
                session=Session.ALL,
            )
            if result != RET_OK:
                raise RuntimeError(f"Moomoo history request failed: {data}")
            pages.append(data)
            if page_key is None:
                break
    finally:
        context.close()

    if not pages:
        raise RuntimeError(f"Moomoo returned no data for {symbol}")
    frame = pd.concat(pages, ignore_index=True)
    frame["contract"] = symbol
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, index=False)
    return frame
