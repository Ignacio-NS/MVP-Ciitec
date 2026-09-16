"""Evaluador de nivel 5 (Guia S7): "evaluacion por modelo", con juez independiente.

`case.expected`:
  - `rubric_prompt`: nombre del archivo en `rubrics/` (default "calidad_semantica").
  - `rubric_criteria`: el criterio especifico que el juez debe verificar en este caso.
  - `rubric_field`: que parte de `contenido` mirar (default: resumen_ejecutivo + situacion).

El puntaje 1-5 se normaliza a 0..1 (`value = score/5`). El detalle SIEMPRE incluye
la justificacion del juez, para que la muestra de calibracion (evaluador
`human_review`) pueda compararse contra ella.
"""
from __future__ import annotations

import json

from ..models import Observation, Score, TestCase
from .base import EvaluatorContext


class RubricLlmEvaluator:
    id = "rubric_llm"

    def evaluate(self, case: TestCase, observation: Observation, context: EvaluatorContext) -> Score:
        if context.judge is None:
            return Score(
                evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
                value=0.0, passed=False, detail="juez LLM no configurado (falta GEMINI_API_KEY)",
            )
        contenido = observation.output.get("contenido")
        if not contenido:
            return Score(
                evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
                value=0.0, passed=False, detail="sin contenido para evaluar",
            )
        criterio = case.expected.get(
            "rubric_criteria",
            "El resumen ejecutivo es claro, preciso y respalda cada afirmacion en los hechos disponibles.",
        )
        campo = case.expected.get("rubric_field", "resumen_ejecutivo")
        salida = contenido.get(campo, contenido.get("resumen_ejecutivo", []))
        salida_txt = json.dumps(salida, ensure_ascii=False, indent=2)
        prompt_id = case.expected.get("rubric_prompt", "calidad_semantica")

        try:
            veredicto = context.judge(prompt_id, {"criterio": criterio, "salida": salida_txt})
        except Exception as exc:  # falla de red/parseo del juez: no derrumbar la campana
            return Score(
                evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
                value=0.0, passed=False, detail=f"juez fallo: {exc}",
            )

        score5 = veredicto.get("score", 1)
        value = score5 / 5.0
        threshold = case.thresholds.get("rubric_llm", 0.6)  # 3/5 por defecto
        passed = value >= threshold
        return Score(
            evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
            value=value, passed=passed,
            detail=f"juez={score5}/5: {veredicto.get('reason', '')}",
        )
