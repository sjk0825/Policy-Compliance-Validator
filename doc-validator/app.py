import streamlit as st

from services.agent_service import setup_logging, initialize_agent, build_retriever
from agent.tools import RetrievalTool, StockChartTool, StockComparisonTool
from ui.document_section import render_conversation_panel
from ui.dbmf_sidebar import render_dbmf_sidebar

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

render_dbmf_sidebar()

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
                        tools=[StockChartTool(), StockComparisonTool()]
                    )
                    st.success(f"Agent 초기화 완료! ({provider.upper()})")
                except Exception as e:
                    st.error(f"초기화 오류: {str(e)}")
                    logger.error(f"Agent 초기화 오류: {str(e)}", exc_info=True)

st.divider()
st.text_area(
    "📋 srule",
    value="DBMF는 역추세 자산이다. 시장 하락·변동성 확대 시 비중을 늘린다.\nQQQ는 추세 자산이다. 상승 모멘텀이 강할 때 비중을 늘린다.",
    height=120,
    key="srule_input",
)

render_conversation_panel()
