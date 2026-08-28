"""판정을 사후에 채점한다.

판정 시점에는 기준일만 박아두고 가격을 건드리지 않는다. 채점은 지평이
경과한 뒤 이 모듈이 과거 시세를 읽어서 수행한다. 그래야 판정 API가
외부 네트워크에 묶이지 않고, 채점도 언제든 재현·재실행할 수 있다.
"""
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .store import JudgementStore

PRICE_SOURCE = "FinanceDataReader"

# 지평은 거래일 기준이다. 시세를 넉넉히 받아 실제 거래일로 세어 나간다.
_CALENDAR_PAD = 2.2


def _fetch_closes(ticker: str, start: date, end: date) -> List[Tuple[date, float]]:
    import FinanceDataReader as fdr

    df = fdr.DataReader(ticker, start=start, end=end)
    if df is None or df.empty:
        return []

    close_col = next((c for c in df.columns if c.lower().strip() == "close"), None)
    if close_col is None:
        return []

    out: List[Tuple[date, float]] = []
    for idx, value in df[close_col].items():
        d = idx.date() if hasattr(idx, "date") else idx
        if value is None:
            continue
        out.append((d, float(value)))
    return out


def _score_one(closes: List[Tuple[date, float]], as_of: date,
               horizon_days: int, result: bool) -> Optional[Dict[str, Any]]:
    """as_of 이후 첫 거래일을 진입, 거기서 horizon_days 거래일 뒤를 청산으로 본다."""
    entry_idx = next((i for i, (d, _) in enumerate(closes) if d >= as_of), None)
    if entry_idx is None:
        return None

    exit_idx = entry_idx + horizon_days
    if exit_idx >= len(closes):
        return None

    entry_date, entry_price = closes[entry_idx]
    exit_date, exit_price = closes[exit_idx]
    if not entry_price:
        return None

    return_pct = round((exit_price / entry_price - 1) * 100, 4)
    # 판정이 true면 상승을, false면 하락을 예측한 것으로 본다.
    hit = return_pct > 0 if result else return_pct <= 0

    return {
        "entry_date": entry_date.isoformat(),
        "entry_price": entry_price,
        "exit_date": exit_date.isoformat(),
        "exit_price": exit_price,
        "return_pct": return_pct,
        "hit": hit,
    }


def score_pending(store: JudgementStore, limit: int = 500,
                  today: Optional[date] = None,
                  retry_unavailable: bool = False) -> Dict[str, Any]:
    """채점 대기 중인 판정을 훑어 결과를 채운다.

    아직 지평이 경과하지 않은 건은 pending으로 남긴다. 시세를 못 구한
    건은 unavailable로 표시하고 사유를 남기는데, 일시적 장애일 수 있으므로
    retry_unavailable로 다시 훑을 수 있다.
    """
    today = today or date.today()
    pending = store.pending_outcomes(limit=limit, include_unavailable=retry_unavailable)
    now = datetime.now().isoformat()

    stats = {"checked": len(pending), "scored": 0, "still_pending": 0, "unavailable": 0}
    if not pending:
        return {**stats, "errors": []}

    # 같은 종목은 시세를 한 번만 받는다.
    price_cache: Dict[str, List[Tuple[date, float]]] = {}
    errors: List[str] = []

    for row in pending:
        ticker = row["normalized_ticker"]
        as_of = date.fromisoformat(row["as_of_date"])
        horizon = row["horizon_days"]

        # 거래일 기준 지평이 아직 안 지났으면 시세를 받을 것도 없다.
        if as_of + timedelta(days=int(horizon * _CALENDAR_PAD) + 5) > today:
            stats["still_pending"] += 1
            continue

        if ticker not in price_cache:
            try:
                price_cache[ticker] = _fetch_closes(
                    ticker, as_of - timedelta(days=7), today
                )
            except Exception as exc:
                price_cache[ticker] = []
                errors.append(f"{ticker}: {exc}")

        closes = price_cache[ticker]
        if not closes:
            store.record_outcome(
                row["judgement_id"], horizon, status="unavailable",
                evaluated_at=now, price_source=PRICE_SOURCE,
                note="시세를 가져오지 못했습니다.",
            )
            stats["unavailable"] += 1
            continue

        scored = _score_one(closes, as_of, horizon, bool(row["result"]))
        if scored is None:
            stats["still_pending"] += 1
            continue

        store.record_outcome(
            row["judgement_id"], horizon, status="scored",
            evaluated_at=now, price_source=PRICE_SOURCE, **scored,
        )
        stats["scored"] += 1

    return {**stats, "errors": errors}
