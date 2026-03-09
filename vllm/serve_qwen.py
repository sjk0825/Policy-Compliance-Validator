"""
Qwen2.5-1.5B GGUF 모델을 vLLM API 서버로 실행
RTX 2060 (6GB VRAM) 최적화
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from vllm import LLM
from transformers import AutoTokenizer

MODEL_PATH = os.getenv("MODEL_PATH", "Qwen/Qwen2.5-1.5B-Instruct-GGUF")
QUANTIZATION = os.getenv("MODEL_QUANTIZATION", "q4_k_m")
GPU_MEM_UTIL = float(os.getenv("VLLM_GPU_MEMORY_UTILIZATION", "0.85"))
MAX_MODEL_LEN = int(os.getenv("VLLM_MAX_MODEL_LEN", "2048"))
ENFORCE_EAGER = os.getenv("VLLM_ENFORCE_EAGER", "true").lower() == "true"

def serve():
    print(f"\n{'='*50}")
    print(f"🚀 vLLM 서버 시작 - Qwen2.5-1.5B (RTX 2060 최적화)")
    print(f"{'='*50}")
    print(f"   모델: {MODEL_PATH}")
    print(f"   양자화: {QUANTIZATION}")
    print(f"   VRAM 사용률: {GPU_MEM_UTIL * 100}%")
    print(f"   Max length: {MAX_MODEL_LEN}")
    print(f"{'='*50}\n")
    
    llm = LLM(
        model=MODEL_PATH,
        quantization=QUANTIZATION,
        tensor_parallel_size=1,
        gpu_memory_utilization=GPU_MEM_UTIL,
        max_model_len=MAX_MODEL_LEN,
        enforce_eager=ENFORCE_EAGER,
        trust_remote_code=True,
    )
    
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_PATH,
        trust_remote_code=True
    )
    
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    
    print(f"\n✅ 서버 준비 완료!")
    print(f"📡 API: http://{host}:{port}/v1/chat/completions")
    print(f"📚 문서: http://{host}:{port}/docs")
    print(f"\n🔴 중지하려면 Ctrl+C\n")
    
    from vllm.entrypoints.openai.api_server import app
    import uvicorn
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    serve()
