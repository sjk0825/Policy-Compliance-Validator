import streamlit as st
import plotly.graph_objects as go
from datetime import datetime, timedelta


DBMF_INCEPTION = datetime(2019, 5, 14)  # DBMF 상장일

def _fetch(ticker: str, days):
    import FinanceDataReader as fdr
    end = datetime.now()
    start = DBMF_INCEPTION if days is None else end - timedelta(days=days)
    df = fdr.DataReader(ticker, start=start, end=end)
    df = df.reset_index()
    date_col = "Date" if "Date" in df.columns else df.columns[0]
    df["Date"] = df[date_col]
    return df


def render_dbmf_sidebar():
    with st.sidebar:
        st.subheader("📈 DBMF vs QQQ")
        period = st.selectbox("기간", ["1개월", "3개월", "6개월", "1년", "최대"], index=2, key="dbmf_period")
        days_map = {"1개월": 30, "3개월": 90, "6개월": 180, "1년": 365, "최대": None}
        days = days_map[period]

        try:
            dbmf = _fetch("DBMF", days)
            qqq = _fetch("QQQ", days)

            if dbmf.empty or qqq.empty:
                st.warning("데이터를 불러올 수 없습니다.")
                return

            # 메트릭: 각각 전일 대비
            def metric_vals(df):
                latest = df["Close"].iloc[-1]
                prev = df["Close"].iloc[-2] if len(df) > 1 else latest
                delta = latest - prev
                return latest, (delta / prev) * 100, delta

            d_price, d_pct, d_delta = metric_vals(dbmf)
            q_price, q_pct, q_delta = metric_vals(qqq)

            col1, col2 = st.columns(2)
            col1.metric("DBMF", f"${d_price:.2f}", f"{d_pct:+.2f}%")
            col2.metric("QQQ", f"${q_price:.2f}", f"{q_pct:+.2f}%")

            # 기준점 대비 % 변화로 정규화 (가격대 차이 해결)
            dbmf["pct"] = (dbmf["Close"] / dbmf["Close"].iloc[0] - 1) * 100
            qqq["pct"] = (qqq["Close"] / qqq["Close"].iloc[0] - 1) * 100

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=dbmf["Date"], y=dbmf["pct"],
                mode="lines", name="DBMF",
                line=dict(color="#2196F3", width=2),
            ))
            fig.add_trace(go.Scatter(
                x=qqq["Date"], y=qqq["pct"],
                mode="lines", name="QQQ",
                line=dict(color="#FF6B35", width=2),
            ))
            fig.add_hline(y=0, line=dict(color="gray", width=1, dash="dot"))
            fig.update_layout(
                margin=dict(l=0, r=0, t=10, b=0),
                height=280,
                xaxis=dict(showgrid=False, tickformat="%m/%d"),
                yaxis=dict(showgrid=True, ticksuffix="%"),
                template="plotly_white",
                legend=dict(orientation="h", y=1.08, x=0, font=dict(size=11)),
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption("기간 시작 대비 누적 수익률")

        except Exception as e:
            st.error(f"차트 로딩 실패: {e}")
