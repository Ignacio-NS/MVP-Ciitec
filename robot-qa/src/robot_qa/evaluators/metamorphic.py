"""Evaluador metamorfico (Guia S8, Anexo A de 29119-1: IA -> "pruebas metamorficas").

No existe una unica salida "correcta" para un briefing generado por LLM, pero
S8 sí define relaciones que DEBEN mantenerse frente a una variacion controlada
de la entrada. Este evaluador ejecuta la variante (usa `context.adapter`, ya
que necesita una SEGUNDA invocacion del SUT) y compara contra la Observation
base segun la relacion declarada en `case.setup["metamorphic"]["relation"]`.

Heuristicas deliberadamente simples y documentadas (no pretenden ser
"la" forma correcta): comparan el CONJUNTO de hechos citados en la
trazabilidad (Jaccard a nivel de palabra sobre el campo `evento`) o su
cardinalidad, segun lo que la relacion predice. Los umbrales son ejemplos
docentes que cada equipo debe justificar (advertencia explicita de la Guia
S7), configurables via `case.thresholds`.
"""
from __future__ import annotations

import copy
import random
import re

from ..evidence import save_observation
from ..models import Observation, Score, TestCase
from ..text_utils import normalize
from .base import EvaluatorContext

_SINONIMOS = {
    "apoyo": "asistencia", "incendio": "siniestro", "efectivos": "elementos",
    "unidad": "reparticion", "despliegue": "movilizacion", "ejecuto": "realizo",
    "rescate": "salvamento", "evaluacion": "revision", "daños": "perjuicios",
}
_MESES = {
    "01": "enero", "02": "febrero", "03": "marzo", "04": "abril", "05": "mayo", "06": "junio",
    "07": "julio", "08": "agosto", "09": "septiembre", "10": "octubre", "11": "noviembre", "12": "diciembre",
}
_FECHA_RE = re.compile(r"\b(\d{2})-(\d{2})-(\d{4})\b")


def _paraphrase(text: str) -> str:
    rng = random.Random(hash(text) & 0xFFFF)  # determinista por contenido, no por ejecucion
    out = text
    for original, sinonimo in _SINONIMOS.items():
        if rng.random() < 0.8:
            out = re.sub(rf"\b{original}\b", sinonimo, out, flags=re.IGNORECASE)
    return out


def _reformatear_fechas(text: str) -> str:
    def _sub(m: re.Match) -> str:
        dd, mm, yyyy = m.groups()
        return f"{int(dd)} de {_MESES.get(mm, mm)} de {yyyy}"
    return _FECHA_RE.sub(_sub, text)


_TRANSFORMS = {
    "paraphrase": lambda docs: [{**d, "content": _paraphrase(d["content"])} for d in docs],
    "date_format": lambda docs: [{**d, "content": _reformatear_fechas(d["content"])} for d in docs],
    "reorder": lambda docs: list(reversed(docs)),
    "duplicate_doc": lambda docs: docs + [{**docs[0], "name": f"dup_{docs[0]['name']}"}] if docs else docs,
    "remove_doc": lambda docs: docs[:-1] if len(docs) > 1 else docs,
    "add_irrelevant": lambda docs: docs + [{
        "name": "receta_no_relacionada.txt",
        "content": (
            "Receta de cocina: para preparar un pastel de tres leches se necesitan "
            "seis huevos, una taza de azucar y una taza de harina. Hornear 35 minutos "
            "a 180 grados. Este documento no contiene informacion operacional."
        ),
    }],
}


def _eventos(output: dict) -> list[str]:
    trazas = (output.get("trazabilidad") or {}).get("trazas", [])
    eventos = [t["hecho"]["evento"] for t in trazas if t.get("hecho") and t["hecho"].get("evento")]
    if eventos:
        return eventos
    return list((output.get("contenido") or {}).get("resumen_ejecutivo", []))


def _jaccard_palabras(a: list[str], b: list[str]) -> float:
    ta = set(w for s in a for w in normalize(s).split() if len(w) > 3)
    tb = set(w for s in b for w in normalize(s).split() if len(w) > 3)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class MetamorphicEvaluator:
    id = "metamorphic"

    def evaluate(self, case: TestCase, observation: Observation, context: EvaluatorContext) -> Score:
        mr = case.setup.get("metamorphic")
        if not mr:
            return Score(
                evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
                value=1.0, passed=True, detail="caso sin bloque 'metamorphic' (no aplica)",
            )
        if observation.error or not observation.output.get("contenido"):
            return Score(
                evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
                value=0.0, passed=False, detail="observacion base invalida, no se puede comparar",
            )
        if context.adapter is None:
            return Score(
                evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
                value=0.0, passed=False, detail="sin adapter en el contexto: no se pudo ejecutar la variante",
            )

        relation = mr.get("relation", "?")
        transform_name = mr.get("transform")
        transform = _TRANSFORMS.get(transform_name)
        base_docs = case.setup.get("documents", [])
        if transform is None or not base_docs:
            return Score(
                evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
                value=0.0, passed=False, detail=f"transform '{transform_name}' desconocido o sin documentos base",
            )

        variant_docs = transform(copy.deepcopy(base_docs))
        variant_case = case.model_copy(deep=True)
        variant_case.case_id = f"{case.case_id}-variant"
        variant_case.setup["documents"] = variant_docs
        variant_case.input["titulo"] = f"{case.input.get('titulo', case.case_id)} (variante {relation})"

        variant_obs = context.adapter.invoke(variant_case, repetition=observation.repetition, run_id=context.run_id)
        if context.evidence_dir is not None:
            save_observation(context.evidence_dir, variant_obs)
        if variant_obs.error or not variant_obs.output.get("contenido"):
            return Score(
                evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
                value=0.0, passed=False, detail=f"la variante fallo: {variant_obs.error or 'sin contenido'}",
                evidence_ref=variant_obs.output.get("briefing_id"),
            )

        base_ev = _eventos(observation.output)
        var_ev = _eventos(variant_obs.output)
        default_threshold = context.thresholds.get(f"metamorphic_{relation}", 0.5)
        threshold = case.thresholds.get("metamorphic", default_threshold)

        if transform_name in ("paraphrase", "reorder", "date_format"):
            value = _jaccard_palabras(base_ev, var_ev)
            passed = value >= threshold
            detail = f"{relation}: jaccard(eventos)={value:.2f} (umbral {threshold})"
        elif transform_name == "duplicate_doc":
            diff = abs(len(var_ev) - len(base_ev))
            value = 1.0 if diff == 0 else max(0.0, 1.0 - diff / max(1, len(base_ev)))
            passed = diff <= 1  # dedup por hash_sha256 deberia mantener el mismo conteo (fuentes.py)
            detail = f"{relation}: base={len(base_ev)} hechos, variante(duplicada)={len(var_ev)} hechos"
        elif transform_name == "remove_doc":
            value = 1.0 if len(var_ev) <= len(base_ev) else 0.0
            passed = value == 1.0
            detail = f"{relation}: base={len(base_ev)} hechos, variante(sin 1 doc)={len(var_ev)} hechos"
        elif transform_name == "add_irrelevant":
            base_asuntos = len((observation.output.get("contenido") or {}).get("asuntos_criticos", []))
            var_asuntos = len((variant_obs.output.get("contenido") or {}).get("asuntos_criticos", []))
            value = 1.0 if var_asuntos <= base_asuntos else 0.0
            passed = value == 1.0
            detail = f"{relation}: asuntos_criticos base={base_asuntos}, con doc irrelevante={var_asuntos}"
        else:
            value, passed, detail = 0.0, False, f"sin comparador para transform '{transform_name}'"

        return Score(
            evaluator_id=self.id, case_id=case.case_id, repetition=observation.repetition,
            value=value, passed=passed, detail=detail, evidence_ref=variant_obs.output.get("briefing_id"),
        )
