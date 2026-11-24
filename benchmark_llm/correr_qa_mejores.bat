@echo off
REM QA de los mejores modelos para sintetizar (nov-2026). Claves: benchmark_llm\.env
REM Uso: correr_qa_mejores.bat            -> todos menos Claude
REM      correr_qa_mejores.bat claude     -> solo Claude (requiere ANTHROPIC_API_KEY en benchmark_llm\.env)
cd /d "%~dp0"
set BENCH=%cd%
for %%I in ("%cd%\..") do set PROY=%%~fI
set "FILTRO=deepseek v4 pro,groq gpt-oss-120b,groq qwen3.8 27b,openai gpt-5,gemini 4 argon,gemini 3.1 pro,gemini 4 hydrogen"
if /i "%1"=="claude" set "FILTRO=claude opus 5.5,claude sonnet 5.5"
:espera
docker info >nul 2>&1
if errorlevel 1 (
  timeout /t 5 /nobreak >nul
  goto espera
)
echo === Corriendo: %FILTRO% (3 corridas cada uno) ===
docker run --rm --name qa-mejores-%1x ^
  -e PYTHONUNBUFFERED=1 -e BENCH_SOLO=nube -e BENCH_CORRIDAS=3 -e BENCH_PAUSA=10 ^
  -e "BENCH_FILTRO=%FILTRO%" -e "BENCH_SUFIJO= [QA mejores modelos]" ^
  -v "%BENCH%":/bench -v "%PROY%\backend\app":/bench/app:ro -v "%PROY%\ejemplos_briefing":/docs:ro ^
  -w /bench mvp-ciitec-api python bench.py
echo.
echo Prueba terminada.
