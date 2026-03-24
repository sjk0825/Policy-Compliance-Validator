import streamlit as st
import os
import logging
import pandas as pd
from datetime import datetime

from agent import (
    AgentOrchestrator,
    Brain,
    AgentState,
    RetrievalTool,
    FileTool,
    CalculatorTool,
    WebSearchTool,
)
from agent.memory import ConversationMemory, DocumentMemory, ValidationMemory
from utils import extract_text_from_file
from stock_chart import parse_csv, get_stock_chart_data, create_stock_chart, get_unique_stocks, filter_transactions_by_stock


LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "streamlit_errors.log")

os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.ERROR,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


st.set_page_config(page_title="문서 검증기 (Agent)", layout="wide")


def chunk_text(text: str, chunk_size: int = 500) -> list:
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunks.append(' '.join(words[i:i + chunk_size]))
    return chunks


def initialize_agent(provider: str, api_key: str, base_url: str = None):
    brain = Brain(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model="gpt-4o-mini"
    )

    tools = [
        RetrievalTool(),
        FileTool(),
        CalculatorTool(),
        WebSearchTool(),
    ]

    agent = AgentOrchestrator(
        brain=brain,
        tools=tools,
        conversation_memory=ConversationMemory(),
        document_memory=DocumentMemory(),
        validation_memory=ValidationMemory()
    )

    return agent


if 'agent' not in st.session_state:
    st.session_state.agent = None
if 'retrieval_tool' not in st.session_state:
    st.session_state.retrieval_tool = None
if 'guidelines' not in st.session_state:
    st.session_state.guidelines = None
if 'guideline_chunks' not in st.session_state:
    st.session_state.guideline_chunks = None
if 'validation_result' not in st.session_state:
    st.session_state.validation_result = None
if 'plan_result' not in st.session_state:
    st.session_state.plan_result = None
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'stock_df' not in st.session_state:
    st.session_state.stock_df = None
if 'agent_response' not in st.session_state:
    st.session_state.agent_response = None


st.title("🤖 문서 검증기 (Agent Mode)")

tab1, = st.tabs(["📄 문서 검증"])

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
        
        enable_retrieval = st.toggle("Retrieval 활성화", value=True, help="가이드라인 검색 활성화")
        
        if enable_retrieval:
            retriever_algorithm = st.selectbox(
                "검색 알고리즘",
                ["TF-IDF", "BM25", "Milvus"],
                key="retriever_algo"
            )
    
    submit_btn = st.button("🚀 Agent 초기화", type="primary", use_container_width=True)
    
    if submit_btn:
        if not api_key:
            st.error("API Key를 입력해 주세요.")
        else:
            with st.spinner("Agent 초기화 중..."):
                try:
                    st.session_state.agent = initialize_agent(provider, api_key, base_url)
                    
                    if enable_retrieval:
                        from retrieval import TfidfRetriever, BM25Retriever, MilvusRetriever
                        
                        if retriever_algorithm == "TF-IDF":
                            retriever = TfidfRetriever()
                        elif retriever_algorithm == "BM25":
                            retriever = BM25Retriever()
                        else:
                            retriever = MilvusRetriever(api_key=api_key)
                        
                        st.session_state.retrieval_tool = RetrievalTool(retriever)
                        st.session_state.agent.add_tool(st.session_state.retrieval_tool)
                    
                    st.success(f"✅ Agent 초기화 완료! ({provider.upper()})")
                    
                except Exception as e:
                    st.error(f"초기화 오류: {str(e)}")
                    logger.error(f"Agent 초기화 오류: {str(e)}", exc_info=True)

    st.divider()

    col_csv, col_view = st.columns([2, 1])
    
    with col_csv:
        st.subheader("CSV 파일 업로드")
        st.caption("컬럼: 주식이름, 주식번호, 구매금액, 판매금액, 날짜")
        csv_file = st.file_uploader(
            "CSV 파일을 업로드하세요",
            type=["csv"],
            key="stock_csv_uploader"
        )
    
    with col_view:
        st.subheader(" ")
        view_button = st.button("🔍 뷰", use_container_width=True, type="primary")
    
    if csv_file:
        try:
            df = parse_csv(csv_file)
            st.session_state.stock_df = df
            st.success(f"✅ CSV 로드 완료! ({len(df)}건)")
            
            unique_stocks = get_unique_stocks(df)
            
            st.subheader("주식 선택")
            selected_stock = st.selectbox(
                "조회할 주식을 선택하세요",
                options=unique_stocks,
                key="stock_selector"
            )
            
            if selected_stock and selected_stock is not None:
                stock_transactions = filter_transactions_by_stock(df, selected_stock)
                stock_code_row = stock_transactions['주식번호'].iloc[0]
                
                with st.spinner("차트 데이터 로딩 중..."):
                    try:
                        stock_transactions = stock_transactions.sort_values('날짜')
                        stock_transactions['날짜'] = pd.to_datetime(stock_transactions['날짜'])
                        
                        start_date = str((stock_transactions['날짜'].min() - pd.DateOffset(years=1)).date())
                        end_date = str(stock_transactions['날짜'].max().date())
                        
                        chart_data = get_stock_chart_data(str(stock_code_row), start_date, end_date)
                        fig = create_stock_chart(chart_data, stock_transactions, selected_stock)
                        st.plotly_chart(fig, use_container_width=True)
                        
                        st.divider()
                        st.subheader("📝 상세 거래 내역")
                        
                        display_df = stock_transactions.copy()
                        
                        def get_type_and_amount(row):
                            if row['구매금액'] > 0:
                                return "🔵 구매", row['구매금액']
                            elif row['판매금액'] > 0:
                                return "🔴 판매", row['판매금액']
                            return "기타", 0

                        display_df[['유형', '거래금액']] = display_df.apply(
                            lambda x: pd.Series(get_type_and_amount(x)), axis=1
                        )

                        report_view = display_df[['날짜', '유형', '거래금액']].sort_values('날짜', ascending=False)

                        st.dataframe(
                            report_view,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "날짜": st.column_config.DateColumn("거래일자", format="YYYY-MM-DD"),
                                "유형": st.column_config.TextColumn("구분"),
                                "거래금액": st.column_config.NumberColumn("금액", format="%d원")
                            }
                        )
                        
                        if report_view.empty:
                            st.info("거래 내역이 없습니다.")

                    except Exception as e:
                        st.error(f"데이터 처리 오류: {str(e)}")
                        st.info("데이터의 날짜가 미래이거나 주식 번호가 정확한지 확인해 주세요.")

        except Exception as e:
            st.error(f"CSV 처리 오류: {str(e)}")
    else:
        st.info("👆 CSV 파일을 업로드하고 '뷰' 버튼을 눌러주세요.")

    st.divider()
    
    st.header("가이드라인 업로드")
    guideline_file = st.file_uploader(
        "가이드라인 파일 (PDF, JPG, TXT)",
        type=["pdf", "jpg", "jpeg", "png", "txt"]
    )
    
    if guideline_file:
        try:
            guidelines = extract_text_from_file(guideline_file)
            guideline_chunks = chunk_text(guidelines)
            
            st.session_state.guidelines = guidelines
            st.session_state.guideline_chunks = guideline_chunks
            
            if st.session_state.agent:
                st.session_state.agent.set_guidelines(guidelines, guideline_chunks)
                st.success("✅ 가이드라인이 Agent에 로드되었습니다.")
            
            with st.expander("가이드라인 미리보기"):
                st.text(guidelines[:1000] + "..." if len(guidelines) > 1000 else guidelines)
                
        except Exception as e:
            st.error(f"파일 읽기 오류: {str(e)}")

    st.divider()
    
    st.header("🔧 Agent 도구 상태")
    if st.session_state.agent:
        stats = st.session_state.agent.get_statistics()
        col_t1, col_t2, col_t3, col_t4 = st.columns(4)
        
        with col_t1:
            st.metric("Provider", stats["brain"]["provider"].upper())
        with col_t2:
            st.metric("Model", stats["brain"]["model"])
        with col_t3:
            st.metric("도구 수", stats["tools"]["count"])
        with col_t4:
            st.metric("대화 수", stats["conversation"]["history"].get("total_messages", 0))
        
        st.caption(f"사용 가능 도구: {', '.join(stats['tools']['available'])}")
    else:
        st.info("Agent를 초기화해주세요.")


col1, col2 = st.columns([2, 1])

with col1:
    st.header("💬 대화")
    
    st.subheader("사용자 입력")
    user_input = st.text_area(
        "메시지를 입력하세요...",
        height=150,
        key="user_input_area",
        placeholder="가이드라인에 대해 질문하거나 문서를 검증해주세요."
    )
    
    col_validate, col_plan, col_chat = st.columns(3)
    
    with col_validate:
        if st.button("📋 검증", use_container_width=True, type="primary"):
            if not st.session_state.agent:
                st.error("Agent를 초기화해주세요.")
            elif not st.session_state.guidelines:
                st.error("가이드라인을 업로드해주세요.")
            else:
                with st.spinner("검증 중..."):
                    response = st.session_state.agent.validate(user_input)
                    st.session_state.validation_result = response.content
                    st.session_state.agent_response = response
                    if response.success:
                        st.success("검증 완료!")
                    else:
                        st.error(f"오류: {response.error}")
    
    with col_plan:
        if st.button("📝 계획 생성", use_container_width=True):
            if not st.session_state.agent:
                st.error("Agent를 초기화해주세요.")
            elif not st.session_state.guidelines:
                st.error("가이드라인을 업로드해주세요.")
            else:
                with st.spinner("계획 생성 중..."):
                    response = st.session_state.agent.plan(user_input)
                    st.session_state.plan_result = response.content
                    st.session_state.agent_response = response
                    if response.success:
                        st.success("계획 생성 완료!")
                    else:
                        st.error(f"오류: {response.error}")
    
    with col_chat:
        retrieval_enabled = enable_retrieval if 'enable_retrieval' in dir() else False
        if st.button("💬 대화", use_container_width=True):
            if not st.session_state.agent:
                st.error("Agent를 초기화해주세요.")
            elif not st.session_state.guidelines:
                st.error("가이드라인을 업로드해주세요.")
            else:
                with st.spinner("응답 생성 중..."):
                    response = st.session_state.agent.execute(user_input, enable_retrieval=retrieval_enabled)
                    st.session_state.agent_response = response
                    if response.success:
                        st.chat_message("assistant").markdown(response.content)
                        st.success("응답 완료!")
                    else:
                        st.error(f"오류: {response.error}")

    st.divider()
    
    if st.button("🗑️ 대화 초기화"):
        if st.session_state.agent:
            st.session_state.agent.clear_conversation()
        st.session_state.chat_history = []
        st.session_state.validation_result = None
        st.session_state.plan_result = None
        st.rerun()

with col2:
    st.header("📊 결과")
    
    if st.session_state.agent_response:
        st.subheader("실행 정보")
        response = st.session_state.agent_response
        st.json({
            "success": response.success,
            "state": response.state.value,
            "elapsed": f"{response.context.metadata.get('elapsed_seconds', 0):.2f}s"
        })
        
        st.divider()
    
    st.subheader("📋 검증 결과")
    if st.session_state.validation_result:
        st.markdown(st.session_state.validation_result)
    else:
        st.info("검증 버튼을 눌러 결과를 확인하세요.")
    
    st.divider()
    
    st.subheader("📝 계획 결과")
    if st.session_state.plan_result:
        st.markdown(st.session_state.plan_result)
    else:
        st.info("계획 생성 버튼을 눌러 결과를 확인하세요.")
