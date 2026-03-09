# Qwen2.5-1.5B vLLM 실행 가이드 (RTX 2060)

RTX 2060 (6GB VRAM)에서 vLLM을 사용하여 Qwen2.5-1.5B GGUF 모델을 실행하는 방법입니다.

## 환경 사양

| 항목 | 요구사항 |
|------|----------|
| GPU | NVIDIA RTX 2060 (6GB VRAM) |
| CUDA | 12.1 이상 |
| Python | 3.10 |
| RAM | 8GB 이상 (권장) |

## 설치 방법

### 1. 디렉토리 이동

```bash
cd vllm
```

### 2. Python 3.10 설치 (시스템에 없는 경우)

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install python3.10 python3.10-venv python3.10-dev
```

**macOS (Homebrew):**
```bash
brew install python@3.10
```

**Windows:**
[Python 3.10 다운로드](https://www.python.org/downloads/release/python-3100/)에서 설치

### 3. 가상환경 생성 및 활성화

```bash
# Linux/Mac
python3.10 -m venv venv
source venv/bin/activate

# Windows
python3.10 -m venv venv
venv\Scripts\activate
```

### 4. 의존성 설치

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. 환경변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 열어 필요시 수정:
- `CUDA_VISIBLE_DEVICES`: GPU 번호 (기본값: 0)
- `VLLM_GPU_MEMORY_UTILIZATION`: VRAM 사용률 (기본값: 0.85)
- `VLLM_MAX_MODEL_LEN`: 최대 컨텍스트 길이 (기본값: 2048)

### 6. 모델 다운로드 (선택)

첫 실행 시 자동으로 다운로드되지만, 미리 다운로드하려면:

```bash
# HuggingFace CLI 사용
huggingface-cli download Qwen/Qwen2.5-1.5B-Instruct-GGUF --local-dir ./models/Qwen2.5-1.5B-GGUF
```

## 실행

### Linux/Mac

```bash
chmod +x run_server.sh
./run_server.sh
```

### Windows

```bash
run_server.bat
```

### 직접 실행

```bash
source venv/bin/activate
python serve_qwen.py
```

## API 사용

### cURL

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "안녕하세요!"}
    ],
    "max_tokens": 256,
    "temperature": 0.7
  }'
```

### Python (OpenAI 클라이언트)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="dummy"  # 로컬 서버이므로 더미 키
)

response = client.chat.completions.create(
    model="Qwen/Qwen2.5-1.5B-Instruct-GGUF",
    messages=[{"role": "user", "content": "안녕하세요!"}],
    max_tokens=256,
    temperature=0.7
)

print(response.choices[0].message.content)
```

### 문서 확인

브라우저에서 http://localhost:8000/docs 접속

## RTX 2060 최적화 파라미터

| 환경변수 | 기본값 | 설명 |
|----------|--------|------|
| `VLLM_GPU_MEMORY_UTILIZATION` | 0.85 | VRAM 사용률 (0.5~0.9) |
| `VLLM_MAX_MODEL_LEN` | 2048 | 최대 컨텍스트 길이 |
| `VLLM_ENFORCE_EAGER` | true | Eager mode (안정성) |
| `MODEL_QUANTIZATION` | q4_k_m | GGUF 양자화 수준 |

### VRAM 부족 시

`.env` 파일에서 다음처럼 수정:

```bash
VLLM_GPU_MEMORY_UTILIZATION=0.7
VLLM_MAX_MODEL_LEN=1024
```

### 속도 최적화

더 나은 성능이 필요하면 ( estabilidad牺牲):

```bash
VLLM_ENFORCE_EAGER=false
```

## 문제해결

### "CUDA out of memory" 오류

VRAM 사용률을 낮추세요:

```bash
VLLM_GPU_MEMORY_UTILIZATION=0.6
```

### 모델 로드 실패

```bash
# HuggingFace 캐시 확인
ls -la ~/.cache/huggingface/hub/

# 수동 다운로드
huggingface-cli download Qwen/Qwen2.5-1.5B-Instruct-GGUF
```

### 속도가 매우 느릴 때

- `enforce_eager=false` 시도
- 배치 크기 감소
- VRAM Utilization 낮추기

### 드라이버 확인

```bash
nvidia-smi
```

## 성능 기준 (RTX 2060)

| 양자화 | VRAM 사용 | 속도 (tok/s) |
|--------|-----------|--------------|
| Q4_K_M | ~1.5GB | ~15-25 |
| Q6_K | ~2.5GB | ~10-18 |
| FP16 | ~3.5GB | ~8-12 |

## 관련 링크

- [vLLM 문서](https://docs.vllm.ai/)
- [Qwen2.5 HuggingFace](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF)
- [GGUF 양자화](https://github.com/ggerganov/llama.cpp/tree/master/gguf)

## 라이선스

이 코드는 MIT 라이선스입니다. 모델 사용 시 Qwen 라이선스를 따라주세요.
