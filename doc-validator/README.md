### 문서 검증기 (Document Validator)

LLM을 사용하여 사용자가 작성한 문서를 가이드라인과 비교하여 실시간으로 검증해주는 도구입니다.

## 기능

- **다중 LLM 지원**: OpenAI, Claude, vLLM 선택 가능
- **가이드라인 업로드 지원**: PDF, TXT, JPG, PNG 등 가이드라인 업로드 가능
- **대화 내 가이드라인 Agent 검증 지원**: 대화 내 가이드라인 검증 기능 지원
- **Plan Mode 지원**: 가이드 라인 검증 시 Plan Step 여부 선택 가능
- **거래내역 업로드/차트뷰 지원**: csv 거래내역 업로드 기능, 차트뷰 view 제공


## 설치

### 1. 필수 패키지 설치 (venv)

```bash

## 설치

### 1. 필수 패키지 설치 (venv)

```bash
# 파이썬 가상환경 생성
apk update
apk add python3 py3-pip
apk add build-base
apk add --no-cache \
build-base \
python3-dev \
py3-numpy-dev \
gfortran \
musl-dev \
pkgconf \
openblas-dev \
lapack-dev \
git \
tesseract-ocr \
tesseract-ocr-data-kor

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 패키지 설치
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
├── stock_chart.py  
├── requirements.txt       
├── llm/                  
│   ├── __init__.py
│   ├── base.py          
│   ├── openai_.py        
│   ├── claude.py         
│   └── vllm.py           
├── utils/                
│   ├── __init__.py
│   └── file_processor.py 
├── retrieval/            
│   ├── __init__.py
│   ├── base.py           
│   ├── tfidf_retriever.py
│   ├── bm25_retriever.py
│   └── embedding_retriever.py
├── agent/                 
│   ├── __init__.py
│   ├── core.py
│   ├── brain.py
│   ├── state.py
│   ├── memory/
│   ├── prompts/
│   └── tools/
└── logs/
```

