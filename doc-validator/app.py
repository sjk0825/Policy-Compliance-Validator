import streamlit as st

from services.agent_service import setup_logging, initialize_agent, build_retriever
from agent.tools import RetrievalTool, StockChartTool
from ui.document_section import render_conversation_panel

logger = setup_logging()

st.set_page_config(page_title="문서 검증기 (Agent)", layout="wide")

_DEFAULTS = {
    "agent": None,
    "retrieval_tool": None,
    "guidelines": None,
    "guideline_chunks": None,
    "validation_result": None,
    "plan_result": None,
    "chat_history": [],
    "agent_response": None,
    "enable_retrieval": False,
}
for key, val in _DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = val

st.title("문서 검증기 (Agent Mode)")

tab1, = st.tabs(["문서 검증"])

with tab1:
    st.header("LLM & Agent 설정")

    col1, col2 = st.columns(2)

    with col1:
        provider = st.selectbox(
            "LLM 선택",
            ["openai", "claude", "vllm"],
            format_func=lambda x: {"openai": "OpenAI", "claude": "Claude", "vllm": "vLLM"}[x],
            key="provider_select"
        )
        api_key = st.text_input("API Key", type="password", key="api_key_input")

    with col2:
        base_url = None
        if provider == "vllm":
            base_url = st.text_input("Base URL", value="http://localhost:8000/v1", key="base_url_input")

    if st.button("Agent 초기화", type="primary", use_container_width=True):
        if not api_key:
            st.error("API Key를 입력해 주세요.")
        else:
            with st.spinner("Agent 초기화 중..."):
                try:
                    st.session_state.agent = initialize_agent(
                        provider, api_key, base_url,
                        tools=[StockChartTool()]
                    )
                    st.success(f"Agent 초기화 완료! ({provider.upper()})")
                except Exception as e:
                    st.error(f"초기화 오류: {str(e)}")
                    logger.error(f"Agent 초기화 오류: {str(e)}", exc_info=True)

render_conversation_panel()
