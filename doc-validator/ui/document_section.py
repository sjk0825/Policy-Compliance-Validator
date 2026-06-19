import streamlit as st
import streamlit.components.v1 as components
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("doc_validator")


def _get_chart_context() -> str:
    try:
        import FinanceDataReader as fdr
        end = datetime.now()
        start = end - timedelta(days=90)
        lines = []
        for ticker in ["DBMF", "QQQ"]:
            df = fdr.DataReader(ticker, start=start, end=end)
            if df.empty:
                continue
            df = df.reset_index()
            close = df["Close"]
            latest = close.iloc[-1]
            prev = close.iloc[-2]
            pct = (latest - prev) / prev * 100
            period_pct = (latest / close.iloc[0] - 1) * 100
            lines.append(
                f"{ticker}: 현재가 ${latest:.2f}, 전일대비 {pct:+.2f}%, "
                f"3개월 누적 {period_pct:+.2f}%"
            )
        if lines:
            return "[현재 시장 데이터 (자동 로드)]\n" + "\n".join(lines)
    except Exception:
        pass
    return ""


def render_conversation_panel():
    st.divider()

    agent = st.session_state.get("agent")
    if not agent:
        st.info("Agent를 먼저 초기화해 주세요.")
        return

    chat_container = st.container()
    with chat_container:
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    if prompt := st.chat_input("메시지를 입력하세요..."):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("처리 중..."):
                try:
                    srule = st.session_state.get("srule_input", "")
                    agent.set_srule(srule)

                    chart_context = _get_chart_context()
                    agent.set_guidelines(chart_context)

                    enable_retrieval = st.session_state.get("enable_retrieval", True)
                    response = agent.execute(prompt, enable_retrieval=enable_retrieval)
                    if response.success:
                        st.markdown(response.content)

                        stock_result = response.context.tool_results.get("stock_chart")
                        if stock_result and stock_result.success:
                            components.html(stock_result.data["html"], height=550)

                        comp_result = response.context.tool_results.get("stock_comparison")
                        if comp_result and comp_result.success:
                            components.html(comp_result.data["html"], height=550)

                        st.session_state.chat_history.append(
                            {"role": "assistant", "content": response.content}
                        )
                    else:
                        error_msg = response.error or "응답 생성에 실패했습니다."
                        st.error(error_msg)
                        st.session_state.chat_history.append(
                            {"role": "assistant", "content": f"오류: {error_msg}"}
                        )
                except Exception as e:
                    st.error(f"처리 중 오류가 발생했습니다: {str(e)}")
                    logger.error(f"Agent execution error: {e}", exc_info=True)
                    st.session_state.chat_history.append(
                        {"role": "assistant", "content": f"오류: {str(e)}"}
                    )

    with st.expander("⚙️ 관리"):
        col1, col2 = st.columns(2)
        with col1:
            if st.button("대화 초기화", type="secondary", use_container_width=True):
                agent.clear_conversation()
                st.session_state.chat_history = []
                st.session_state.agent_response = None
                st.rerun()
        with col2:
            if st.button("전체 검증 실행", type="primary", use_container_width=True):
                text_to_validate = "\n".join(
                    m["content"] for m in st.session_state.chat_history
                    if m["role"] == "user"
                )
                if text_to_validate:
                    with st.spinner("문서 검증 중..."):
                        result = agent.validate(text_to_validate)
                        if result.success:
                            st.session_state.validation_result = result.content
                            st.success("검증 완료!")
                        else:
                            st.error(f"검증 실패: {result.error}")
