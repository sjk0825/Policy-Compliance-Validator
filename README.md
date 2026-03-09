# 문서 검증기 (Document Validator)

LLM을 사용하여 사용자가 작성한 문서를 가이드라인과 비교하여 실시간으로 검증해주는 도구입니다.

## 기능

- **다중 LLM 지원**: OpenAI, Claude, vLLM 선택 가능
- **가이드라인 업로드**: PDF, JPG, TXT 파일 지원
- **실시간 검증**: 디바운싱 기반 자동 검증
- **결과 표시**: 가이드라인 라인번호와 문제점 표시

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
tesseract-ocr tesseract-ocr-data-kor

python -m venv venv

# 가상환경 활성화
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# 패키지 설치
pip install -r requirements.txt
```

**참고**: pip 에러가 발생하면 `--break-system-packages` 플래그를 추가하세요.

### 2. Tesseract OCR 설치 (JPG/PNG 사용 시 필수)


## 실행

```bash
streamlit run app.py
```

## 사용 방법

1. **LLM 설정** (사이드바)
   - 사용할 LLM 선택 (OpenAI/Claude/vLLM)
   - API Key 입력
   - (vLLM의 경우) Base URL 입력
   - "설정 저장" 버튼 클릭

2. **가이드라인 업로드**
   - PDF, JPG, PNG, TXT 파일 업로드
   - 자동으로 텍스트 추출됨

3. **문서 작성**
   - 메인 영역에서 문서 작성
   - 입력 후 설정한 디바운싱 시간(초) 지나면 자동 검증

4. **결과 확인**
   - 우측 패널에서 검증 결과 확인
   - 가이드라인 라인번호와 문제점, 개선 제안 표시

## 환경변수 (.env)

```bash
cp .env.example .env
# .env 파일에 실제 API Key 입력
```

## 프로젝트 구조

```
doc-validator/
├── app.py                 # 메인 앱
├── requirements.txt       # 패키지 목록
├── .env.example          # 환경변수 예시
├── llm/                  # LLM 연동 모듈
│   ├── base.py           # 추상 클래스
│   ├── openai_.py        # OpenAI 구현
│   ├── claude.py         # Claude 구현
│   └── vllm.py           # vLLM 구현
└── utils/                # 유틸리티
    └── file_processor.py # 파일 처리
```
