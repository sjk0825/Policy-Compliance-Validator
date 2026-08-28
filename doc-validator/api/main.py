from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from . import pipeline, render, schemas, scoring
from .buildinfo import current_build
from .store import JudgementStore

app = FastAPI(
    title="Policy Compliance Validator API",
    description="종목을 입력받아 판정하고, 판정 근거가 된 실행 과정을 id로 되짚는 API.",
    version="0.1.0",
)

_store = JudgementStore()


def get_store() -> JudgementStore:
    return _store


def _build_headers() -> dict:
    """모든 응답에 이 응답을 만든 코드의 커밋/브랜치를 실어 보낸다."""
    b = current_build()
    return {"X-Git-Commit": b.commit, "X-Git-Branch": b.branch}


@app.middleware("http")
async def add_build_headers(request, call_next):
    response = await call_next(request)
    for k, v in _build_headers().items():
        response.headers[k] = v
    return response


@app.get("/health", response_model=schemas.HealthOut, tags=["meta"])
def health(store: JudgementStore = Depends(get_store)):
    return schemas.HealthOut(
        status="ok",
        ruleset_version=pipeline.RULESET_VERSION,
        build=current_build().to_dict(),
        judgement_count=store.count(),
        db_path=str(store.db_path),
    )


@app.post("/judgements", response_model=schemas.JudgementOut, status_code=201, tags=["judgement"])
def create_judgement(req: schemas.JudgeRequest, store: JudgementStore = Depends(get_store)):
    """종목을 판정한다. 현재 판정값은 스텁이라 항상 true다.

    응답의 process에 이 값이 나온 실행 단계가 그대로 들어가고,
    같은 내용이 id로 다시 조회된다.
    """
    judgement = pipeline.run(req.ticker, as_of=req.as_of)
    return store.save(judgement)


@app.get("/judgements", response_model=schemas.JudgementList, tags=["judgement"])
def list_judgements(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ticker: Optional[str] = Query(None, description="정규화된 티커로 필터"),
    store: JudgementStore = Depends(get_store),
):
    return schemas.JudgementList(
        total=store.count(ticker),
        limit=limit,
        offset=offset,
        items=store.list(limit=limit, offset=offset, ticker=ticker),
    )


@app.get(
    "/judgements/{judgement_id}",
    tags=["judgement"],
    responses={
        200: {
            "content": {"application/json": {}, "text/html": {}},
            "description": "판정 당시 반환한 데이터. format=html이면 같은 내용을 HTML로 렌더링한다.",
        },
        404: {"description": "해당 id의 판정 없음"},
    },
)
def get_judgement(
    judgement_id: str,
    format: str = Query("json", pattern="^(json|html)$"),
    store: JudgementStore = Depends(get_store),
):
    """id로 그 당시 판정 결과를 조회한다.

    저장해 둔 응답 원문을 그대로 돌려주므로, 이후 코드가 바뀌어도
    과거 판정은 당시 형태 그대로 남는다.
    """
    payload = store.get(judgement_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"판정 '{judgement_id}'을(를) 찾을 수 없습니다.")

    if format == "html":
        return HTMLResponse(render.judgement_page(
            payload,
            current_build(),
            outcomes=store.get_outcomes(judgement_id),
            default_horizon=pipeline.DEFAULT_HORIZON,
        ))
    return JSONResponse(payload)


@app.get("/judgements/{judgement_id}/process", response_model=schemas.ProcessOut, tags=["judgement"])
def get_judgement_process(judgement_id: str, store: JudgementStore = Depends(get_store)):
    """그 판정이 어떤 단계를 거쳐 나왔는지만 떼어서 돌려준다."""
    summary = store.get_summary(judgement_id)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"판정 '{judgement_id}'을(를) 찾을 수 없습니다.")

    return schemas.ProcessOut(
        id=summary["id"],
        ticker=summary["ticker"],
        result=summary["result"],
        ruleset_version=summary["ruleset_version"],
        created_at=summary["created_at"],
        build=summary["build"],
        process=store.get_steps(judgement_id),
    )


@app.get("/judgements/{judgement_id}/outcomes", response_model=schemas.OutcomesOut, tags=["outcome"])
def get_judgement_outcomes(judgement_id: str, store: JudgementStore = Depends(get_store)):
    """이 판정이 지평별로 어떻게 됐는지 돌려준다."""
    summary = store.get_summary(judgement_id)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"판정 '{judgement_id}'을(를) 찾을 수 없습니다.")

    return schemas.OutcomesOut(
        id=summary["id"],
        ticker=summary["ticker"],
        result=summary["result"],
        as_of_date=summary["as_of_date"],
        default_horizon=pipeline.DEFAULT_HORIZON,
        outcomes=store.get_outcomes(judgement_id),
    )


@app.post("/outcomes/score", response_model=schemas.ScoreRunOut, tags=["outcome"])
def run_scoring(
    limit: int = Query(500, ge=1, le=5000),
    retry_unavailable: bool = Query(
        False, description="시세를 못 받아 unavailable로 남은 건까지 다시 시도한다."
    ),
    store: JudgementStore = Depends(get_store),
):
    """지평이 경과한 판정을 채점한다. 스케줄러가 주기적으로 때리는 진입점."""
    return scoring.score_pending(store, limit=limit, retry_unavailable=retry_unavailable)


@app.get("/stats", response_model=schemas.StatsOut, tags=["outcome"])
def get_stats(
    ticker: Optional[str] = Query(None),
    store: JudgementStore = Depends(get_store),
):
    """지평별 적중률. 어느 주기에서 룰이 먹히는지 보는 지표."""
    return schemas.StatsOut(
        ticker=ticker,
        default_horizon=pipeline.DEFAULT_HORIZON,
        by_horizon=[store.hit_rate(h, ticker) for h in pipeline.HORIZONS],
    )
