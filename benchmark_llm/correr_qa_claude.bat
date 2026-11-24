@echo off
REM QA de Claude (Opus 5.5 y Sonnet 5.5). Clave: ANTHROPIC_API_KEY en benchmark_llm\.env
cd /d "%~dp0"
set BENCH=%cd%
for %%I in ("%cd%\..") do set PROY=%%~fI
docker run --rm --name qa-claude ^
  -e PYTHONUNBUFFERED=1 -e BENCH_SOLO=nube -e BENCH_CORRIDAS=3 -e BENCH_PAUSA=10 ^
  -e "BENCH_FILTRO=claude opus 5.5,claude sonnet 5.5" -e "BENCH_SUFIJO= [QA mejores modelos]" ^
  -v "%BENCH%":/bench -v "%PROY%\backend\app":/bench/app:ro -v "%PROY%\ejemplos_briefing":/docs:ro ^
  -w /bench mvp-ciitec-api python bench.py
echo.
echo Prueba de Claude terminada.
