### 문서 검증기 (Document Validator)

LLM을 사용하여 사용자가 작성한 문서를 가이드라인과 비교하여 실시간으로 검증해주는 도구입니다.

## 기능

- **다중 LLM 지원**: OpenAI, Claude, vLLM 선택 가능
- **다중 검색 방법**: TF-IDF, BM25, Embedding 기반 검색
- **가이드라인 업로드**: PDF, JPG, PNG, TXT 파일 지원
- **Plan 설정**: 검증 전 문서 분석 계획 생성 기능
- **결과 표시**: 관련 가이드라인 라인번호와 문제점, 개선 제안 표시

## 설치

### 1. 필수 패키지 설치 (venv)

```bash
# 파이썬 가상환경 생성
python -m venv venv

# 가상환경 활성화
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# 패키지 설치
pip install -r requirements.txt
```

**참고**: pip 에러가 발생하면 `--break-system-packages` 플래그를 추가하세요.


## 실행

```bash
streamlit run app.py
```

## 환경변수 (.env)

```bash
cp .env.example .env
# .env 파일에 실제 API Key 입력
```

## 프로젝트 구조

```
doc-validator/
├── app.py                 
├── requirements.txt       
├── .env.example          
├── llm/                  
│   ├── __init__.py
│   ├── base.py          
│   ├── openai_.py        
│   ├── claude.py         
│   └── vllm.py           
├── utils/                
│   ├── __init__.py
│   └── file_processor.py 
└── retrieval/            
    ├── __init__.py
    ├── base.py           
    ├── tfidf_retriever.py
    ├── bm25_retriever.py
    └── embedding_retriever.py
```
