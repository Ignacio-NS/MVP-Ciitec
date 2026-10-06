"""Contrato del SUT Adapter (Guia S4 y S5: "invoke(test_case)").

Aisla al robot del sistema bajo prueba: cualquier evaluador o reportero
trabaja solo con Observation, nunca con detalles de transporte (HTTP, CLI,
SDK...). Esto permite, por ejemplo, cambiar mas adelante a un adaptador de
CLI o de UI sin tocar evaluadores ni el agregador.
"""
from __future__ import annotations

from typing import Protocol

from ..models import Observation, TestCase


class SutAdapter(Protocol):
    """Cualquier adaptador debe poder invocar un caso y devolver una Observation."""

    def invoke(self, case: TestCase, *, repetition: int, run_id: str) -> Observation:
        ...

    def close(self) -> None:
        ...
