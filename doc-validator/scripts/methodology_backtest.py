"""거래방법론 라우팅 + 월간 리밸런싱 + 트랜칭 백테스트.

세 가지를 같은 잣대로 비교한다.
  static     : E 조합 고정비중 (기존 결론)
  heuristic  : 규칙 라우터가 방법론을 고름
  llm        : LLM 라우터가 방법론을 고름

전부 원화 기준, 21일 주기, 트랜치 7개(시작일 0/3/6/.../18), 왕복 10bp.

선행편향 방지: 리밸런싱 날 d의 종가까지만 보고 비중을 정하고, 수익은
d+1부터 붙는다. 컨텍스트에 쓰는 이동평균·변동성도 전부 d 이하 데이터다.
"""
import csv
import math
import statistics as st
import sys
from bisect import bisect_right
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import PriceStore                                     # noqa: E402
from engine import portfolio_programs as pp                       # noqa: E402
from engine import portfolio_router as pr                         # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXTRA = ["XLE", "DBC", "BIL"]
UNIVERSE = list(pp.CORE) + EXTRA
COST_BP = 10
# 평가 통화. 기본은 원화. 기존 USD 기준 결과와 대조할 때만 False로 둔다.
USE_KRW = True
PERIOD = 21
# 자금을 21등분한다. 조각 k는 k일차부터 21일마다 되맞춘다.
TRANCHES = list(range(PERIOD))

store = PriceStore(ROOT / "fixtures" / "wide")

_fx = {}
for _r in csv.DictReader(open(ROOT / "fixtures" / "leaders" / "USD-KRW.csv",
                              encoding="utf-8")):
    try:
        _fx[_r["Date"]] = float(_r["Close"])
    except (KeyError, ValueError):
        pass
_fxd = sorted(_fx)
_usd = {}


def _series(sym):
    if sym not in _usd:
        _usd[sym] = {b.date: b.close for b in store._all_bars(sym)}
    return _usd[sym]


_krw = {}


def px(sym, date, krw=None):
    """원화 종가. 069500은 이미 원화다."""
    if krw is None:
        krw = USE_KRW
    if not krw:
        return _series(sym).get(date)
    key = (sym, date)
    if key not in _krw:
        raw = _series(sym).get(date)
        if raw is None or sym == "069500":
            _krw[key] = raw
        else:
            i = bisect_right(_fxd, date) - 1
            _krw[key] = raw * _fx[_fxd[i]] if i >= 0 else None
    return _krw[key]


CAL = sorted(_series("SPY"))
IDX = {d: i for i, d in enumerate(CAL)}


def _dates(sym):
    if not hasattr(_dates, "c"):
        _dates.c = {}
    if sym not in _dates.c:
        _dates.c[sym] = sorted(_series(sym))
    return _dates.c[sym]


def hist(sym, date, n, krw=True):
    """date 이하 마지막 n개 종가. 선행 없음."""
    ds = _dates(sym)
    j = bisect_right(ds, date)
    out = [px(sym, d, krw) for d in ds[max(0, j - n):j]]
    return [v for v in out if v is not None]


def ann_vol(prices):
    if len(prices) < 20:
        return None
    r = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))
         if prices[i - 1] > 0]
    return st.pstdev(r) * math.sqrt(252) * 100 if len(r) > 5 else None


def vs_ma(sym, date, n, krw=False):
    h = hist(sym, date, n, krw)
    if len(h) < n:
        return None
    return (h[-1] / (sum(h) / len(h)) - 1) * 100


_CTX_CACHE = {}


def build_ctx(date, available):
    """리밸런싱 날 컨텍스트. date 종가까지만 쓴다.

    같은 날짜·같은 가용종목이면 같은 컨텍스트다. 트랜치마다 다시
    계산할 이유가 없어 캐시한다.
    """
    ck = (date, tuple(available))
    if ck in _CTX_CACHE:
        return _CTX_CACHE[ck]
    ma = {s: vs_ma(s, date, 200, krw=True) for s in available}
    above = {s: (v > 0 if v is not None else True) for s, v in ma.items()}
    known = [v for v in ma.values() if v is not None]
    n_above = sum(1 for v in known if v > 0)

    # 코어 고정비중 포트폴리오의 최근 60일 실현변동성(원화)
    base = {s: w for s, w in pp.CORE.items() if s in available}
    tot = sum(base.values()) or 1
    base = {s: w / tot for s, w in base.items()}
    rets = []
    ds = [d for d in CAL if d <= date][-61:]
    for i in range(1, len(ds)):
        acc, wsum = 0.0, 0.0
        for s, w in base.items():
            a, b = px(s, ds[i - 1]), px(s, ds[i])
            if a and b:
                acc += w * (b / a - 1)
                wsum += w
        if wsum > 0.5:
            rets.append(acc / wsum)
    pvol = st.pstdev(rets) * math.sqrt(252) * 100 if len(rets) > 20 else None

    v20 = ann_vol(hist("SPY", date, 21, krw=False))
    v60 = ann_vol(hist("SPY", date, 61, krw=False))
    dbc = hist("DBC", date, 61, krw=False)

    ctx = {
        "as_of": date,
        "available": available,
        "above_ma": above,
        "candidates": pp.candidates(available),
        "spy_vs_ma200_pct": vs_ma("SPY", date, 200),
        "tlt_vs_ma200_pct": vs_ma("TLT", date, 200),
        "gld_vs_ma200_pct": vs_ma("GLD", date, 200),
        "port_vol_pct": pvol,
        "vol_target_pct": 10.0,
        "vol_ratio_20_60": (v20 / v60) if (v20 and v60) else None,
        "breadth_above_ma200_pct": (n_above / len(known) * 100) if known else None,
        "commodity_ret_60d_pct": ((dbc[-1] / dbc[0] - 1) * 100
                                  if len(dbc) > 40 else None),
    }
    _CTX_CACHE[ck] = ctx
    return ctx


def run(mode, lo, hi, offset, router=None, log=None):
    """조각 하나의 일별 수익률 시계열. 거래비용은 그날 수익률에 넣는다."""
    days = [d for d in CAL if lo <= d <= hi]
    held, cash = {}, 0.0
    path = []
    for k, d in enumerate(days):
        i = IDX[d]
        prev = CAL[i - 1] if i > 0 else None
        avail = [s for s in UNIVERSE
                 if prev and px(s, d) is not None and px(s, prev) is not None]
        if not avail:
            continue
        if held or cash:
            r = 0.0
            for s, w in held.items():
                a, b = px(s, prev), px(s, d)
                if a and b:
                    r += w * (b / a - 1)
            a, b = px(pp.CASH, prev), px(pp.CASH, d)
            if cash and a and b:
                r += cash * (b / a - 1)
            path.append(r)
            grown, tot = {}, cash
            for s, w in held.items():
                a, b = px(s, prev), px(s, d)
                g = w * (b / a) if (a and b) else w
                grown[s] = g
                tot += g
            if tot > 0:
                held = {s: g / tot for s, g in grown.items()}
                cash /= tot
        if (not held and not cash) or (k - offset) % PERIOD == 0:
            core_avail = [s for s in avail if s in pp.CORE]
            if not core_avail:
                continue
            if mode == "static":
                w = {s: pp.CORE[s] for s in core_avail}
                t = sum(w.values())
                alloc = pp.Allocation({s: v / t for s, v in w.items()}, 0.0)
                name = "static"
            else:
                ctx = build_ctx(d, avail)
                route = (pr.heuristic_route(ctx) if mode == "heuristic"
                         else router.route(ctx))
                alloc = pp.REGISTRY[route.program].run(ctx)
                name = route.program
                if log is not None:
                    log.append((d, name, route.source))
            turn = sum(abs(alloc.weights.get(s, 0) - held.get(s, 0))
                       for s in set(alloc.weights) | set(held))
            turn += abs(alloc.cash - cash)
            if path:
                path[-1] -= turn * COST_BP / 10000
            held, cash = dict(alloc.weights), alloc.cash
    return path


def metrics(path):
    if len(path) < 60:
        return None
    eq = peak = 1.0
    mdd = 0.0
    for x in path:
        eq *= (1 + x)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    sd = st.pstdev(path)
    yrs = len(path) / 252
    return {"total": (eq - 1) * 100,
            "cagr": (eq ** (1 / yrs) - 1) * 100 if yrs > 0.3 else None,
            "sharpe": st.mean(path) / sd * math.sqrt(252) if sd else 0.0,
            "mdd": mdd * 100, "n": len(path)}


def tranche(mode, lo, hi, router=None, log=None):
    """자금을 21등분해 동시 운용한 포트폴리오.

    조각별로 지표를 구해 평균내면 안 된다. 그건 실재하지 않는 값이다.
    매일의 포트폴리오 수익률은 21개 조각 수익률의 평균이고, 지표는
    그 평균 시계열 하나에서 나와야 한다.
    """
    paths = [p for p in (run(mode, lo, hi, o, router, log) for o in TRANCHES)
             if p and len(p) >= 60]
    if not paths:
        return None
    n = min(len(p) for p in paths)
    return metrics([st.mean([p[i] for p in paths]) for i in range(n)])
