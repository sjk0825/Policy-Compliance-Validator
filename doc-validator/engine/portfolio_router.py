"""포트폴리오 방법론 라우터.

engine/router.py 와 같은 구조다. LLM은 국면을 보고 어떤 방법론을 쓸지만
고른다. 비중표는 고른 프로그램이 결정론적으로 만든다.

LLM 호출은 국면 서명(signature)으로 캐시한다. 16년 × 21일 리밸런싱 ×
트랜치 7개면 호출이 1300번을 넘는데, 국면은 그렇게 다양하지 않다.
서명이 같으면 같은 답을 쓴다. 결과 재현도 이쪽이 낫다.
"""
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import portfolio_programs as pp

DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "minimax/minimax-m3:free")
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT_SEC = 40

SYSTEM_PROMPT = (
    "너는 자산배분 라우터다. 시장 국면을 보고 아래 방법론 중 하나만 고른다.\n"
    "너는 개별 자산이 오를지 내릴지 예측하지 않는다. 방법론 선택만 한다.\n"
    "반드시 JSON만 출력한다. 다른 말은 쓰지 않는다.\n"
    '{"program": "<이름>", "reason": "<한 문장>"}'
)


@dataclass
class Route:
    program: str
    reason: str
    source: str                 # llm | heuristic | fallback
    error: Optional[str] = None


def signature(ctx: Dict[str, Any]) -> tuple:
    """국면 서명. 같은 서명이면 같은 라우팅을 쓴다.

    연속값을 그대로 키로 쓰면 캐시가 전혀 안 맞는다. 국면 판단에
    의미 있는 경계로만 자른다.
    """
    def b(x, edges):
        if x is None:
            return None
        return sum(1 for e in edges if x > e)
    return (
        b(ctx["spy_vs_ma200_pct"], [-10, -3, 0, 5]),
        b(ctx["tlt_vs_ma200_pct"], [-10, -3, 0, 5]),
        b(ctx["port_vol_pct"], [8, 12, 16, 22]),
        b(ctx["vol_ratio_20_60"], [0.8, 1.0, 1.3, 1.8]),
        b(ctx["breadth_above_ma200_pct"], [25, 50, 75]),
        b(ctx["commodity_ret_60d_pct"], [-5, 0, 8]),
        tuple(sorted(ctx["candidates"])),
    )


def heuristic_route(ctx: Dict[str, Any]) -> Route:
    """규칙 라우터. LLM이 죽어도 판정이 멈추면 안 된다.

    순서가 곧 우선순위다. 위에서부터 걸리는 첫 규칙을 쓴다.
    """
    cand = set(ctx["candidates"])
    spy = ctx["spy_vs_ma200_pct"]
    tlt = ctx["tlt_vs_ma200_pct"]
    vr = ctx["vol_ratio_20_60"]
    rv = ctx["port_vol_pct"]

    if spy is not None and tlt is not None and spy < 0 and tlt < 0:
        # 주식과 장기채가 동시에 추세 아래. 분산이 듣지 않는 국면이다.
        if "inflation_tilt" in cand and (ctx["commodity_ret_60d_pct"] or 0) > 0:
            return Route("inflation_tilt", "주식·장기채 동반 추세 이탈 + 원자재 상승", "heuristic")
        return Route("trend_gated", "주식·장기채 동반 추세 이탈", "heuristic")
    if spy is not None and spy < -3:
        return Route("trend_gated", "주가지수가 장기추세 아래", "heuristic")
    if rv and rv > 18:
        return Route("risk_off", "포트폴리오 실현변동성 극단", "heuristic")
    if vr and vr > 1.3:
        return Route("vol_scaled", "단기 변동성이 장기 대비 급등", "heuristic")
    if ctx["breadth_above_ma200_pct"] is not None and ctx["breadth_above_ma200_pct"] < 40:
        return Route("defensive_tilt", "추세 위 자산 비중이 낮음", "heuristic")
    return Route("core_balanced", "특이 국면 아님", "heuristic")


def build_prompt(ctx: Dict[str, Any]) -> str:
    menu = "\n".join(f"- {m['name']} ({m['title']}): {m['when_to_use']}"
                     for m in pp.menu(ctx["candidates"]))
    view = {k: v for k, v in ctx.items()
            if k not in ("candidates", "available", "above_ma")}
    view["추세_위_자산"] = sorted(s for s, a in ctx["above_ma"].items() if a)
    view["추세_아래_자산"] = sorted(s for s, a in ctx["above_ma"].items() if not a)
    return (f"[방법론 목록]\n{menu}\n\n"
            f"[시장 국면]\n{json.dumps(view, ensure_ascii=False, default=str)}\n\n"
            f"위 국면에 가장 맞는 방법론 하나를 고르시오.")


class MethodologyRouter:
    def __init__(self, api_key=None, model=None, base_url=None, cache_path=None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model = model or DEFAULT_MODEL
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.cache_path = cache_path
        self.cache: Dict[str, Dict[str, str]] = {}
        if cache_path and os.path.exists(cache_path):
            self.cache = json.load(open(cache_path, encoding="utf-8"))
        self.calls = 0
        self.hits = 0
        self.errors = 0

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def save(self):
        if self.cache_path:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            json.dump(self.cache, open(self.cache_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1, sort_keys=True)

    def _post(self, prompt: str) -> str:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps({
                "model": self.model,
                "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                             {"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 200,
            }).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    @staticmethod
    def _parse(text: str, cand: List[str]) -> Optional[Dict[str, str]]:
        s, e = text.find("{"), text.rfind("}")
        if s < 0 or e <= s:
            return None
        try:
            obj = json.loads(text[s:e + 1])
        except Exception:
            return None
        name = obj.get("program")
        if name not in cand:
            return None
        return {"program": name, "reason": str(obj.get("reason", ""))[:200]}

    def route(self, ctx: Dict[str, Any]) -> Route:
        key = json.dumps(signature(ctx), default=str)
        if key in self.cache:
            self.hits += 1
            c = self.cache[key]
            return Route(c["program"], c["reason"], "llm")
        if not self.configured:
            return heuristic_route(ctx)
        for attempt in range(2):
            try:
                self.calls += 1
                got = self._parse(self._post(build_prompt(ctx)), ctx["candidates"])
                if got:
                    self.cache[key] = got
                    return Route(got["program"], got["reason"], "llm")
            except Exception as exc:                      # noqa: BLE001
                self.errors += 1
                if attempt == 0:
                    time.sleep(2)
                    continue
                h = heuristic_route(ctx)
                return Route(h.program, h.reason, "fallback", f"{type(exc).__name__}")
        h = heuristic_route(ctx)
        return Route(h.program, h.reason, "fallback", "unparsable")
