@echo off
REM Modelos locales que caben enteros en la GPU de 11 GB (ventana de 8k tokens).
cd /d "%~dp0"
set BENCH=%cd%
for %%I in ("%cd%\..") do set PROY=%%~fI
:espera
docker info >nul 2>&1
if errorlevel 1 (
  timeout /t 5 /nobreak >nul
  goto espera
)
docker network create benchnet >nul 2>&1
docker rm -f ollama-bench >nul 2>&1
set GPU=1
docker run -d --name ollama-bench --gpus all --network benchnet -e OLLAMA_CONTEXT_LENGTH=8192 -e OLLAMA_MAX_LOADED_MODELS=1 -v ollama_bench:/root/.ollama ollama/ollama
if errorlevel 1 (
  set GPU=0
  docker rm -f ollama-bench >nul 2>&1
  docker run -d --name ollama-bench --network benchnet -e OLLAMA_CONTEXT_LENGTH=8192 -e OLLAMA_MAX_LOADED_MODELS=1 -v ollama_bench:/root/.ollama ollama/ollama
)
docker run --rm --name bench-llm-local --network benchnet ^
  -e LLM_MAX_OUTPUT_TOKENS=32768 -e PYTHONUNBUFFERED=1 -e BENCH_GPU_DOCKER=%GPU% -e BENCH_SOLO=local -e BENCH_CTX_LOCAL=8192 -e "BENCH_LOCALES=qwen3:8b,gemma4:12b" ^
  -v "%BENCH%":/bench -v "%PROY%\ejemplos_briefing":/docs:ro -v "%PROY%\.env":/bench/.env:ro ^
  -w /bench mvp-ciitec-api python bench.py
docker stop ollama-bench >nul 2>&1
echo.
echo Modelos locales terminados. Avisale a Claude.
pause
