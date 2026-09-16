"""Evaluador determinista de nivel 1 (Guia S7): valida forma y campos obligatorios.

Valida `observation.output["contenido"]` contra el MISMO `BriefingOut` que usa
el backend (`sut_contracts.BriefingOut`), y exige que exista al menos un
bullet en el resumen ejecutivo -- una respuesta "vacia" (schema valido pero
sin contenido real) no debe contar como exito.
"""
from __future__ import annotations

from pydantic import ValidationError

from ..models import Observation, Score, TestCase
from ..sut_contracts import BriefingOut
from .base import EvaluatorContext


class SchemaEvaluator:
    id = "schema"

    def evaluate(self, case: TestCase, observation: Observation, context: EvaluatorContext) -> Score:
        if observation.error:
            return Score(
                evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
                value=0.0, passed=False, critical=True, detail=f"error de transporte: {observation.error}",
            )
        contenido = observation.output.get("contenido")
        if not contenido:
            return Score(
                evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
                value=0.0, passed=False, critical=True,
                detail="sin 'contenido' en la respuesta (timeout o generacion vacia)",
            )
        try:
            parsed = BriefingOut.model_validate(contenido)
        except ValidationError as exc:
            return Score(
                evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
                value=0.0, passed=False, critical=True, detail=f"esquema invalido: {exc.error_count()} errores",
            )
        n_bullets = len(parsed.resumen_ejecutivo)
        ok = n_bullets >= 1
        return Score(
            evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
            value=1.0 if ok else 0.0, passed=ok,
            detail=f"{n_bullets} bullets en resumen_ejecutivo" if ok else "resumen_ejecutivo vacio",
        )
