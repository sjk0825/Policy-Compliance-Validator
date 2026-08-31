"""E 고정비중 · 규칙 라우팅 · LLM 라우팅 비교.

LLM 라우팅은 warm_router_cache.py 로 미리 채운 캐시만 읽는다. 캐시에
없는 국면이 나오면 규칙 라우터로 떨어진다(fallback).
"""
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import methodology_backtest as m                                  # noqa: E402
from engine import portfolio_router as pr                         # noqa: E402

CACHE = ROOT / "fixtures" / "router_inputs" / "methodology_cache.json"
router = pr.MethodologyRouter(api_key=None, cache_path=str(CACHE))
MODES = [("static", "E 고정비중"), ("heuristic", "규칙 라우팅"), ("llm", "LLM 라우팅")]
LO, HI = "2010-01-01", "2026-12-31"


def go(mode, lo, hi, log=None):
    return m.tranche(mode, lo, hi, router=router, log=log)


print(f"LLM 라우팅 캐시 {len(router.cache)}개 국면\n")
print("원화 · 21일 리밸런싱 · 트랜치 7개 · 왕복 10bp · 선행편향 차단\n")
print(f"  {'':<14}{'CAGR':>9}{'샤프':>8}{'MDD':>9}   방법론 선택 분포")
print("  " + "-" * 90)
for mode, lab in MODES:
    log = []
    r = go(mode, LO, HI, log)
    dist = ""
    if log:
        c = Counter(p for _, p, _ in log)
        t = sum(c.values())
        dist = "  ".join(f"{k}:{v/t*100:.0f}%" for k, v in c.most_common(4))
    print(f"  {lab:<14}{r['cagr']:>+8.2f}%{r['sharpe']:>8.2f}{r['mdd']:>+8.1f}%   {dist}")

SPLITS = [("탐색 10~18", "2010-01-01", "2018-12-31"),
          ("검증 19~22", "2019-01-01", "2022-12-31"),
          ("최종 23~26", "2023-01-01", "2026-12-31")]
print("\n3분할\n")
print(f"  {'':<14}" + "".join(f"{n:>24}" for n, _, _ in SPLITS))
print(f"  {'':<14}" + "".join(f"{'CAGR    샤프     MDD':>24}" for _ in SPLITS))
print("  " + "-" * 88)
for mode, lab in MODES:
    cells = []
    for _, lo, hi in SPLITS:
        r = go(mode, lo, hi)
        cells.append(f"{r['cagr']:>+8.1f}%{r['sharpe']:>8.2f}{r['mdd']:>+8.1f}%"
                     if r else f"{'-':>24}")
    print(f"  {lab:<14}" + "".join(cells))

print("\n연도별 (원화 %)\n")
print(f"  {'연도':<7}{'E 고정':>10}{'규칙':>10}{'LLM':>10}   LLM 주된 선택")
print("  " + "-" * 74)
for y in range(2010, 2027):
    lo, hi = f"{y}-01-01", f"{y}-12-31"
    row, log = [], []
    for mode, _ in MODES:
        r = go(mode, lo, hi, log if mode == "llm" else None)
        row.append(r["total"] if r else None)
    if any(v is None for v in row):
        continue
    c = Counter(p for _, p, _ in log)
    t = max(1, sum(c.values()))
    top = "  ".join(f"{k} {v*100//t}%" for k, v in c.most_common(2))
    print(f"  {y:<7}{row[0]:>+9.2f}%{row[1]:>+9.2f}%{row[2]:>+9.2f}%   {top}")

print("\n최악의 해\n")
for mode, lab in MODES:
    ys = []
    for y in range(2010, 2027):
        r = go(mode, f"{y}-01-01", f"{y}-12-31")
        if r:
            ys.append((r["total"], y))
    neg = [v for v, _ in ys if v < 0]
    w = min(ys)
    print(f"  {lab:<14} 최악 {w[0]:+.2f}% ({w[1]})   마이너스 해 {len(neg)}개 / {len(ys)}")
