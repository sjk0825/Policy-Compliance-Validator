import json
from html import escape
from typing import Any, Dict, List, Optional

from .buildinfo import BuildInfo

_CSS = """
:root {
  color-scheme: light dark;
  --bg: #ffffff; --fg: #1b1b1f; --muted: #6b6b76;
  --line: #e3e3e8; --card: #f7f7f9; --code: #f0f0f3;
  --true: #147d3f; --true-bg: #e6f5ec;
  --false: #b3261e; --false-bg: #fbeae9;
  --accent: #3b5bdb;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #131316; --fg: #e8e8ec; --muted: #9a9aa5;
    --line: #2c2c33; --card: #1b1b20; --code: #202027;
    --true: #6ee7a4; --true-bg: #123024;
    --false: #ff9c94; --false-bg: #3a1a18;
    --accent: #8ba4ff;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2rem 1.25rem 4rem;
  background: var(--bg); color: var(--fg);
  font: 15px/1.6 ui-sans-serif, -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
}
.wrap { max-width: 880px; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
h2 { font-size: 1rem; margin: 2rem 0 .75rem; text-transform: uppercase;
     letter-spacing: .06em; color: var(--muted); }
.sub { color: var(--muted); font-size: .875rem; margin: 0 0 1.5rem; }
code, pre, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.verdict {
  display: inline-block; padding: .35rem .9rem; border-radius: 999px;
  font-weight: 700; font-size: 1rem; letter-spacing: .04em;
}
.verdict.t { background: var(--true-bg); color: var(--true); }
.verdict.f { background: var(--false-bg); color: var(--false); }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: .75rem; }
.cell { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: .75rem .9rem; }
.cell .k { font-size: .72rem; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
.cell .v { margin-top: .2rem; font-size: .95rem; word-break: break-all; }
ol.steps { list-style: none; margin: 0; padding: 0; }
ol.steps > li {
  position: relative; padding: 0 0 1.25rem 1.75rem;
  border-left: 2px solid var(--line);
}
ol.steps > li:last-child { border-left-color: transparent; padding-bottom: 0; }
ol.steps > li::before {
  content: attr(data-seq); position: absolute; left: -11px; top: 0;
  width: 20px; height: 20px; border-radius: 50%;
  background: var(--accent); color: #fff;
  font-size: .7rem; line-height: 20px; text-align: center; font-weight: 700;
}
.step-h { display: flex; align-items: baseline; gap: .5rem; flex-wrap: wrap; }
.step-h .name { font-size: .78rem; color: var(--muted); }
.step-h .ms { font-size: .72rem; color: var(--muted); margin-left: auto; }
.step-d { color: var(--muted); font-size: .875rem; margin: .15rem 0 .5rem; }
.io { display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; }
@media (max-width: 640px) { .io { grid-template-columns: 1fr; } }
.io .k { font-size: .7rem; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin-bottom: .2rem; }
pre {
  background: var(--code); border: 1px solid var(--line); border-radius: 8px;
  padding: .7rem .8rem; margin: 0; overflow-x: auto; font-size: .8rem;
}
.warn { color: var(--false); font-weight: 600; }
table { width: 100%; border-collapse: collapse; font-size: .875rem; }
th, td { text-align: right; padding: .5rem .6rem; border-bottom: 1px solid var(--line); }
th:first-child, td:first-child { text-align: left; }
th { font-size: .72rem; text-transform: uppercase; letter-spacing: .06em;
     color: var(--muted); font-weight: 600; }
td.hit { color: var(--true); font-weight: 600; }
td.miss { color: var(--false); font-weight: 600; }
td.na { color: var(--muted); }
tr.primary td { background: var(--card); }
.tw { overflow-x: auto; }
footer { margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid var(--line);
         color: var(--muted); font-size: .8rem; }
footer a { color: var(--accent); }
"""


def _pre(value: Any) -> str:
    return f"<pre>{escape(json.dumps(value, ensure_ascii=False, indent=2))}</pre>"


def _cell(key: str, value: str, mono: bool = False) -> str:
    cls = ' class="v mono"' if mono else ' class="v"'
    return f'<div class="cell"><div class="k">{escape(key)}</div><div{cls}>{escape(value)}</div></div>'


def _steps_html(steps: List[Dict[str, Any]]) -> str:
    items = []
    for s in steps:
        status = "" if s["status"] == "ok" else f' <span class="warn">{escape(s["status"])}</span>'
        items.append(
            f'<li data-seq="{s["seq"]}">'
            f'<div class="step-h"><strong>{escape(s["title"])}</strong>'
            f'<span class="name mono">{escape(s["name"])}</span>{status}'
            f'<span class="ms">{s["duration_ms"]} ms</span></div>'
            f'<div class="step-d">{escape(s["description"])}</div>'
            f'<div class="io">'
            f'<div><div class="k">input</div>{_pre(s["input"])}</div>'
            f'<div><div class="k">output</div>{_pre(s["output"])}</div>'
            f"</div></li>"
        )
    return '<ol class="steps">' + "".join(items) + "</ol>"


def _outcomes_html(outcomes: List[Dict[str, Any]], default_horizon: int) -> str:
    if not outcomes:
        return '<p class="sub">아직 채점 슬롯이 없습니다.</p>'

    rows = []
    for o in outcomes:
        h = o["horizon_days"]
        primary = ' class="primary"' if h == default_horizon else ""
        label = f'{h}거래일' + (" (기본)" if h == default_horizon else "")

        if o["status"] == "scored":
            hit_cls = "hit" if o["hit"] else "miss"
            hit_txt = "적중" if o["hit"] else "실패"
            ret = f'{o["return_pct"]:+.2f}%'
            rows.append(
                f"<tr{primary}><td>{escape(label)}</td>"
                f'<td class="{hit_cls}">{hit_txt}</td><td>{ret}</td>'
                f'<td class="mono">{escape(o["entry_date"] or "")}</td>'
                f'<td class="mono">{escape(o["exit_date"] or "")}</td>'
                f'<td>{o["entry_price"]:g} → {o["exit_price"]:g}</td></tr>'
            )
        else:
            note = o["note"] or ("지평 미경과" if o["status"] == "pending" else "")
            rows.append(
                f"<tr{primary}><td>{escape(label)}</td>"
                f'<td class="na" colspan="5">{escape(o["status"])}'
                f'{" · " + escape(note) if note else ""}</td></tr>'
            )

    return (
        '<div class="tw"><table><thead><tr>'
        "<th>지평</th><th>판정</th><th>수익률</th><th>진입일</th><th>청산일</th><th>종가</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def judgement_page(payload: Dict[str, Any], server_build: BuildInfo,
                   outcomes: Optional[List[Dict[str, Any]]] = None,
                   default_horizon: int = 21) -> str:
    """판정 1건을 HTML로 렌더링한다.

    페이지에는 판정 당시 반환한 JSON 원문이 그대로 들어간다. 화면에 보이는
    값과 API가 돌려준 값이 어긋날 여지를 두지 않기 위해서다.
    """
    build = payload.get("build", {})
    result = bool(payload.get("result"))
    verdict_cls = "t" if result else "f"
    verdict_txt = "TRUE" if result else "FALSE"

    drift = ""
    if build.get("commit") and build["commit"] != server_build.commit:
        drift = (
            '<p class="sub warn">⚠ 이 판정을 만든 커밋은 현재 서버에서 돌고 있는 '
            f"커밋({escape(server_build.commit_short)} / {escape(server_build.branch)})과 다릅니다.</p>"
        )

    dirty_mark = " (dirty)" if build.get("dirty") else ""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>판정 {escape(str(payload.get("id", "")))} · {escape(str(payload.get("ticker", "")))}</title>
<meta name="x-git-commit" content="{escape(str(build.get("commit", "")))}">
<meta name="x-git-branch" content="{escape(str(build.get("branch", "")))}">
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>{escape(str(payload.get("ticker", "")))} <span class="verdict {verdict_cls}">{verdict_txt}</span></h1>
  <p class="sub mono">{escape(str(payload.get("id", "")))} · {escape(str(payload.get("created_at", "")))}</p>
  {drift}

  <h2>판정 요약</h2>
  <div class="grid">
    {_cell("종목 (입력)", str(payload.get("ticker", "")))}
    {_cell("종목 (정규화)", str(payload.get("normalized_ticker", "")), mono=True)}
    {_cell("시장", str(payload.get("market", "")))}
    {_cell("판정", verdict_txt)}
    {_cell("규칙 세트", str(payload.get("ruleset_version", "")), mono=True)}
    {_cell("기준일", str(payload.get("as_of_date", "")), mono=True)}
  </div>

  <h2>빌드 정보 (판정 당시)</h2>
  <div class="grid">
    {_cell("branch", str(build.get("branch", "unknown")) + dirty_mark, mono=True)}
    {_cell("commit", str(build.get("commit", "unknown")), mono=True)}
  </div>

  <h2>지평별 결과</h2>
  {_outcomes_html(outcomes or [], default_horizon)}

  <h2>판정 프로세스</h2>
  {_steps_html(payload.get("process", []))}

  <h2>당시 반환 데이터 (원문)</h2>
  {_pre(payload)}

  <footer>
    이 페이지는 <span class="mono">{escape(str(build.get("commit", "unknown"))[:7])}</span>
    (<span class="mono">{escape(str(build.get("branch", "unknown")))}</span>) 시점 코드가 만든 판정입니다 ·
    <a href="/judgements/{escape(str(payload.get("id", "")))}">JSON으로 보기</a>
  </footer>
</div>
</body>
</html>
"""
