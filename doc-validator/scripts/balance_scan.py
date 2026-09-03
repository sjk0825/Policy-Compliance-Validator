"""추세와 역추세의 균형을 축별로 훑는다.

이 전략에는 방향이 다른 축이 섞여 있다.

    보유/현금   200일선 위      추세
    낙폭 조건   BTC만 -20%      추세 (무너진 것은 뺀다)
    비중 기울기  k<0            추세 (오른 것을 더 산다)
    되맞춤     목표로 되돌림     역추세
    현금 통화   달러가 싸면 달러  역추세

축마다 방향이 다른 것이 우연인지 구조인지 보려면 함께 흔들어야 한다.
특히 기울기 기준기간은 초기에 5일로 정해진 뒤 다른 층이 다 바뀌는 동안
재검토된 적이 없다.

두 창에서 동시에 재고, 양쪽 모두 개선되는 것만 후보로 본다. 한쪽에서만
좋은 것은 그 시대에 맞춘 것이다(2008 검증에서 이미 한 번 데었다).

    python scripts/balance_scan.py
"""
import argparse
import csv
import math
import statistics as st
import sys
from collections import deque
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import krw_basis as K                              # noqa: E402
from engine import PriceStore                      # noqa: E402
from btal_hibl import closes, summarize            # noqa: E402
from worst_year_push import daily                  # noqa: E402

COST = 10.0
C13 = ["SPY", "QQQ", "069500", "TLT", "IEF", "GLD", "SLV",
       "DBC", "XLE", "XLU", "EFA", "EEM", "BTC/USD"]
C9 = ["SPY", "QQQ", "TLT", "IEF", "GLD", "EFA", "EEM", "XLU", "XLE"]


class Board:
    """한 판(자산 집합 + 기간)을 준비해 두고 설정만 바꿔 돌린다."""

    def __init__(self, px, cal, fx, core, lo, hi, y0, dd_assets, gap=-0.05):
        self.core, self.y0 = core, y0
        c2 = [d for d in cal if d in fx]
        krw, usd, e, f = {}, {}, 100.0, 100.0
        for d in c2:
            e *= 1 + 0.02 / 252
            krw[d] = e
            f *= 1 + 0.02 / 252
            usd[d] = f * fx[d] / fx[c2[0]]
        g, r = {}, 0.0
        for i, d in enumerate(c2):
            r += fx[d]
            if i >= 200:
                r -= fx[c2[i - 200]]
            if i >= 199 and i + 1 < len(c2):
                g[c2[i + 1]] = fx[d] / (r / 200) - 1
        cash, e, prev = {}, 100.0, None
        for d in c2:
            if prev is None:
                cash[d] = e
                prev = d
                continue
            use = g.get(d, 0.0) <= gap
            e *= (usd[d] / usd[prev]) if use else (krw[d] / krw[prev])
            cash[d] = e
            prev = d
        pk = dict(px)
        pk["CASH"] = cash
        self.px, self.cal = pk, cal
        self.rets = daily(pk, cal)
        self.days = [d for d in cal if lo <= d <= hi and d in fx]
        self.w0 = {s: 1 / len(core) for s in core}
        self.ma60 = {s: self._ma(s, 60) for s in core}
        b200 = {s: self._ma(s, 200) for s in core}
        self.filt = {}
        for s in core:
            if s in dd_assets:
                a = self._dd(s, 504, 0.20)
                self.filt[s] = {d: min(a[d], b200[s].get(d, 1.0)) for d in a}
            else:
                self.filt[s] = b200[s]
        self.trail = {}

    def _ma(self, s, n):
        ds = [d for d in self.cal if d in self.px[s]]
        out, r = {}, 0.0
        for i, d in enumerate(ds):
            r += self.px[s][d]
            if i >= n:
                r -= self.px[s][ds[i - n]]
            if i >= n - 1 and i + 1 < len(ds):
                out[ds[i + 1]] = 1.0 if self.px[s][d] > r / n else 0.0
        return out

    def _dd(self, s, win, thr):
        ds = [d for d in self.cal if d in self.px[s]]
        out, dq = {}, deque()
        for i, d in enumerate(ds):
            while dq and self.px[s][ds[dq[-1]]] <= self.px[s][d]:
                dq.pop()
            dq.append(i)
            while dq[0] < i - win:
                dq.popleft()
            if i >= win and i + 1 < len(ds):
                out[ds[i + 1]] = (1.0 if self.px[s][d] / self.px[s][ds[dq[0]]] - 1
                                  > -thr else 0.0)
        return out

    def tr(self, L):
        if L not in self.trail:
            m = {}
            for s in self.core:
                ds = [d for d in self.cal if d in self.px[s]]
                m[s] = {ds[i + 1]: self.px[s][ds[i]] / self.px[s][ds[i - L]] - 1
                        for i in range(L, len(ds) - 1)}
            self.trail[L] = m
        return self.trail[L]

    def run(self, k, L, per, sig=21, noff=7) -> Dict:
        TR = self.tr(L)
        days, rets, w0 = self.days, self.rets, self.w0

        def path(off):
            sleeve, inner, out = {}, {}, []
            for i, d in enumerate(days):
                avail = [s for s in self.core if d in rets.get(s, {})]
                if not avail or d not in rets["CASH"]:
                    continue
                aset = set(avail)
                if sleeve:
                    x, grow = 0.0, {}
                    for s, w in sleeve.items():
                        if s in aset:
                            a = inner.get(s, 1.0)
                            rr = a * rets[s][d] + (1 - a) * rets["CASH"][d]
                            x += w * rr
                            grow[s] = w * (1 + rr)
                            if 1 + rr != 0:
                                inner[s] = a * (1 + rets[s][d]) / (1 + rr)
                        else:
                            grow[s] = w
                    out.append(x)
                    t = sum(grow.values())
                    if t > 0:
                        sleeve = {s: v / t for s, v in grow.items()}
                traded = 0.0
                if not sleeve or i % sig == 0:
                    for s in avail:
                        tg = self.filt[s].get(d, 1.0)
                        traded += 2 * sleeve.get(s, 0) * abs(tg - inner.get(s, tg))
                        inner[s] = tg
                if not sleeve or (aset - set(sleeve)) or (i - off) % per == 0:
                    vals = {s: TR[s][d] for s in avail if d in TR[s]}
                    if len(vals) >= 3 and k:
                        mu, sd = st.mean(vals.values()), st.pstdev(vals.values())
                        w = {}
                        for s in avail:
                            kk = k if self.ma60[s].get(d, True) else 0.0
                            z = (vals[s] - mu) / sd if (sd and s in vals) else 0.0
                            w[s] = w0[s] * math.exp(max(-3, min(3, -kk * z)))
                    else:
                        w = {s: w0[s] for s in avail}
                    t2 = sum(w.values())
                    tg = {s: v / t2 for s, v in w.items()}
                    traded += sum(abs(tg.get(s, 0) - sleeve.get(s, 0))
                                  for s in set(tg) | set(sleeve))
                    sleeve = tg
                    for s in avail:
                        inner.setdefault(s, self.filt[s].get(d, 1.0))
                if traded and out:
                    out[-1] -= traded * COST / 10000
            return out

        ps = [path(round(i * per / noff)) for i in range(min(per, noff))]
        n = min(len(p) for p in ps)
        s2 = dict(zip(days[len(days) - n:],
                      [st.mean([p[i] for p in ps]) for i in range(n)]))
        m = summarize([s2[d] for d in sorted(s2)])
        ys: Dict[int, List[float]] = {}
        for d in sorted(s2):
            ys.setdefault(int(d[:4]), []).append(s2[d])
        y = {a: (math.prod(1 + x for x in b) - 1) * 100
             for a, b in ys.items() if len(b) > 150 and a >= self.y0}
        m["y"], m["worst"] = y, min(y.values())
        m["neg"], m["ny"] = sum(1 for v in y.values() if v < 0), len(y)
        return m


def load_long(name):
    p = ROOT / "fixtures" / "longrun" / f"{name}.csv"
    return {r["Date"]: float(r["Close"])
            for r in csv.DictReader(p.open(encoding="utf-8")) if r["Close"]}


def boards():
    store = PriceStore(Path("fixtures/wide"))
    cal = sorted(closes(store, "SPY"))
    fx = K.load_fx(cal)
    a = Board(K.to_krw({s: closes(store, s) for s in C13}, fx), cal, fx,
              C13, "2012-05-07", "2026-12-31", 2013, {"BTC/USD"})
    fxr = load_long("USDKRW_long")
    pu = {s: load_long(s) for s in C9}
    c2 = sorted(set().union(*[set(v) for v in pu.values()]))
    last, fx2 = None, {}
    for d in c2:
        if d in fxr:
            last = fxr[d]
        if last:
            fx2[d] = last
    c2 = [d for d in c2 if d in fx2]
    pk = {s: {d: v * fx2[d] for d, v in ser.items() if d in fx2}
          for s, ser in pu.items()}
    b = Board(pk, c2, fx2, C9, "2007-01-03", "2026-12-31", 2008, set())
    return a, b


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--noff", type=int, default=7)
    args = ap.parse_args()
    A, B = boards()
    print("기울기 방향·기간 × 되맞춤 주기 — 두 창 동시\n")
    print(f"  {'k':>6}{'기준일':>7}{'되맞춤':>7} │"
          f"{'A샤프':>7}{'A CAGR':>9}{'A최악':>8} │"
          f"{'B샤프':>7}{'B CAGR':>9}{'B최악':>8}")
    print("  " + "-" * 74)
    rows = []
    for L in (5, 21, 63):
        for k in (-1.0, -0.5, -0.25, 0.0, 0.25):
            for per in (21, 63):
                a = A.run(k, L, per, noff=args.noff)
                b = B.run(k, L, per, noff=args.noff)
                rows.append((a["sharpe"] + b["sharpe"], k, L, per, a, b))
                tag = "  ← 지금" if (k, L, per) == (-0.5, 5, 21) else ""
                print(f"  {k:>+6.2f}{L:>7}{per:>7} │{a['sharpe']:>7.2f}"
                      f"{a['cagr']:>+8.2f}%{a['worst']:>+7.1f}% │{b['sharpe']:>7.2f}"
                      f"{b['cagr']:>+8.2f}%{b['worst']:>+7.1f}%{tag}")
        print()
    base = [r for r in rows if (r[1], r[2], r[3]) == (-0.5, 5, 21)][0]
    print(f"  기준(지금) 합산샤프 {base[0]:.2f}\n")
    print("  두 창 모두 지금보다 나은 것\n")
    good = [r for r in rows if r[4]["sharpe"] > base[4]["sharpe"]
            and r[5]["sharpe"] > base[5]["sharpe"]]
    if not good:
        print("    없음")
    for r in sorted(good, reverse=True):
        print(f"    k={r[1]:+.2f} 기준{r[2]}일 되맞춤{r[3]}일 │"
              f" A {r[4]['sharpe']:.2f}/{r[4]['cagr']:+.2f}%/{r[4]['worst']:+.1f}%"
              f" │ B {r[5]['sharpe']:.2f}/{r[5]['cagr']:+.2f}%/{r[5]['worst']:+.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
