import streamlit as st
import logging

logger = logging.getLogger("doc_validator")



def render_agent_stats():
    st.subheader("📊 Agent 통계")

    if st.session_state.get("agent"):
        stats = st.session_state.agent.get_statistics()

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("대화 메시지", stats["conversation"]["total_messages"])
        with col2:
            val_stats = stats.get("validation", {})
            st.metric("검증 횟수", val_stats.get("total_validations", 0))
        with col3:
            st.metric("사용 도구", stats["tools"]["count"])
        with col4:
            brain_info = stats.get("brain", {})
            st.metric("LLM", brain_info.get("provider", "N/A").upper())
    else:
        st.info("Agent가 초기화되지 않았습니다.")


def render_conversation_panel():
    st.divider()
    st.header("💬 대화")

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
                    enable_retrieval = st.session_state.get("enable_retrieval", True)
                    response = agent.execute(prompt, enable_retrieval=enable_retrieval)
                    if response.success:
                        st.markdown(response.content)
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
