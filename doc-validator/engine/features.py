"""가격 시계열에서 뽑는 지표들. 순수 함수만 둔다.

전부 "마지막 원소가 기준일"인 리스트를 받는다. 미래 차단은 PriceStore가
이미 했으므로 여기서는 다시 확인하지 않는다.
"""
import math
from typing import List, Optional

TRADING_DAYS_PER_YEAR = 252


def _pct(a: float, b: float) -> Optional[float]:
    if not b:
        return None
    return round((a / b - 1) * 100, 4)


def ret(closes: List[float], days: int) -> Optional[float]:
    """N거래일 수익률(%)."""
    if len(closes) <= days:
        return None
    return _pct(closes[-1], closes[-1 - days])


def sma(closes: List[float], window: int) -> Optional[float]:
    if len(closes) < window:
        return None
    return round(sum(closes[-window:]) / window, 6)


def ann_volatility(closes: List[float], window: int) -> Optional[float]:
    """일간 로그수익률 표준편차의 연율화 값(%)."""
    if len(closes) < window + 1:
        return None
    rets = [
        math.log(closes[i] / closes[i - 1])
        for i in range(len(closes) - window, len(closes))
        if closes[i - 1] > 0 and closes[i] > 0
    ]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return round(math.sqrt(var) * math.sqrt(TRADING_DAYS_PER_YEAR) * 100, 4)


def slope_pct(closes: List[float], window: int) -> Optional[float]:
    """최근 window 구간 회귀 기울기를 평균가 대비 %로 환산(일당)."""
    if len(closes) < window:
        return None
    ys = closes[-window:]
    n = len(ys)
    mean_x = (n - 1) / 2
    mean_y = sum(ys) / n
    denom = sum((i - mean_x) ** 2 for i in range(n))
    if not denom or not mean_y:
        return None
    beta = sum((i - mean_x) * (ys[i] - mean_y) for i in range(n)) / denom
    return round(beta / mean_y * 100, 6)


def drawdown_from_high(closes: List[float], window: int) -> Optional[dict]:
    """최근 window 구간 고점 대비 낙폭(%)과 고점 이후 경과 거래일."""
    if not closes:
        return None
    seg = closes[-window:] if len(closes) >= window else closes
    peak = max(seg)
    idx = len(seg) - 1 - seg[::-1].index(peak)
    return {
        "pct": _pct(closes[-1], peak),
        "days_since_high": len(seg) - 1 - idx,
        "window_used": len(seg),
    }


def relative_volume(volumes: List[float], short: int, long: int) -> Optional[float]:
    """단기 평균 거래량이 장기 평균 대비 몇 %인가."""
    if len(volumes) < long:
        return None
    s = sum(volumes[-short:]) / short
    l = sum(volumes[-long:]) / long
    if not l:
        return None
    return round(s / l * 100, 2)
