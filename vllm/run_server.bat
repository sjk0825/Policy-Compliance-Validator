@echo off
setlocal

cd /d "%~dp0"

if not exist venv (
    echo ❌ 가상환경이 없습니다. 먼저 설치하세요
    pause
    exit /b 1
)

echo 🔮 가상환경 활성화...
call venv\Scripts\activate.bat

if exist .env (
    echo 📦 환경변수 로드...
    for /f "usebackq tokens=*" %%a in (.env) do set "%%a"
)

echo 🚀 vLLM 서버 시작...
python serve_qwen.py
