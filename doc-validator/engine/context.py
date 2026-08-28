"""판정에 쓸 컨텍스트를 조립한다.

라우터(LLM)와 판단 프로그램이 보는 입력은 전부 여기서 나온다. 그래서
JSON으로 직렬화되고, 그대로 판정 기록에 남길 수 있어야 한다.

컨텍스트는 두 층이다.
- symbol: 대상 종목 자체의 상태
- regime: 시장 전반의 상태. 라우터가 "지금이 어떤 국면인가"를 보고
  프로그램을 고르려면 대상 종목만으로는 부족하다.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import features as F
from .prices import PriceStore

# 국면 판단에 쓰는 기준 자산. 성격이 서로 다른 것들로 고른다.
REGIME_ASSETS = [
    ("SPY", "미국 대형주"),
    ("QQQ", "미국 기술주"),
    ("IWM", "미국 소형주"),
    ("TLT", "장기채"),
    ("GLD", "금"),
    ("UUP", "달러"),
    ("DBMF", "관리선물(역추세)"),
    ("BTC/USD", "암호화폐"),
    # 미국 자산만으로는 한국 시장이 설명되지 않는다.
    # (SPY와 KODEX200의 일간 수익률 상관은 +0.13에 불과하다)
    ("069500", "한국 대형주"),
]

RETURN_WINDOWS = [1, 5, 20, 60, 120, 252]
MAX_LOOKBACK = 400

# 횡단면 비교 축. 스타일별로 묶는다.
# 백분위는 원래 방향 그대로 매기고(값이 클수록 1에 가깝다), 방향 해석은
# 프로그램이 한다. 여기서 뒤집어두면 나중에 축을 다른 용도로 못 쓴다.
CROSS_AXES = {
    # 모멘텀. IC 측정에서 미국·한국 양쪽 t 2~7로 유의했던 것들.
    "momentum": ["ret_60d", "ret_120d", "px_vs_sma60", "slope60"],
    # 단기 반전. 값이 낮을수록 과매도다.
    "reversal": ["ret_5d", "ret_20d", "px_vs_sma20"],
    # 안정성. 변동성과 낙폭.
    "stability": ["vol_20d", "vol_ratio", "drawdown"],
}
MOMENTUM_AXES = CROSS_AXES["momentum"]
ALL_AXES = [a for axes in CROSS_AXES.values() for a in axes]

# (market, as_of) 단위로 동료 종목 지표를 재사용한다. 백테스트는 같은
# 날짜에 모든 종목을 훑으므로 이게 없으면 같은 계산을 수십 번 반복한다.
_PEER_CACHE: Dict[tuple, Dict[str, Dict[str, Optional[float]]]] = {}
_PEER_CACHE_MAX = 512


@dataclass
class MarketContext:
    symbol: str
    as_of: str
    meta: Dict[str, Any]
    price: Dict[str, Any]
    returns: Dict[str, Optional[float]]
    trend: Dict[str, Optional[float]]
    volatility: Dict[str, Optional[float]]
    drawdown: Optional[Dict[str, Any]]
    volume: Dict[str, Optional[float]]
    cross_section: Dict[str, Any]
    regime: Dict[str, Any]
    coverage: Dict[str, Any]
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "as_of": self.as_of,
            "meta": self.meta,
            "coverage": self.coverage,
            "price": self.price,
            "returns": self.returns,
            "trend": self.trend,
            "volatility": self.volatility,
            "drawdown": self.drawdown,
            "volume": self.volume,
            "cross_section": self.cross_section,
            "regime": self.regime,
            "warnings": self.warnings,
        }


def _returns(closes: List[float]) -> Dict[str, Optional[float]]:
    return {f"{d}d": F.ret(closes, d) for d in RETURN_WINDOWS}


def _trend(closes: List[float]) -> Dict[str, Optional[float]]:
    last = closes[-1]
    s20, s60, s120 = F.sma(closes, 20), F.sma(closes, 60), F.sma(closes, 120)
    return {
        "sma20": s20,
        "sma60": s60,
        "sma120": s120,
        "px_vs_sma20_pct": round((last / s20 - 1) * 100, 4) if s20 else None,
        "px_vs_sma60_pct": round((last / s60 - 1) * 100, 4) if s60 else None,
        "sma20_vs_sma60_pct": round((s20 / s60 - 1) * 100, 4) if s20 and s60 else None,
        "slope20_pct_per_day": F.slope_pct(closes, 20),
        "slope60_pct_per_day": F.slope_pct(closes, 60),
    }


def _volatility(closes: List[float]) -> Dict[str, Optional[float]]:
    v20, v60 = F.ann_volatility(closes, 20), F.ann_volatility(closes, 60)
    return {
        "ann_vol_20d_pct": v20,
        "ann_vol_60d_pct": v60,
        # 1보다 크면 최근 변동성이 확대되는 중이다.
        "vol_ratio_20_60": round(v20 / v60, 4) if v20 and v60 else None,
    }


def _regime_entry(store: PriceStore, symbol: str, as_of: str) -> Optional[Dict[str, Any]]:
    if not store.has(symbol):
        return None
    closes = store.closes(symbol, as_of, MAX_LOOKBACK)
    if len(closes) < 2:
        return None
    s20, s60 = F.sma(closes, 20), F.sma(closes, 60)
    return {
        "close": round(closes[-1], 4),
        "ret_20d_pct": F.ret(closes, 20),
        "ret_60d_pct": F.ret(closes, 60),
        "px_vs_sma60_pct": round((closes[-1] / s60 - 1) * 100, 4) if s60 else None,
        "sma20_above_sma60": (s20 > s60) if (s20 and s60) else None,
        "ann_vol_20d_pct": F.ann_volatility(closes, 20),
    }


def _axis_values(store: PriceStore, symbol: str, as_of: str) -> Dict[str, Optional[float]]:
    closes = store.closes(symbol, as_of, MAX_LOOKBACK)
    if len(closes) < 2:
        return {k: None for k in ALL_AXES}
    s20, s60 = F.sma(closes, 20), F.sma(closes, 60)
    v20, v60 = F.ann_volatility(closes, 20), F.ann_volatility(closes, 60)
    dd = F.drawdown_from_high(closes, 252) or {}
    return {
        "ret_5d": F.ret(closes, 5),
        "ret_20d": F.ret(closes, 20),
        "ret_60d": F.ret(closes, 60),
        "ret_120d": F.ret(closes, 120),
        "px_vs_sma20": round((closes[-1] / s20 - 1) * 100, 4) if s20 else None,
        "px_vs_sma60": round((closes[-1] / s60 - 1) * 100, 4) if s60 else None,
        "slope60": F.slope_pct(closes, 60),
        "vol_20d": v20,
        "vol_ratio": round(v20 / v60, 4) if v20 and v60 else None,
        "drawdown": dd.get("pct"),
    }


def _peer_axes(store: PriceStore, market: str, as_of: str) -> Dict[str, Dict]:
    key = (market, as_of, id(store))
    if key in _PEER_CACHE:
        return _PEER_CACHE[key]

    peers = [s for s in store.symbols if store.meta(s).market == market]
    out = {s: _axis_values(store, s, as_of) for s in peers}

    if len(_PEER_CACHE) >= _PEER_CACHE_MAX:
        _PEER_CACHE.clear()
    _PEER_CACHE[key] = out
    return out


def _cross_section(store: PriceStore, symbol: str, as_of: str,
                   market: str) -> Dict[str, Any]:
    """같은 시장 종목들 사이에서 이 종목이 몇 등인가.

    모멘텀은 횡단면 순위로 작동한다(IC 측정 결과). "60일 수익률이 0보다
    크다"는 절대 조건과 "동료 20종목 중 상위권"은 다른 이야기다.
    """
    axes = _peer_axes(store, market, as_of)
    me = axes.get(symbol) or {}

    pct: Dict[str, Optional[float]] = {}
    for axis in ALL_AXES:
        mine = me.get(axis)
        vals = [v[axis] for v in axes.values() if v.get(axis) is not None]
        if mine is None or len(vals) < 5:
            pct[axis] = None
            continue
        below = sum(1 for v in vals if v < mine)
        ties = sum(1 for v in vals if v == mine)
        pct[axis] = round((below + 0.5 * ties) / len(vals), 4)

    def composite(names: List[str]) -> Optional[float]:
        vals = [pct[a] for a in names if pct.get(a) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    styles = {k: composite(v) for k, v in CROSS_AXES.items()}
    scored = [v for v in pct.values() if v is not None]
    return {
        "market": market,
        "peer_count": len(axes),
        "ranked_axes": len(scored),
        "percentile": pct,
        # 스타일별 종합 백분위. 방향 해석은 프로그램이 한다.
        "styles": styles,
        # 모멘텀 종합. 하위 호환을 위해 남긴다.
        "composite": styles.get("momentum"),
    }


def build(store: PriceStore, symbol: str, as_of: str) -> MarketContext:
    """symbol에 대해 as_of 시점의 컨텍스트를 만든다."""
    meta = store.meta(symbol)
    bars = store.bars(symbol, as_of, MAX_LOOKBACK)
    warnings: List[str] = []

    if not bars:
        raise ValueError(f"{symbol}: {as_of} 이전 데이터가 없습니다.")

    closes = [b.close for b in bars]
    volumes = [b.volume for b in bars]
    last = bars[-1]

    if last.date != as_of:
        # 기준일이 휴장일이면 직전 거래일을 쓴다. 숨기지 않고 알린다.
        warnings.append(f"{as_of}는 거래일이 아니어서 직전 거래일 {last.date} 기준으로 계산했습니다.")
    if len(closes) < 120:
        warnings.append(f"봉이 {len(closes)}개뿐이라 장기 지표(120/252일)는 비어 있습니다.")

    regime = {}
    for sym, label in REGIME_ASSETS:
        entry = _regime_entry(store, sym, as_of)
        if entry:
            regime[sym] = {"label": label, **entry}

    return MarketContext(
        symbol=symbol,
        as_of=as_of,
        meta={
            "name": meta.name,
            "group": meta.group,
            "kind": meta.kind,
            "market": meta.market,
        },
        coverage={
            "bars_available": len(closes),
            "first_date": bars[0].date,
            "last_trading_date": last.date,
            "source": str(store.manifest_path.parent.name),
            "slice_id": store.slice_id,
        },
        price={
            "open": last.open, "high": last.high, "low": last.low,
            "close": last.close, "volume": last.volume,
        },
        returns=_returns(closes),
        trend=_trend(closes),
        volatility=_volatility(closes),
        drawdown=F.drawdown_from_high(closes, 252),
        volume={
            "avg20": round(sum(volumes[-20:]) / 20, 2) if len(volumes) >= 20 else None,
            "rel_vol_20_over_60_pct": F.relative_volume(volumes, 20, 60),
        },
        cross_section=_cross_section(store, symbol, as_of, meta.market),
        regime=regime,
        warnings=warnings,
    )
