"""Cliente del "juez" LLM (Guia S7, nivel 5: evaluacion por modelo).

Usa el MISMO Gemini que el SUT (misma API key y modelo, via el endpoint
OpenAI-compatible que ya usa `backend/app/llm/provider.py`), pero el robot
llama al modelo por su cuenta: el juez debe ser independiente del pipeline
que genero la respuesta que esta evaluando.

El prompt vive versionado en archivos de texto bajo `rubrics/` (Guia S7:
"exigir prompt versionado, justificacion y calibracion"), nunca hardcodeado
en Python, para que un cambio de rubrica quede en el historial de git y
pueda citarse en el informe final.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .config import GeminiConfig

_JSON_INSTRUCCION = (
    "\n\nResponde SOLO con un JSON valido (sin markdown, sin preambulo) con esta forma exacta:\n"
    '{"score": <entero 1 a 5>, "reason": "justificacion breve en espanol"}'
)

JudgeFn = Callable[[str, dict], dict]


def make_judge(gemini: GeminiConfig, rubrics_dir: Path) -> JudgeFn | None:
    """Devuelve una funcion (prompt_id, variables) -> {"score":int,"reason":str}, o None si no hay API key."""
    if not gemini.available:
        return None
    from openai import OpenAI  # import perezoso: solo si de verdad se usa el juez

    client = OpenAI(base_url=gemini.base_url, api_key=gemini.api_key)

    def _judge(prompt_id: str, variables: dict) -> dict:
        template_path = rubrics_dir / f"{prompt_id}.md"
        if not template_path.is_file():
            raise FileNotFoundError(f"rubrica no encontrada: {template_path}")
        template = template_path.read_text(encoding="utf-8")
        prompt = template.format(**variables) + _JSON_INSTRUCCION
        resp = client.chat.completions.create(
            model=gemini.model,
            messages=[
                {"role": "system", "content": "Eres un evaluador de calidad de QA, objetivo y estricto."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        raw = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"score": 1, "reason": f"respuesta del juez no parseable: {raw[:200]}"}
        data["score"] = max(1, min(5, int(data.get("score", 1))))
        data.setdefault("reason", "")
        return data

    return _judge
