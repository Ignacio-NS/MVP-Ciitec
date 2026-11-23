@echo off
REM Segunda pasada: modelos con cuota gratuita (Gemini, Groq) usando la mejora que
REM respeta la espera que pide el servicio ante un 429 (cuota por minuto agotada).
cd /d "%~dp0"
set BENCH=%cd%
for %%I in ("%cd%\..") do set PROY=%%~fI
docker run --rm --name bench-llm2 ^
  -e LLM_MAX_OUTPUT_TOKENS=32768 -e PYTHONUNBUFFERED=1 -e BENCH_SOLO=nube -e BENCH_CORRIDAS=1 ^
  -e "BENCH_FILTRO=gemini 2.5 flash,gemini 3.8 flash,groq gpt-oss,groq qwen" -e "BENCH_SUFIJO= (respetando cuota)" ^
  -v "%BENCH%":/bench -v "%PROY%\ejemplos_briefing":/docs:ro -v "%PROY%\.env":/bench/.env:ro ^
  -w /bench mvp-ciitec-api python bench.py
echo.
echo Segunda pasada terminada. Avisale a Claude.
pause
