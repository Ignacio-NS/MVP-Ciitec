"""
Resultados de las pruebas de QA de motores de IA, para verlos en la interfaz.

Las pruebas (benchmark_llm/bench.py) generan el SITREP con el pipeline real del
sistema, una vez por motor y corrida, y guardan cada corrida como
`<modelo>__corridaN.json` en una carpeta de resultados. Ese directorio se monta
SOLO LECTURA en el contenedor de la API (QA_RESULTADOS_DIR); este módulo lo lee,
calcula métricas comparables (tiempo, calidad, exactitud de cifras, costo) y lo
entrega a la pantalla "Pruebas QA". No escribe nada ni toca la base de datos.

Los SITREP de estas pruebas se hicieron con documentos FICTICIOS (ejemplos_briefing).
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from statistics import mean
from typing import Any

from .config import settings

# Precios de referencia de cada API (US$ por millón de tokens: entrada, salida), tomados
# de las páginas oficiales en oct-2026, y tipo de cambio usado en el informe de benchmark.
# Sirven para ESTIMAR el costo por SITREP; la facturación real está en la consola de cada proveedor.
PRECIOS_USD_MTOK: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.8-flash": (0.75, 3.75),
    "deepseek-chat": (0.30, 1.20),
    "deepseek-flash": (0.30, 1.20),
    "deepseek-v4-pro": (1.32, 3.96),
    "openai/gpt-oss-20b": (0.075, 0.30),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "qwen/qwen3.8-27b": (0.80, 4.00),
}
USD_CLP = 984.09
PRECIOS_FECHA = "oct-2026"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,120}__corrida\d{1,3}$")
_LOTE_RE = re.compile(r"\s*\[([^\]]+)\]\s*$")
_MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def directorio() -> str:
    return settings.qa_resultados_dir


def _leer_json(ruta: str) -> Any:
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def _lote_y_nombre(etiqueta: str, inicio: str | None) -> tuple[str, str]:
    """'Gemini 3.5 Flash-Lite [QA nov]' -> ('QA nov', 'Gemini 3.5 Flash-Lite').
    Sin corchetes: el lote es el benchmark del mes en que corrió."""
    nombre = etiqueta
    m = _LOTE_RE.search(nombre)
    if m:
        lote = m.group(1)
        nombre = nombre[: m.start()]
    else:
        lote = "Benchmark"
        if inicio and len(inicio) >= 7 and inicio[5:7].isdigit():
            lote = f"Benchmark {_MESES[int(inicio[5:7]) - 1]}-{inicio[:4]}"
    nombre = nombre.replace(" (respetando cuota)", "").replace(" (config actual)", "").strip()
    return lote, nombre


def costo_clp(modelo: str, tokens_in: int | None, tokens_out: int | None) -> float | None:
    precio = PRECIOS_USD_MTOK.get(modelo)
    if precio is None or tokens_in is None or tokens_out is None:
        return None
    return round((tokens_in * precio[0] + tokens_out * precio[1]) / 1e6 * USD_CLP, 1)


# ---------------------------------------------------------------------------
#  Exactitud de cifras: cada número del SITREP debe estar en los documentos fuente
# ---------------------------------------------------------------------------
_NUM_RE = re.compile(r"\d[\d.,]*\d|\d")


def _formas(n: str) -> set[str]:
    n = n.strip(".,")
    formas = {n, n.replace(".", ""), n.replace(".", "").replace(",", ".")}
    if re.fullmatch(r"\d{1,3}(,\d{3})+", n):  # miles con coma (estilo inglés): 1,440 = 1.440
        formas.add(n.replace(",", ""))
    return formas


@lru_cache(maxsize=4)
def _cifras_fuente(ruta_docs: str, mtime: float) -> frozenset[str]:
    docs = _leer_json(ruta_docs)
    texto = " ".join(v.get("texto", "") for v in docs.values())
    out: set[str] = set()
    for m in _NUM_RE.findall(texto):
        out |= _formas(m)
    return frozenset(out)


def _textos(obj: Any, clave: str = "") -> list[str]:
    if clave in ("trazabilidad", "generacion"):
        return []
    if isinstance(obj, dict):
        return [t for k, v in obj.items() for t in _textos(v, k)]
    if isinstance(obj, list):
        return [t for v in obj for t in _textos(v, clave)]
    if obj is None:
        return []
    return [str(obj)]


def exactitud(sitrep: dict[str, Any] | None) -> dict[str, Any] | None:
    """% de cifras del SITREP (2+ dígitos, sin años) que aparecen en los documentos."""
    ruta = os.path.join(directorio(), "documentos.json")
    if not sitrep or not os.path.exists(ruta):
        return None
    fuente = _cifras_fuente(ruta, os.path.getmtime(ruta))
    total, faltan = 0, []
    for texto in _textos(sitrep):
        for n in _NUM_RE.findall(texto):
            n = n.strip(".,")
            if len(re.sub(r"\D", "", n)) < 2 or re.fullmatch(r"20\d\d", n):
                continue
            total += 1
            if not (_formas(n) & fuente):
                faltan.append(n)
    pct = round(100 * (total - len(faltan)) / total, 1) if total else None
    return {"cifras": total, "pct": pct, "no_encontradas": sorted(set(faltan))[:30]}


# ---------------------------------------------------------------------------
#  Lectura de corridas
# ---------------------------------------------------------------------------
def _fila(id_: str, d: dict[str, Any]) -> dict[str, Any]:
    lote, nombre = _lote_y_nombre(d.get("etiqueta", id_), d.get("inicio"))
    cal = d.get("calidad") or {}
    ex = exactitud(d.get("sitrep")) if d.get("sitrep_ok") else None
    fases = d.get("fases") or {}
    gen = (d.get("sitrep") or {}).get("generacion") or {}
    return {
        "id": id_,
        "lote": lote,
        "motor": nombre,
        "proveedor": d.get("proveedor"),
        "modelo": d.get("modelo"),
        "corrida": d.get("corrida"),
        "inicio": d.get("inicio"),
        "estado": "OK" if d.get("sitrep_ok") else "ERROR",
        "tiempo_s": d.get("tiempo_total_s"),
        "t_extraccion_s": (fases.get("extraccion") or {}).get("tiempo_s"),
        "t_contradicciones_s": (fases.get("contradicciones") or {}).get("tiempo_s"),
        "t_sintesis_s": (fases.get("sintesis") or {}).get("tiempo_s"),
        "calidad_pct": cal.get("pct"),
        "calidad": f"{cal.get('aciertos', 0)}/{cal.get('total', 0)}" if cal else None,
        "exactitud_pct": ex["pct"] if ex else None,
        "cifras": ex["cifras"] if ex else None,
        "tokens_in": d.get("tokens_in"),
        "tokens_out": d.get("tokens_out"),
        "costo_clp": costo_clp(d.get("modelo", ""), d.get("tokens_in"), d.get("tokens_out")),
        "hechos": len(d.get("hechos") or []),
        "contradicciones": len(d.get("contradicciones") or []),
        "modo_sintesis": gen.get("modo") or cal.get("modo_sintesis"),
        "avisos": len(gen.get("avisos") or []),
        "error": _primer_error(d),
    }


def _primer_error(d: dict[str, Any]) -> str | None:
    """Motivo de una corrida fallida: el error general o el primero de alguna fase."""
    if d.get("sitrep_ok"):
        return None
    if d.get("error"):
        return str(d["error"])[:300]
    for fase in (d.get("fases") or {}).values():
        if not isinstance(fase, dict):
            continue
        if fase.get("error"):
            return str(fase["error"])[:300]
        for e in (fase.get("errores_doc") or {}).values():
            return str(e)[:300]
        for e in fase.get("errores") or []:
            return str(e)[:300]
    return "La corrida no produjo un SITREP válido."


def _no_disponibles() -> list[dict[str, Any]]:
    """Motores que no se pudieron probar (clave inválida, modelo retirado…), desde resumen.jsonl."""
    ruta = os.path.join(directorio(), "resumen.jsonl")
    if not os.path.exists(ruta):
        return []
    ultimos: dict[str, dict[str, Any]] = {}
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            try:
                r = json.loads(linea)
            except json.JSONDecodeError:
                continue
            if r.get("estado") in ("NO_DISPONIBLE", "NO_DESCARGADO", "CONFIG_INVALIDA"):
                ultimos[r.get("etiqueta", "")] = r
    out = []
    for et, r in ultimos.items():
        lote, nombre = _lote_y_nombre(et, None)
        out.append({"lote": lote, "motor": nombre, "proveedor": r.get("proveedor"), "modelo": r.get("modelo"),
                    "estado": r.get("estado"), "error": (r.get("error") or "")[:300]})
    return out


def listar() -> dict[str, Any]:
    base = directorio()
    if not os.path.isdir(base):
        return {"disponible": False, "carpeta": base, "corridas": [], "resumen": [], "no_disponibles": [], "lotes": []}
    corridas = []
    for nombre in sorted(os.listdir(base)):
        if not nombre.endswith(".json"):
            continue
        id_ = nombre[:-5]
        if not _ID_RE.match(id_):
            continue
        try:
            corridas.append(_fila(id_, _leer_json(os.path.join(base, nombre))))
        except (OSError, ValueError):
            continue
    nd = _no_disponibles()
    # resumen.jsonl no guarda fecha: lo que no trae lote va al benchmark más reciente.
    benchs = sorted({c["lote"] for c in corridas if c["lote"].startswith("Benchmark ")},
                    key=lambda l: max(c["inicio"] or "" for c in corridas if c["lote"] == l))
    for n in nd:
        if n["lote"] == "Benchmark" and benchs:
            n["lote"] = benchs[-1]
    # Un motor que al final sí corrió en ese lote no se lista como no disponible; sin duplicados.
    corrio = {(c["lote"], c["motor"]) for c in corridas}
    vistos: dict[tuple[str, str], dict[str, Any]] = {}
    for n in nd:
        if (n["lote"], n["motor"]) not in corrio:
            vistos[(n["lote"], n["motor"])] = n
    nd = list(vistos.values())

    grupos: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for c in corridas:
        grupos.setdefault((c["lote"], c["motor"]), []).append(c)
    resumen = []
    for (lote, motor), cs in grupos.items():
        ok = [c for c in cs if c["estado"] == "OK"]
        prom = lambda k: round(mean(v for v in (c[k] for c in ok) if v is not None), 1) if any(c[k] is not None for c in ok) else None  # noqa: E731
        resumen.append({
            "lote": lote, "motor": motor, "proveedor": cs[0]["proveedor"], "modelo": cs[0]["modelo"],
            "corridas": len(cs), "exitosas": len(ok),
            "tiempo_s": prom("tiempo_s"),
            "tiempo_min_s": min((c["tiempo_s"] for c in ok if c["tiempo_s"] is not None), default=None),
            "tiempo_max_s": max((c["tiempo_s"] for c in ok if c["tiempo_s"] is not None), default=None),
            "calidad_pct": prom("calidad_pct"), "exactitud_pct": prom("exactitud_pct"),
            "cifras": prom("cifras"), "costo_clp": prom("costo_clp"),
            "contradicciones": prom("contradicciones"), "hechos": prom("hechos"),
        })
    lotes = sorted({c["lote"] for c in corridas} | {n["lote"] for n in nd},
                   key=lambda l: max((c["inicio"] or "" for c in corridas if c["lote"] == l), default=""), reverse=True)
    return {
        "disponible": True, "lotes": lotes, "corridas": corridas, "resumen": resumen, "no_disponibles": nd,
        "precios": {"fecha": PRECIOS_FECHA, "usd_clp": USD_CLP},
    }


def detalle(id_: str) -> dict[str, Any] | None:
    if not _ID_RE.match(id_ or ""):
        return None
    ruta = os.path.join(directorio(), f"{id_}.json")
    if not os.path.isfile(ruta):
        return None
    d = _leer_json(ruta)
    fila = _fila(id_, d)
    return {
        **fila,
        "sitrep": d.get("sitrep"),
        "hechos_detalle": d.get("hechos") or [],
        "contradicciones_detalle": d.get("contradicciones") or [],
        "calidad_detalle": (d.get("calidad") or {}).get("detalle") or [],
        "calidad_por_seccion": (d.get("calidad") or {}).get("por_seccion") or {},
        "hechos_por_doc": ((d.get("fases") or {}).get("extraccion") or {}).get("hechos_por_doc") or {},
        "exactitud_detalle": exactitud(d.get("sitrep")) if d.get("sitrep_ok") else None,
        "avisos_detalle": ((d.get("sitrep") or {}).get("generacion") or {}).get("avisos") or [],
    }
