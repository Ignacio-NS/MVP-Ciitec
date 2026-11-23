@echo off
REM ======================================================================
REM  Benchmark de motores de IA del MVP-Ciitec.
REM  Prueba cada modelo con los documentos de ejemplos_briefing usando el
REM  mismo pipeline del sistema. Usa las claves del .env del proyecto (no
REM  las muestra). Los modelos locales corren en Ollama dentro de Docker.
REM  Resultados: benchmark_llm\resultados  -  Avance: benchmark_llm\avance.log
REM ======================================================================
cd /d "%~dp0"
set BENCH=%cd%
for %%I in ("%cd%\..") do set PROY=%%~fI
echo.
echo === 1/4 Revisando la GPU ===
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader > gpu.txt 2>nul
type gpu.txt
powershell -NoProfile -Command "Get-PSDrive C | Select-Object @{n='LibreGB';e={[math]::Round($_.Free/1GB,1)}} | Format-List" > disco.txt
type disco.txt

echo === 2/4 Esperando a Docker ===
:espera
docker info >nul 2>&1
if errorlevel 1 (
  timeout /t 5 /nobreak >nul
  goto espera
)

echo === 3/4 Levantando Ollama para los modelos locales ===
docker network create benchnet >nul 2>&1
docker rm -f ollama-bench >nul 2>&1
set GPU=1
docker run -d --name ollama-bench --gpus all --network benchnet -e OLLAMA_CONTEXT_LENGTH=16384 -e OLLAMA_MAX_LOADED_MODELS=1 -v ollama_bench:/root/.ollama ollama/ollama
if errorlevel 1 (
  echo Docker no tiene acceso a la GPU: los modelos locales correran en CPU.
  set GPU=0
  docker rm -f ollama-bench >nul 2>&1
  docker run -d --name ollama-bench --network benchnet -e OLLAMA_CONTEXT_LENGTH=16384 -e OLLAMA_MAX_LOADED_MODELS=1 -v ollama_bench:/root/.ollama ollama/ollama
)

echo === 4/4 Corriendo el benchmark (puede tardar 1 a 2 horas; no apagues ni suspendas el PC) ===
docker run --rm --name bench-llm --network benchnet ^
  -e LLM_MAX_OUTPUT_TOKENS=32768 -e PYTHONUNBUFFERED=1 -e BENCH_GPU_DOCKER=%GPU% ^
  -v "%BENCH%":/bench -v "%PROY%\ejemplos_briefing":/docs:ro -v "%PROY%\.env":/bench/.env:ro ^
  -w /bench mvp-ciitec-api python bench.py

docker stop ollama-bench >nul 2>&1
echo.
echo Benchmark terminado. Avisale a Claude.
pause
