"""프로그램 라우터.

LLM이 하는 일은 하나다. 컨텍스트를 보고 어떤 프로그램을 태울지 고르는 것.
판단 자체는 하지 않는다. 고른 프로그램이 결정론적으로 답을 낸다.

LLM은 언제든 못 쓸 수 있다(크레딧 소진, 장애, 응답 파싱 실패). 그때는
규칙 기반 라우터로 떨어진다. 라우팅이 막혀 판정 자체가 멈추면 안 된다.
"""
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import programs

DEFAULT_MODEL = "minimax/minimax-m3:free"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT_SEC = 40


@dataclass
class RouteDecision:
    program: str
    reason: str
    source: str                      # llm | heuristic | fallback
    model: Optional[str] = None
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    candidates: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "program": self.program,
            "reason": self.reason,
            "source": self.source,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "candidates": self.candidates,
        }


def digest(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """LLM에 넘길 축약 컨텍스트.

    원본을 통째로 넘기면 토큰만 먹고 라우팅 품질도 떨어진다. 국면 판단에
    필요한 것만 남긴다.
    """
    t, v, r = ctx["trend"], ctx["volatility"], ctx["returns"]
    dd = ctx.get("drawdown") or {}
    return {
        "symbol": ctx["symbol"],
        "name": ctx["meta"].get("name"),
        "kind": ctx["meta"].get("kind"),
        "as_of": ctx["as_of"],
        "returns_pct": {k: r.get(k) for k in ("5d", "20d", "60d", "120d")},
        "px_vs_sma20_pct": t["px_vs_sma20_pct"],
        "px_vs_sma60_pct": t["px_vs_sma60_pct"],
        "sma20_vs_sma60_pct": t["sma20_vs_sma60_pct"],
        "ann_vol_20d_pct": v["ann_vol_20d_pct"],
        "vol_ratio_20_60": v["vol_ratio_20_60"],
        "drawdown_pct": dd.get("pct"),
        "regime": {
            sym: {"ret_20d_pct": e["ret_20d_pct"],
                  "px_vs_sma60_pct": e["px_vs_sma60_pct"]}
            for sym, e in ctx.get("regime", {}).items()
        },
    }


SYSTEM_PROMPT = (
    "너는 금융 데이터 라우터다. 종목의 시장 상태를 보고, 아래 프로그램 중 "
    "어느 것으로 판단하게 할지 딱 하나만 고른다.\n"
    "너는 매수/매도를 판단하지 않는다. 프로그램 선택만 한다.\n"
    "반드시 아래 형식의 JSON만 출력한다. 다른 말은 쓰지 않는다.\n"
    '{"program": "<이름>", "reason": "<한 문장>"}'
)


def build_prompt(ctx_digest: Dict[str, Any]) -> str:
    menu = "\n".join(
        f"- {m['name']} ({m['title']}): {m['when_to_use']}" for m in programs.menu()
    )
    return (
        f"[프로그램 목록]\n{menu}\n\n"
        f"[시장 상태]\n{json.dumps(ctx_digest, ensure_ascii=False)}\n\n"
        f"위 상태에 가장 맞는 프로그램 하나를 고르시오."
    )


class RouterUnavailable(Exception):
    pass


class LLMRouter:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None,
                 base_url: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model = model or os.getenv("OPENROUTER_MODEL") or DEFAULT_MODEL
        self.base_url = (base_url or os.getenv("OPENROUTER_BASE_URL")
                         or DEFAULT_BASE_URL).rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            raise RouterUnavailable(f"HTTP {e.code}: {body}") from e
        except Exception as e:
            raise RouterUnavailable(f"{type(e).__name__}: {e}") from e

    def route(self, ctx: Dict[str, Any]) -> RouteDecision:
        return self.route_digest(digest(ctx))

    def route_digest(self, ctx_digest: Dict[str, Any]) -> RouteDecision:
        """축약 컨텍스트만으로 라우팅한다.

        저장해 둔 입력 fixture를 그대로 태울 수 있어야 프롬프트나 모델을
        바꿨을 때 같은 입력으로 비교가 된다.
        """
        if not self.configured:
            raise RouterUnavailable("OPENROUTER_API_KEY가 설정되지 않았습니다.")

        started = time.perf_counter()
        data = self._post({
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(ctx_digest)},
            ],
            "max_tokens": 200,
            "temperature": 0,
        })
        latency = round((time.perf_counter() - started) * 1000, 1)

        if "error" in data:
            raise RouterUnavailable(str(data["error"])[:300])

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RouterUnavailable(f"응답 형식이 예상과 다릅니다: {e}") from e

        parsed = _parse_json(text)
        name = (parsed or {}).get("program")
        if name not in programs.REGISTRY:
            raise RouterUnavailable(f"모델이 고른 프로그램이 올바르지 않습니다: {name!r}")

        return RouteDecision(
            program=name,
            reason=str((parsed or {}).get("reason", ""))[:300],
            source="llm",
            model=data.get("model", self.model),
            latency_ms=latency,
            candidates=list(programs.REGISTRY),
        )


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    """모델이 코드펜스나 잡설을 붙여도 JSON만 건져낸다."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def heuristic_route(ctx: Dict[str, Any], error: Optional[str] = None) -> RouteDecision:
    """LLM 없이도 돌아가는 규칙 기반 라우터.

    LLM 라우터와 같은 관점(변동성 확대 → 역추세, 추세 정상 → 추세추종)을
    쓰되 임계값을 고정한다. 결과를 비교하면 LLM이 실제로 뭘 더 하는지 보인다.
    """
    v, t = ctx["volatility"], ctx["trend"]
    dd = (ctx.get("drawdown") or {}).get("pct")
    vr = v.get("vol_ratio_20_60")

    if (vr is not None and vr >= 1.35) or (dd is not None and dd <= -18):
        name, why = "defensive", "변동성 급증 또는 깊은 낙폭"
    elif (dd is not None and dd <= -8) and (t.get("px_vs_sma20_pct") or 0) < 0:
        name, why = "mean_reversion", "고점 대비 하락 + 단기선 아래"
    elif (t.get("px_vs_sma60_pct") or 0) > 0 and (t.get("sma20_vs_sma60_pct") or 0) > 0:
        name, why = "trend_following", "가격이 이동평균 위, 단기선 우위"
    else:
        name, why = programs.DEFAULT_PROGRAM, "뚜렷한 국면 신호 없음"

    return RouteDecision(
        program=name, reason=why,
        source="fallback" if error else "heuristic",
        error=error, candidates=list(programs.REGISTRY),
    )


def route(ctx: Dict[str, Any], router: Optional[LLMRouter] = None,
          use_llm: bool = True) -> RouteDecision:
    """LLM으로 라우팅하고, 안 되면 규칙 기반으로 떨어진다."""
    if not use_llm:
        return heuristic_route(ctx)
    router = router or LLMRouter()
    try:
        return router.route(ctx)
    except RouterUnavailable as e:
        return heuristic_route(ctx, error=str(e))
