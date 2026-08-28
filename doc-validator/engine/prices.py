"""fixture(전체 또는 슬라이스)에서 시세를 읽는다.

이 계층의 유일한 책임은 기준일 이후 데이터를 절대 내보내지 않는 것이다.
판단 로직이 미래를 보면 백테스트 결과 전체가 무의미해지므로, 차단은
호출자 재량이 아니라 여기서 강제한다.
"""
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "fixtures"


@dataclass(frozen=True)
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class SymbolMeta:
    symbol: str
    name: Optional[str]
    group: str
    kind: Optional[str]
    market: str


def _market_of(group: str, kind: Optional[str]) -> str:
    if kind == "암호화폐":
        return "crypto"
    return "kr" if group.startswith("kr_") else "us"


class PriceStore:
    """슬라이스 또는 전체 fixture 하나를 읽어 들인다."""

    def __init__(self, source: Optional[Path] = None) -> None:
        self.source = Path(source) if source else self._default_source()
        self.manifest_path = self._find_manifest(self.source)
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))

        self.slice_id: Optional[str] = manifest.get("slice_id")
        self.window = (manifest.get("start"), manifest.get("end"))

        self._meta: Dict[str, SymbolMeta] = {}
        self._files: Dict[str, Path] = {}
        for e in manifest["symbols"]:
            sym = e["symbol"]
            self._meta[sym] = SymbolMeta(
                symbol=sym,
                name=e.get("name"),
                group=e["group"],
                kind=e.get("kind"),
                market=_market_of(e["group"], e.get("kind")),
            )
            # manifest의 경로는 보통 레포 기준 상대경로지만,
            # 임시 위치의 fixture를 물릴 수 있게 절대경로도 받는다.
            f = Path(e["file"])
            self._files[sym] = f if f.is_absolute() else ROOT / f

        self._cache: Dict[str, List[Bar]] = {}

    @staticmethod
    def _default_source() -> Path:
        """기본은 전체 fixture다.

        슬라이스에서 읽으면 창 시작 이전을 못 봐서, 창 초반 판정일마다
        장기 지표가 비어버린다. 슬라이스의 역할은 "어떤 날짜에 판정할지"를
        정하는 것이지 "과거를 얼마나 볼지"가 아니다. 과거는 전부 열어두고
        미래만 as_of로 자른다.
        """
        return FIXTURES

    @staticmethod
    def _find_manifest(source: Path) -> Path:
        for name in ("slice.json", "manifest.json"):
            candidate = source / name
            if candidate.exists():
                return candidate
        raise FileNotFoundError(f"{source}에 slice.json도 manifest.json도 없습니다.")

    # ---- 조회 ---------------------------------------------------------

    @property
    def symbols(self) -> List[str]:
        return list(self._meta)

    def meta(self, symbol: str) -> SymbolMeta:
        if symbol not in self._meta:
            raise KeyError(f"'{symbol}'은 이 fixture에 없습니다.")
        return self._meta[symbol]

    def _all_bars(self, symbol: str) -> List[Bar]:
        if symbol not in self._cache:
            path = self._files[self.meta(symbol).symbol]
            with path.open(encoding="utf-8", newline="") as f:
                self._cache[symbol] = [
                    Bar(
                        date=r["Date"],
                        open=float(r["Open"] or 0),
                        high=float(r["High"] or 0),
                        low=float(r["Low"] or 0),
                        close=float(r["Close"]),
                        volume=float(r["Volume"] or 0),
                    )
                    for r in csv.DictReader(f)
                ]
        return self._cache[symbol]

    def bars(self, symbol: str, as_of: str, lookback: Optional[int] = None) -> List[Bar]:
        """기준일까지의 봉만 돌려준다. lookback을 주면 최근 N개로 자른다."""
        bars = [b for b in self._all_bars(symbol) if b.date <= as_of]
        if bars and bars[-1].date > as_of:  # 방어적 확인
            raise AssertionError(f"미래 데이터 유출: {symbol} {bars[-1].date} > {as_of}")
        return bars[-lookback:] if lookback else bars

    def closes(self, symbol: str, as_of: str, lookback: Optional[int] = None) -> List[float]:
        return [b.close for b in self.bars(symbol, as_of, lookback)]

    def has(self, symbol: str) -> bool:
        return symbol in self._meta
