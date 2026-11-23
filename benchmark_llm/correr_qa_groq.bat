@echo off
REM Repite SOLO la prueba de Groq (cuando la clave de benchmark_llm\.env este corregida).
cd /d "%~dp0"
set BENCH=%cd%
for %%I in ("%cd%\..") do set PROY=%%~fI
docker run --rm --name qa-groq ^
  -e PYTHONUNBUFFERED=1 -e BENCH_SOLO=nube -e BENCH_CORRIDAS=3 -e BENCH_PAUSA=10 ^
  -e "BENCH_FILTRO=groq gpt-oss-20b,groq gpt-oss-120b" -e "BENCH_SUFIJO= [QA nov]" ^
  -v "%BENCH%":/bench -v "%PROY%\backend\app":/bench/app:ro -v "%PROY%\ejemplos_briefing":/docs:ro ^
  -w /bench mvp-ciitec-api python bench.py
echo.
echo Prueba de Groq terminada. Avisale a Claude.
pause
