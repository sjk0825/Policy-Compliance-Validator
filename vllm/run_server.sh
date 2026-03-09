#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    echo "❌ 가상환경이 없습니다. 먼저 설치하세요 (README.md 참조)"
    exit 1
fi

echo "🔮 가상환경 활성화..."
source venv/bin/activate

if [ -f ".env" ]; then
    echo "📦 환경변수 로드..."
    export $(cat .env | grep -v '^#' | xargs)
fi

echo "🚀 vLLM 서버 시작..."
python serve_qwen.py
