import streamlit as st
import pandas as pd
from stock_chart import parse_csv, get_stock_chart_data, create_stock_chart, get_unique_stocks, filter_transactions_by_stock
import plotly.graph_objects as go
import logging

logger = logging.getLogger("doc_validator")


def render_stock_section():
    st.subheader("📈 주식 포트폴리오 차트")

    uploaded_file = st.file_uploader(
        "CSV/Excel 업로드",
        type=["csv", "xlsx"],
        key="stock_file_uploader"
    )

    if uploaded_file:
        try:
            df = parse_csv(uploaded_file)
            st.session_state.stock_df = df
            st.success(f"파일 로드 완료! ({len(df)} rows)")
        except Exception as e:
            st.error(f"파일 파싱 오류: {str(e)}")
            logger.error(f"Stock file parse error: {e}", exc_info=True)
            return

    if st.session_state.stock_df is not None:
        df = st.session_state.stock_df
        stocks = get_unique_stocks(df)

        selected_stock = st.selectbox(
            "주식 선택",
            stocks,
            key="stock_select"
        )

        if selected_stock:
            try:
                transactions = filter_transactions_by_stock(df, selected_stock)

                start_date = transactions['날짜'].min().strftime('%Y-%m-%d')
                end_date = transactions['날짜'].max().strftime('%Y-%m-%d')

                with st.spinner("주가 데이터 로딩 중..."):
                    stock_data = get_stock_chart_data(
                        transactions['주식번호'].iloc[0],
                        start_date,
                        end_date
                    )

                fig = create_stock_chart(stock_data, transactions, selected_stock)
                st.plotly_chart(fig, use_container_width=True)

                with st.expander("📋 거래 내역"):
                    display_cols = ['날짜', '주식이름', '구매금액', '판매금액']
                    display_df = transactions[display_cols].copy()
                    display_df['날짜'] = display_df['날짜'].dt.strftime('%Y-%m-%d')
                    display_df['구매금액'] = display_df['구매금액'].fillna(0).astype(int)
                    display_df['판매금액'] = display_df['판매금액'].fillna(0).astype(int)
                    st.dataframe(display_df, use_container_width=True)

            except Exception as e:
                st.error(f"차트 생성 오류: {str(e)}")
                logger.error(f"Stock chart error: {e}", exc_info=True)
