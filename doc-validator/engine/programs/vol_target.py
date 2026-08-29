"""변동성 목표제. 방향을 맞히지 않고 비중만 정한다.

측정에서 나온 비대칭이 근거다. 20일 블록 자기상관을 12개 칸에서 재보면
수익률은 -0.24에서 +0.35까지 부호가 오가는데 변동성은 12개 모두 양수이고
+0.21에서 +0.85다. 방향은 이어지지 않고 크기는 이어진다.

    비중 = 목표변동성 / 최근 실현변동성

조용하면 더 담고 시끄러우면 덜 담는다. 예측이 아니라 최근에 관측된
위험 크기에 비중을 맞추는 것이다.

효과는 낙폭에서 가장 뚜렷하다(측정: 목표 15%, 상한 2배, 20일 기준).

    삼성전자 최종     MDD -43.2% → -25.3%   샤프 1.17 → 1.47
    KODEX 200 최종   MDD -40.8% → -23.7%   샤프 1.27 → 1.59
    QQQ 검증         MDD -35.6% → -22.8%   샤프 0.64 → 0.84

샤프는 12개 중 8개에서 개선됐고 낙폭은 거의 모든 칸에서 줄었다. 대신
상승장에서는 CAGR이 낮아진다. 위험을 줄인 대가이지 공짜가 아니다.

이 프로그램은 목표 비중만 낸다. 실제로 얼마나 자주 조정할지는 실행의
문제이고, 매일 맞추면 회전율이 감당되지 않는다. 밴드는 백테스트와
운용 쪽에서 건다.
"""
from typing import Any, Dict, Optional

from .base import Program, ProgramResult, Signal


class VolTarget(Program):
    name = "vol_target"
    title = "변동성 목표"
    version = "v1"
    kind = "sizing"
    when_to_use = (
        "얼마나 담을지를 정할 때. 방향을 묻지 않는다. 최근 변동성이 목표보다 "
        "낮으면 비중을 늘리고 높으면 줄인다. 레버리지를 허용한다."
    )

    TARGET_VOL = 15.0     # 연율 %
    MAX_WEIGHT = 2.0
    MIN_WEIGHT = 0.0

    def _measured_vol(self, ctx: Dict[str, Any]) -> Optional[float]:
        return (ctx.get("volatility") or {}).get("ann_vol_20d_pct")

    def fitness(self, ctx: Dict[str, Any]) -> float:
        return 1.0 if self._measured_vol(ctx) else 0.0

    def run(self, ctx: Dict[str, Any]) -> ProgramResult:
        vol = self._measured_vol(ctx)
        vol60 = (ctx.get("volatility") or {}).get("ann_vol_60d_pct")

        if not vol:
            return ProgramResult(
                program=self.name, version=self.version, kind=self.kind,
                decision=False, weight=None, confidence=0.0,
                summary="실현변동성을 계산할 수 없어 비중을 정하지 못한다.",
                signals=[Signal("20일 실현변동성", None, "-", None)],
            )

        raw = self.TARGET_VOL / vol
        weight = round(max(self.MIN_WEIGHT, min(self.MAX_WEIGHT, raw)), 4)
        capped = raw > self.MAX_WEIGHT

        s = [
            Signal("20일 실현변동성", True, f"{vol:.1f}% (목표 {self.TARGET_VOL:.0f}%)", vol),
            Signal("60일 실현변동성", vol60 is not None,
                   f"{vol60:.1f}%" if vol60 else "-", vol60),
            Signal("상한 미도달", not capped,
                   f"산출 {raw:.2f}배, 상한 {self.MAX_WEIGHT:.1f}배", round(raw, 4)),
        ]
        return ProgramResult(
            program=self.name, version=self.version, kind=self.kind,
            decision=weight > 0, weight=weight,
            confidence=round(min(1.0, vol / self.TARGET_VOL), 3),
            summary=(f"변동성 {vol:.1f}%가 목표 {self.TARGET_VOL:.0f}%보다 "
                     f"{'낮아 비중을 늘린다' if weight > 1 else '높아 비중을 줄인다' if weight < 1 else '같아 그대로 둔다'}"
                     f" — 비중 {weight:.2f}배"),
            signals=s,
        )


class VolTargetNoLeverage(VolTarget):
    """레버리지를 쓰지 않는 변형. 조용해도 100%를 넘기지 않는다."""
    name = "vol_target_conservative"
    title = "변동성 목표(무레버리지)"
    version = "v1"
    when_to_use = (
        "얼마나 담을지를 정하되 빌리지 않을 때. 변동성이 목표보다 높으면 "
        "줄이기만 하고, 낮아도 100%를 넘기지 않는다."
    )
    TARGET_VOL = 12.0
    MAX_WEIGHT = 1.0
