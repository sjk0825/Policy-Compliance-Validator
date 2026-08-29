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

# 라우팅 선호. 적합도에 곱하는 가중치다.
# 어느 프로그램을 더 자주 태울지는 "무엇이 맞는가"가 아니라 "무엇을
# 원하는가"의 문제라, 코드에 하나로 박지 않고 프로파일로 갈라둔다.
ROUTING_PROFILES = {
    # 적합도 그대로. 가중치 없음.
    "balanced": {},
    # 고승률·저왜도 계열을 우대한다. 자주 이기는 대신 기대수익이 낮다.
    "steady": {"low_vol_steady": 1.6, "short_reversal": 1.4},
    # 같은 방향으로 더 밀어붙이고 모멘텀 계열을 눌러둔다.
    "steady_strong": {"low_vol_steady": 2.4, "short_reversal": 2.0,
                      "cross_momentum": 0.6, "trend_following": 0.8},
    # 비중만 답한다. 방향 프로그램을 모두 눌러 sizing만 남긴다.
    # 방향 예측에는 우위가 확인되지 않았고 비중 조절에는 낙폭 감소가
    # 12개 칸 전부에서 확인됐다. 답하는 질문 자체가 다르다.
    "sizing": {"vol_target": 3.0, "vol_target_conservative": 3.0,
               "trend_following": 0.0, "mean_reversion": 0.0,
               "cross_momentum": 0.0, "short_reversal": 0.0,
               "low_vol_steady": 0.0, "laggard": 0.0,
               "overnight_reversal": 0.0, "defensive": 0.0},
    # 오버나이트 되돌림을 우대한다. 보유 가정이 다르므로(시가매수→종가매도)
    # 이 프로파일로 낸 판정은 다른 프로파일과 같은 잣대로 채점하면 안 된다.
    "overnight": {"overnight_reversal": 2.0},
    # 승률을 최우선으로 둔다. 십분위 측정에서 모멘텀 하위권이 중앙값을
    # 넘길 확률이 높았으므로 소외주 계열을 앞세운다.
    "win_rate": {"laggard": 2.6, "low_vol_steady": 2.0, "short_reversal": 1.6,
                 "cross_momentum": 0.4, "trend_following": 0.5},
    # 반대쪽. 드물게 크게 이기는 계열을 우대한다.
    "aggressive": {"cross_momentum": 1.5, "trend_following": 1.3,
                   "low_vol_steady": 0.6},
}
# 기본 프로파일. 방향 프로그램들은 탐색/검증/최종 3분할에서 승률이
# 48~50.6% 사이를 오갔고 프로파일 간 순위도 유지되지 않았다. 우위가
# 확인되지 않은 답을 기본으로 낼 이유가 없다.
#
# 비중 프로그램은 다르다. 낙폭 감소가 4종목 × 3구간 12개 칸 전부에서
# 나타났고(무레버리지 기준 평균 -12.1%p), 밴드와 거래비용을 넣은 뒤에도
# 유지된다. 다만 샤프는 개선이 아니고(7/12) CAGR은 낮아진다. 위험을
# 줄이는 도구이지 수익을 늘리는 도구가 아니다.
#
# 환경변수 ROUTING_PROFILE로 바꿀 수 있다.
DEFAULT_PROFILE = os.getenv("ROUTING_PROFILE", "sizing")
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
    # 규칙 라우터가 매긴 프로그램별 적합도와 1·2위 격차.
    # 왜 그 프로그램이 골라졌는지 나중에 되짚기 위해 남긴다.
    scores: Optional[Dict[str, float]] = None
    margin: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "program": self.program,
            "reason": self.reason,
            "source": self.source,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "candidates": self.candidates,
            "scores": self.scores,
            "margin": self.margin,
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


def allowed_programs(profile: str) -> List[str]:
    """프로파일이 죽이지 않은 프로그램만 남긴다."""
    weights = ROUTING_PROFILES.get(profile, {})
    return [n for n in programs.REGISTRY if weights.get(n, 1.0) > 0]


def build_prompt(ctx_digest: Dict[str, Any], profile: str = DEFAULT_PROFILE) -> str:
    menu = "\n".join(
        f"- {m['name']} ({m['title']}): {m['when_to_use']}"
        for m in programs.menu(allowed_programs(profile))
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

    def route(self, ctx: Dict[str, Any], profile: str = DEFAULT_PROFILE) -> RouteDecision:
        return self.route_digest(digest(ctx), profile)

    def route_digest(self, ctx_digest: Dict[str, Any],
                     profile: str = DEFAULT_PROFILE) -> RouteDecision:
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
                {"role": "user", "content": build_prompt(ctx_digest, profile)},
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
        allowed = allowed_programs(profile)
        if name not in allowed:
            raise RouterUnavailable(
                f"모델이 고른 프로그램이 이 프로파일에 없습니다: {name!r}")

        return RouteDecision(
            program=name,
            reason=str((parsed or {}).get("reason", ""))[:300],
            source="llm",
            model=data.get("model", self.model),
            latency_ms=latency,
            candidates=allowed,
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


def heuristic_route(ctx: Dict[str, Any], error: Optional[str] = None,
                    profile: str = DEFAULT_PROFILE) -> RouteDecision:
    """규칙 기반 라우터. 적합도가 가장 높은 프로그램을 고른다.

    우선순위 체인(if/elif)을 쓰지 않는다. 체인은 먼저 걸리는 조건이 이기므로
    순서가 곧 결과가 된다. 실제로 낙폭이 깊은 구간은 defensive 조건에 먼저
    걸려서 mean_reversion이 도달 불가였다. 각 프로그램이 스스로 적합도를
    내고 최댓값을 고르면 그런 순서 효과가 없다.

    defensive는 고정 바닥값을 낸다. 전문 프로그램이 그 값을 넘지 못하면,
    즉 어느 쪽도 자기 국면이라고 말하지 못하면 방어가 이긴다.
    """
    weights = ROUTING_PROFILES.get(profile, {})
    scores = {name: round(p.fitness(ctx) * weights.get(name, 1.0), 4)
              for name, p in programs.REGISTRY.items()}
    # 동점 처리를 명시한다. 등록 순서에 맡기면 순서가 결과를 정한다.
    # 적합도 → 선언된 우선순위 → 이름 순으로 결정론적으로 고른다.
    best = max(scores, key=lambda n: (scores[n],
                                      programs.REGISTRY[n].priority,
                                      n == programs.DEFAULT_PROGRAM,
                                      n))

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    gap = round(ranked[0][1] - ranked[1][1], 4) if len(ranked) > 1 else None
    reason = f"[{profile}] 적합도 " + ", ".join(f"{n} {v:.2f}" for n, v in ranked[:3])

    return RouteDecision(
        program=best, reason=reason,
        source="fallback" if error else "heuristic",
        error=error, candidates=list(programs.REGISTRY),
        scores=scores, margin=gap,
    )


def chain_route(ctx: Dict[str, Any], error: Optional[str] = None) -> RouteDecision:
    """구버전 우선순위 체인. 적합도 라우터와 비교하기 위해 남겨둔다.

    먼저 걸리는 조건이 이기므로 순서가 결과를 바꾼다. 낙폭이 깊으면
    defensive가 먼저 잡아 mean_reversion이 도달하지 못한다.
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

    return RouteDecision(program=name, reason=why,
                         source="fallback" if error else "chain",
                         error=error, candidates=list(programs.REGISTRY))


def route(ctx: Dict[str, Any], router: Optional[LLMRouter] = None,
          use_llm: bool = True, profile: str = DEFAULT_PROFILE) -> RouteDecision:
    """LLM으로 라우팅하고, 안 되면 규칙 기반으로 떨어진다.

    프로파일은 양쪽에 똑같이 적용된다. LLM에게 프로파일이 죽인 프로그램을
    보여주면 프로파일이 무력해진다.
    """
    if not use_llm:
        return heuristic_route(ctx, profile=profile)
    router = router or LLMRouter()
    try:
        return router.route(ctx, profile=profile)
    except RouterUnavailable as e:
        return heuristic_route(ctx, error=str(e), profile=profile)
