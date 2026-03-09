import streamlit as st
from llm import get_llm_client
from utils import extract_text_from_file
from retrieval import TfidfRetriever, BM25Retriever


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
        st.session_state.plan_result = f"오류: {str(e)}"


def validate_document(text: str, guidelines: str, llm_client):
    if not text or not guidelines or not llm_client:
        return None
    
    try:
        result = llm_client.validate(text, guidelines)
        st.session_state.validation_result = result
    except Exception as e:
        st.session_state.validation_result = f"오류: {str(e)}"


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
    st.header("문서 작성")
    
    user_text = st.text_area(
        "문서를 작성해 주세요...",
        height=500,
        key="user_text"
    )
    
    if plan_mode and st.button("계획 생성", type="secondary") and user_text and st.session_state.guidelines and st.session_state.llm_client:
        generate_plan(user_text, st.session_state.guidelines, st.session_state.llm_client)
    
    validate_btn = st.button("검증하기", type="primary")
    
    if validate_btn and user_text and st.session_state.guidelines and st.session_state.llm_client:
        if plan_mode and st.session_state.plan_result:
            guidelines_to_use = st.session_state.guidelines
            if retrieval_mode and st.session_state.retriever:
                retrieved = run_retrieval(
                    user_text + "\n\n" + st.session_state.plan_result,
                    st.session_state.retriever,
                    st.session_state.guideline_chunks,
                    top_k
                )
                if retrieved:
                    st.session_state.retrieval_result = retrieved
                    guidelines_to_use = "\n\n".join([r["text"] for r in retrieved])
            
            validate_document(user_text, guidelines_to_use, st.session_state.llm_client)
        elif retrieval_mode and st.session_state.retriever:
            retrieved = run_retrieval(
                user_text,
                st.session_state.retriever,
                st.session_state.guideline_chunks,
                top_k
            )
            if retrieved:
                st.session_state.retrieval_result = retrieved
                guidelines_to_use = "\n\n".join([r["text"] for r in retrieved])
                validate_document(user_text, guidelines_to_use, st.session_state.llm_client)
            else:
                validate_document(user_text, st.session_state.guidelines, st.session_state.llm_client)
        else:
            validate_document(user_text, st.session_state.guidelines, st.session_state.llm_client)
    
    elif not st.session_state.llm_client:
        st.warning("먼저 사이드바에서 LLM을 설정해 주세요.")
    elif not st.session_state.guidelines:
        st.warning("먼저 가이드라인 파일을 업로드해 주세요.")

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
