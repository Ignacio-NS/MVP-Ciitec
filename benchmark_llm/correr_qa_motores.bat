@echo off
REM ======================================================================
REM  QA de motores de IA: compara Gemini, DeepSeek y Groq con el codigo
REM  ACTUAL del sistema (backend\app) y los documentos de ejemplos_briefing.
REM  Mide tiempo, cifras correctas y tokens (para el costo) en 3 corridas.
REM  Claves: benchmark_llm\.env (no se muestran ni se suben a GitHub).
REM ======================================================================
cd /d "%~dp0"
set BENCH=%cd%
for %%I in ("%cd%\..") do set PROY=%%~fI
findstr /r /c:"^GEMINI_API_KEY=..*" /c:"^DEEPSEEK_API_KEY=..*" /c:"^GROQ_API_KEY=..*" .env >nul
if errorlevel 1 (
  echo Falta pegar las claves en benchmark_llm\.env . Abrelo con el Bloc de notas, pegalas y vuelve a ejecutar.
  notepad .env
  pause
  exit /b 1
)
echo === Esperando a Docker ===
:espera
docker info >nul 2>&1
if errorlevel 1 (
  timeout /t 5 /nobreak >nul
  goto espera
)
echo === Corriendo la prueba (unos 20 a 40 minutos; no suspendas el PC) ===
docker run --rm --name qa-motores-ia ^
  -e PYTHONUNBUFFERED=1 -e BENCH_SOLO=nube -e BENCH_CORRIDAS=3 -e BENCH_PAUSA=10 ^
  -e "BENCH_FILTRO=gemini 3.5 flash-lite,gemini 3.8 flash,deepseek chat,deepseek flash sin razonamiento,groq gpt-oss-20b,groq gpt-oss-120b" ^
  -e "BENCH_SUFIJO= [QA nov]" ^
  -v "%BENCH%":/bench -v "%PROY%\backend\app":/bench/app:ro -v "%PROY%\ejemplos_briefing":/docs:ro ^
  -w /bench mvp-ciitec-api python bench.py
echo.
echo Prueba terminada. Avisale a Claude para armar la comparacion.
pause
