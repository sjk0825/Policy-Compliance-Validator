import streamlit as st
import os
import logging
from datetime import datetime
from llm import get_llm_client
from utils import extract_text_from_file
from retrieval import TfidfRetriever, BM25Retriever


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


st.set_page_config(page_title="문서 검증기", layout="wide")

if 'llm_client' not in st.session_state:
    st.session_state.llm_client = None
if 'guidelines' not in st.session_state:
    st.session_state.guidelines = None
if 'validation_result' not in st.session_state:
    st.session_state.validation_result = None
if 'plan_result' not in st.session_state:
    st.session_state.plan_result = None
if 'retrieval_result' not in st.session_state:
    st.session_state.retrieval_result = None
if 'retriever' not in st.session_state:
    st.session_state.retriever = None
if 'guideline_chunks' not in st.session_state:
    st.session_state.guideline_chunks = None
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []


def chunk_text(text: str, chunk_size: int = 500) -> list:
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunks.append(' '.join(words[i:i + chunk_size]))
    return chunks


def create_retriever(algorithm: str):
    if algorithm == "TF-IDF":
        return TfidfRetriever()
    elif algorithm == "BM25":
        return BM25Retriever()
    return None


def run_retrieval(query: str, retriever, guideline_chunks: list, top_k: int = 5):
    if not retriever or not guideline_chunks:
        return None
    
    results = retriever.retrieve(query, top_k)
    retrieved_texts = []
    for idx, score in results:
        retrieved_texts.append({
            "index": idx,
            "score": score,
            "text": guideline_chunks[idx]
        })
    return retrieved_texts


def generate_plan(text: str, guidelines: str, llm_client):
    if not text or not guidelines or not llm_client:
        return None
    
    try:
        result = llm_client.plan(text, guidelines)
        st.session_state.plan_result = result
    except Exception as e:
        logger.error(f"Plan 생성 오류: {str(e)}", exc_info=True)
        st.session_state.plan_result = f"오류: {str(e)}"


def validate_document(text: str, guidelines: str, llm_client):
    if not text or not guidelines or not llm_client:
        return None
    
    try:
        result = llm_client.validate(text, guidelines)
        st.session_state.validation_result = result
    except Exception as e:
        logger.error(f"문서 검증 오류: {str(e)}", exc_info=True)
        st.session_state.validation_result = f"오류: {str(e)}"


def handle_speaker1_message(message: str):
    if message.strip():
        st.session_state.chat_history.append({
            "role": "speaker_1",
            "content": message,
            "timestamp": len(st.session_state.chat_history)
        })


def handle_speaker2_message(message: str, llm_client, guidelines: str):
    if message.strip() and llm_client and guidelines:
        st.session_state.chat_history.append({
            "role": "speaker_2",
            "content": message,
            "timestamp": len(st.session_state.chat_history)
        })
        
        try:
            response = llm_client.chat(message, guidelines)
            st.session_state.chat_history.append({
                "role": "speaker_2",
                "content": response,
                "timestamp": len(st.session_state.chat_history),
                "is_response": True
            })
        except Exception as e:
            logger.error(f"Chat 응답 오류: {str(e)}", exc_info=True)
            st.session_state.chat_history.append({
                "role": "speaker_2",
                "content": f"오류: {str(e)}",
                "timestamp": len(st.session_state.chat_history),
                "is_response": True
            })


st.title("📝 문서 검증기")

with st.sidebar:
    st.header("LLM 설정")
    
    provider = st.selectbox(
        "LLM 선택",
        ["openai", "claude", "vllm"],
        format_func=lambda x: {"openai": "OpenAI", "claude": "Claude", "vllm": "vLLM"}[x]
    )
    
    api_key = st.text_input("API Key", type="password")
    
    base_url = None
    if provider == "vllm":
        base_url = st.text_input("Base URL", value="http://localhost:8000/v1")
    
    submit_btn = st.button("설정 저장")
    
    if submit_btn:
        if not api_key:
            st.error("API Key를 입력해 주세요.")
        else:
            try:
                st.session_state.llm_client = get_llm_client(provider, api_key, base_url)
                st.success(f"{provider.upper()} 설정 완료!")
            except Exception as e:
                st.error(f"설정 오류: {str(e)}")
    
    st.divider()
    
    st.header("가이드라인 업로드")
    guideline_file = st.file_uploader(
        "가이드라인 파일 (PDF, JPG, TXT)",
        type=["pdf", "jpg", "jpeg", "png", "txt"]
    )
    
    if guideline_file:
        try:
            st.session_state.guidelines = extract_text_from_file(guideline_file)
            st.session_state.guideline_chunks = chunk_text(st.session_state.guidelines)
            with st.expander("가이드라인 미리보기"):
                st.text(st.session_state.guidelines[:1000] + "..." if len(st.session_state.guidelines) > 1000 else st.session_state.guidelines)
        except Exception as e:
            st.error(f"파일 읽기 오류: {str(e)}")
    
    st.divider()
    
    st.header("Agent 설정")
    
    plan_mode = st.toggle("Plan Mode", value=False)
    retrieval_mode = st.toggle("Retrieval", value=False)
    
    if retrieval_mode:
        retriever_algorithm = st.selectbox(
            "检索 알고리즘",
            ["TF-IDF", "BM25"]
        )
        
        top_k = st.slider("검색 결과 수", min_value=1, max_value=10, value=3)
        
        if st.button("Retrieval 초기화"):
            retriever = create_retriever(retriever_algorithm)
            if retriever and st.session_state.guideline_chunks:
                retriever.index(st.session_state.guideline_chunks)
                st.session_state.retriever = retriever
                st.success("Retrieval 초기화 완료!")

col1, col2 = st.columns([2, 1])

with col1:
    st.header("대화")
    
    speaker1_col, speaker2_col = st.columns(2)
    
    with speaker1_col:
        st.subheader("Speaker 1")
        speaker1_input = st.text_area(
            "입력...",
            height=150,
            key="speaker1_input"
        )
        if st.button("전송", key="speaker1_send", use_container_width=True):
            handle_speaker1_message(speaker1_input)
            st.rerun()
    
    with speaker2_col:
        st.subheader("Speaker 2 (가이드라인 적용)")
        speaker2_input = st.text_area(
            "입력...",
            height=150,
            key="speaker2_input"
        )
        if st.button("전송", key="speaker2_send", use_container_width=True):
            if not st.session_state.llm_client:
                st.error("먼저 사이드바에서 LLM을 설정해 주세요.")
            elif not st.session_state.guidelines:
                st.error("가이드라인 파일을 업로드해 주세요.")
            else:
                handle_speaker2_message(speaker2_input, st.session_state.llm_client, st.session_state.guidelines)
                st.rerun()
    
    st.divider()
    
    if st.button("대화 초기화"):
        st.session_state.chat_history = []
        st.rerun()
    
    st.subheader("대화 기록")
    for msg in st.session_state.chat_history:
        if msg["role"] == "speaker_1":
            with st.chat_message("user", avatar="🧑"):
                st.markdown(f"**Speaker 1:** {msg['content']}")
        elif msg.get("is_response"):
            with st.chat_message("assistant", avatar="🤖"):
                st.markdown(f"**Speaker 2 (응답):** {msg['content']}")
        else:
            with st.chat_message("user", avatar="🧑"):
                st.markdown(f"**Speaker 2:** {msg['content']}")

with col2:
    st.header("검증 결과")
    
    if plan_mode:
        st.subheader("📋 검증 계획")
        if st.session_state.plan_result:
            st.markdown(st.session_state.plan_result)
        else:
            st.info("'계획 생성' 버튼을 눌러 검증 계획을 생성해 주세요.")
        
        st.divider()
        
        if retrieval_mode:
            st.subheader("🔍检索 결과")
            if st.session_state.retrieval_result:
                for i, result in enumerate(st.session_state.retrieval_result):
                    st.markdown(f"**{i+1}.** (점수: {result['score']:.3f})")
                    st.text(result['text'][:200] + "..." if len(result['text']) > 200 else result['text'])
                    st.divider()
            else:
                st.info("검증 시检索 결과가 여기에 표시됩니다.")
            
            st.divider()
    
    st.subheader("✅ 최종 검증 결과")
    if st.session_state.validation_result:
        st.markdown(st.session_state.validation_result)
    else:
        st.info("문서를 작성하면 검증 결과가 여기에 표시됩니다.")
