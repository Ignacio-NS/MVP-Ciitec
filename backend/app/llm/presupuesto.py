"""
Presupuesto de contexto según el modelo (LLM_CONTEXT_TOKENS).

Los topes SYNTH_* del .env están calibrados para modelos de nube con ventanas
grandes. Un modelo local puede tener 8k–32k tokens: si se le envía más, el
servidor corta la entrada sin avisar (Ollama) o responde error. Cuando se
declara la ventana del modelo, estos helpers reparten ese presupuesto entre
entrada y salida, y parten los documentos largos para la extracción.

Con LLM_CONTEXT_TOKENS=0 (por defecto) el comportamiento es el de siempre.
"""
from __future__ import annotations

from ..config import settings
from .ajustes import Ajustes

# Español: ~3,5 caracteres por token; se usa 3,0 para quedar del lado seguro.
CHARS_POR_TOKEN = 3.0
_RESERVA_PROMPT_SINTESIS = 1500   # tokens del prompt de sistema + margen
_RESERVA_PROMPT_EXTRACCION = 600
_TOKENS_POR_HECHO = 110           # un hecho serializado en JSON, aprox.
_SOLAPE_CHARS = 400               # solape entre fragmentos para no cortar un hecho


def salida_maxima(context_tokens: int, max_output_tokens: int, fraccion: float = 0.45) -> int:
    """Tokens de salida que caben junto a la entrada en la ventana del modelo."""
    if not context_tokens:
        return max_output_tokens
    return max(512, min(max_output_tokens, int(context_tokens * fraccion)))


def limites_sintesis(aj: Ajustes) -> tuple[int, int, int]:
    """(máx. hechos, máx. caracteres de contexto, máx. caracteres por fuente)."""
    base = (settings.synth_max_hechos, settings.synth_max_contexto_chars, settings.synth_max_chars_por_fuente)
    if not aj.context_tokens:
        return base
    entrada = aj.context_tokens - salida_maxima(aj.context_tokens, aj.max_output_tokens) - _RESERVA_PROMPT_SINTESIS
    entrada = max(entrada, 1000)
    ctx_chars = int(entrada * 0.4 * CHARS_POR_TOKEN)
    hechos = int(entrada * 0.6 / _TOKENS_POR_HECHO)
    return (
        max(20, min(base[0], hechos)),
        max(2000, min(base[1], ctx_chars)),
        max(800, min(base[2], ctx_chars)),
    )


def max_chars_extraccion(aj: Ajustes) -> int:
    """Caracteres de documento que caben en una llamada de extracción (0 = sin límite)."""
    if not aj.context_tokens:
        return 0
    salida = salida_maxima(aj.context_tokens, aj.max_output_tokens, fraccion=0.4)
    return max(2000, int((aj.context_tokens - salida - _RESERVA_PROMPT_EXTRACCION) * CHARS_POR_TOKEN))


def fragmentar(texto: str, max_chars: int) -> list[str]:
    """Parte el texto en trozos <= max_chars, cortando en saltos de párrafo/línea
    cuando es posible y con un pequeño solape para no partir un hecho en dos."""
    if not max_chars or len(texto) <= max_chars:
        return [texto]
    trozos: list[str] = []
    inicio = 0
    n = len(texto)
    while inicio < n:
        fin = min(inicio + max_chars, n)
        if fin < n:
            corte = max(texto.rfind("\n\n", inicio, fin), texto.rfind("\n", inicio, fin))
            if corte > inicio + max_chars // 2:
                fin = corte
        trozos.append(texto[inicio:fin])
        if fin >= n:
            break
        inicio = max(fin - _SOLAPE_CHARS, inicio + 1)
    return trozos
