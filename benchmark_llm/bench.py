"""
Benchmark de motores de IA para el MVP-Ciitec.

Corre el MISMO pipeline del sistema (extracción por documento en paralelo,
detección de contradicciones y redacción del SITREP) con cada modelo, sobre los
documentos de ejemplos_briefing, y mide tiempos, tokens, fallas y calidad.

La calidad se mide con una lista de verificación (~40 datos que están en los
documentos y que el SITREP debe traer: cifras de personal, logística,
operaciones, alertas, asuntos críticos) y con la fidelidad de las citas
textuales de la extracción.

Se ejecuta dentro de la imagen del backend (mvp-ciitec-api) con el código del
motor de IA de la rama feat/llm-agnostico montado en /bench/app.
Resultados: /bench/resultados/*.json y resumen.jsonl. Avance: /bench/avance.log
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
import traceback
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.chdir(BASE)  # app.config lee .env desde el directorio actual

from app.llm import ajustes, ollama, presupuesto  # noqa: E402
from app.llm.ajustes import ConfigIAError  # noqa: E402
from app.llm.provider import LLMError, crear_proveedor, listar_modelos, probar_conexion  # noqa: E402
from app.pipeline import ingesta  # noqa: E402

DOCS = os.environ.get("BENCH_DOCS", "/docs")
OUT = os.path.join(BASE, "resultados")
os.makedirs(OUT, exist_ok=True)
AVANCE = os.path.join(BASE, "avance.log")
OLLAMA_URL = os.environ.get("BENCH_OLLAMA_URL", "http://ollama-bench:11434/v1")
CTX_LOCAL = int(os.environ.get("BENCH_CTX_LOCAL", "16384"))
CONCURRENCIA = 4  # igual que el worker (--concurrency=4)
PAUSA_ENTRE_CORRIDAS = int(os.environ.get("BENCH_PAUSA", "65"))  # libera cuotas por minuto


def log(msg: str) -> None:
    linea = f"{datetime.now().strftime('%H:%M:%S')}  {msg}"
    print(linea, flush=True)
    with open(AVANCE, "a", encoding="utf-8") as f:
        f.write(linea + "\n")


# ---------------------------------------------------------------------------
#  Captura del registro de uso (llm_call) para contar tokens, llamadas y fallas
# ---------------------------------------------------------------------------
_RE = re.compile(
    r"op=(?P<op>\S+) intento=(?P<intento>\d+)/\d+ latencia_s=(?P<lat>[\d.]+) "
    r"tokens_in=(?P<tin>\S+) tokens_out=(?P<tout>\S+) resultado=(?P<res>\S+)(?: error=(?P<err>\S+))?"
)


class Captura(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.llamadas: list[dict] = []
        self._mx = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        m = _RE.search(record.getMessage())
        if not m:
            return
        num = lambda v: int(v) if v and v != "None" else 0  # noqa: E731
        with self._mx:
            self.llamadas.append({
                "op": m["op"], "intento": int(m["intento"]), "latencia_s": float(m["lat"]),
                "tokens_in": num(m["tin"]), "tokens_out": num(m["tout"]),
                "resultado": m["res"], "error": m["err"],
            })

    def tomar(self) -> list[dict]:
        with self._mx:
            out, self.llamadas = self.llamadas, []
        return out


CAP = Captura()
logging.getLogger("app.llm.provider").addHandler(CAP)
logging.getLogger("app.llm.provider").setLevel(logging.INFO)
logging.basicConfig(level=logging.WARNING)


# ---------------------------------------------------------------------------
#  Documentos
# ---------------------------------------------------------------------------
_EXT_TIPO = {".pdf": "PDF", ".doc": "WORD", ".docx": "WORD", ".xls": "EXCEL", ".xlsx": "EXCEL",
             ".msg": "CORREO", ".eml": "CORREO", ".txt": "BITACORA", ".log": "BITACORA", ".csv": "BITACORA"}


def cargar_documentos() -> list[tuple[str, str]]:
    docs = []
    for nombre in sorted(os.listdir(DOCS)):
        ruta = os.path.join(DOCS, nombre)
        if not os.path.isfile(ruta):
            continue
        tipo = _EXT_TIPO.get(os.path.splitext(nombre)[1].lower(), "OTRO")
        with open(ruta, "rb") as f:
            docs.append((nombre, ingesta.extraer_texto(f.read(), tipo, nombre)))
    return docs


# ---------------------------------------------------------------------------
#  Calidad: lista de verificación (datos presentes en ejemplos_briefing)
# ---------------------------------------------------------------------------
def _n(s) -> str:
    s = unicodedata.normalize("NFKD", str(s if s is not None else "")).encode("ascii", "ignore").decode()
    return s.lower()


def _dig(v) -> str:
    return "".join(ch for ch in str(v if v is not None else "") if ch.isdigit())


def _g(c, *ruta):
    for k in ruta:
        if isinstance(c, dict):
            c = c.get(k)
        else:
            return None
    return c


def _lista(c, *ruta) -> list:
    v = _g(c, *ruta)
    return v if isinstance(v, list) else []


def _fila(lst, campo_texto, contiene):
    for r in lst:
        if isinstance(r, dict) and contiene in _n(" ".join(str(x) for x in r.values()) if campo_texto is None else r.get(campo_texto)):
            return r
    return {}


def _texto(c, *rutas) -> str:
    return _n(json.dumps([_g(c, *r) for r in rutas], ensure_ascii=False))


CHECKS = [
    # Personal (02_dotacion_personal.xlsx)
    ("PERSONAL", "OF 2840", lambda c: _dig(_g(c, "personal", "parte_fuerza_institucional", "OF")) == "2840"),
    ("PERSONAL", "SOF 9120", lambda c: _dig(_g(c, "personal", "parte_fuerza_institucional", "SOF")) == "9120"),
    ("PERSONAL", "ECP 18760", lambda c: _dig(_g(c, "personal", "parte_fuerza_institucional", "ECP")) == "18760"),
    ("PERSONAL", "Total institucional 43720", lambda c: _dig(_g(c, "personal", "parte_fuerza_institucional", "total")) == "43720"),
    ("PERSONAL", "SLC total 4200", lambda c: _dig(_g(c, "personal", "slc", "total")) == "4200"),
    ("PERSONAL", "Macrozona Norte fuerza 9800", lambda c: _dig(_fila(_lista(c, "personal", "macrozonas"), "zona", "norte").get("fuerza")) == "9800"),
    ("PERSONAL", "Fuerza de catástrofe 1500", lambda c: _dig(_g(c, "personal", "catastrofe", "fuerza")) == "1500"),
    ("PERSONAL", "Catástrofe faltan 60", lambda c: _dig(_g(c, "personal", "catastrofe", "faltan")) == "60"),
    ("PERSONAL", "UFEC 12", lambda c: _dig(_g(c, "personal", "unidades_emergencia", "ufec")) == "12"),
    ("PERSONAL", "BRIFE 4", lambda c: _dig(_g(c, "personal", "unidades_emergencia", "brife")) == "4"),
    ("PERSONAL", "PARME 6", lambda c: _dig(_g(c, "personal", "unidades_emergencia", "parme")) == "6"),
    # Logística (03_operacionalidad_logistica.xlsx / 09_operacionalidad.csv)
    ("LOGISTICA", "Total material 1740", lambda c: _dig(_g(c, "logistica", "resumen", "total")) == "1740"),
    ("LOGISTICA", "NOP total 199", lambda c: _dig(_g(c, "logistica", "resumen", "nop")) == "199"),
    ("LOGISTICA", "7 unidades en operacionalidad", lambda c: len(_lista(c, "logistica", "operacionalidad")) == 7),
    ("LOGISTICA", "JDN Biobío NOP 38", lambda c: _dig(_fila(_lista(c, "logistica", "operacionalidad"), "unidad", "biob").get("nop")) == "38"),
    # Operaciones (04_operaciones_relevos.xlsx)
    ("OPERACIONES", "2 operaciones de catástrofe", lambda c: len(_lista(c, "operaciones", "ops_catastrofe")) == 2),
    ("OPERACIONES", "Concepción: 120 efectivos", lambda c: _dig(_fila(_lista(c, "operaciones", "ops_catastrofe"), None, "concepci").get("cantidad")) == "120"),
    ("OPERACIONES", "2 relevos norte", lambda c: len(_lista(c, "operaciones", "relevos_norte")) == 2),
    ("OPERACIONES", "2 relevos sur", lambda c: len(_lista(c, "operaciones", "relevos_sur")) == 2),
    ("OPERACIONES", "Antártica dotación 24", lambda c: _dig((_lista(c, "operaciones", "ops_antartica") or [{}])[0].get("dotacion_estival") if _lista(c, "operaciones", "ops_antartica") and isinstance(_lista(c, "operaciones", "ops_antartica")[0], dict) else "") == "24"),
    ("OPERACIONES", "UNFICYP 14 efectivos", lambda c: _dig(_fila(_lista(c, "operaciones", "ops_extranjero"), None, "unficyp").get("efectivos")) == "14"),
    ("OPERACIONES", "Guardián soberano 3 JAF", lambda c: len(_lista(c, "operaciones", "guardian_soberano")) == 3),
    ("OPERACIONES", "Tarapacá planificado 5.200", lambda c: _dig(_fila(_lista(c, "operaciones", "guardian_soberano"), None, "tarapac").get("planif")) == "5200"),
    ("OPERACIONES", "Unidades en terreno 6", lambda c: _dig(_g(c, "operaciones", "unidades_terreno_kpi", "unidades_en_terreno")) == "6"),
    ("OPERACIONES", "Fuerza en terreno 540", lambda c: _dig(_g(c, "operaciones", "unidades_terreno_kpi", "fuerza_en_terreno")) == "540"),
    ("OPERACIONES", "10 UAC en traslados", lambda c: len(_lista(c, "operaciones", "traslados_uac")) == 10),
    ("OPERACIONES", "III DE: 8 unidades", lambda c: _dig(next((r.get("unidades") for r in _lista(c, "operaciones", "traslados_uac") if isinstance(r, dict) and _n(r.get("uac")).strip() == "iii de"), "")) == "8"),
    ("OPERACIONES", "Despliegue MZN 14", lambda c: _dig(_g(c, "operaciones", "despliegue_mapa", "mzn")) == "14"),
    ("OPERACIONES", "Despliegue MZS 12", lambda c: _dig(_g(c, "operaciones", "despliegue_mapa", "mzs")) == "12"),
    ("OPERACIONES", "Despliegue Antártica 1", lambda c: _dig(_g(c, "operaciones", "despliegue_mapa", "antartica")) == "1"),
    # Inteligencia (05_parte_meteorologico.txt)
    ("INTELIGENCIA", "3 alertas vigentes", lambda c: len(_lista(c, "inteligencia", "sistema_alerta")) == 3),
    ("INTELIGENCIA", "Alerta roja Biobío", lambda c: any("roja" in _n(json.dumps(r, ensure_ascii=False)) and "biob" in _n(json.dumps(r, ensure_ascii=False)) for r in _lista(c, "inteligencia", "sistema_alerta"))),
    ("INTELIGENCIA", "Análisis meteo: sistema frontal", lambda c: "frontal" in _n(_g(c, "inteligencia", "analisis_meteo"))),
    ("INTELIGENCIA", "Proyección 48 h: 30-50 mm o Ruta 5", lambda c: ("30" in _n(_g(c, "inteligencia", "proyeccion_meteo_48h")) and "50" in _n(_g(c, "inteligencia", "proyeccion_meteo_48h"))) or "ruta 5" in _n(_g(c, "inteligencia", "proyeccion_meteo_48h"))),
    # Resumen ejecutivo / asuntos críticos (07_correo, 08_bitacora)
    ("EJECUTIVO", "Resumen de 5 a 10 bullets", lambda c: 5 <= len([b for b in _lista(c, "resumen_ejecutivo") if str(b).strip()]) <= 10),
    ("EJECUTIVO", "3 o más asuntos críticos", lambda c: len(_lista(c, "asuntos_criticos")) >= 3),
    ("EJECUTIVO", "Asunto: aluvión Calama", lambda c: "calama" in _texto(c, ("asuntos_criticos",))),
    ("EJECUTIVO", "Asunto: control fronterizo Putre", lambda c: "putre" in _texto(c, ("asuntos_criticos",))),
    ("EJECUTIVO", "Asunto: sistema frontal / Biobío", lambda c: "biob" in _texto(c, ("asuntos_criticos",), ("resumen_ejecutivo",))),
    ("EJECUTIVO", "Situación con panorama", lambda c: len(_n(_g(c, "situacion", "resumen"))) > 40),
]

EVENTOS_CLAVE = [
    ("Incendio forestal Florida / 120 efectivos", lambda t: "incendio" in t and ("florida" in t or "120" in t)),
    ("Evacuación Calama / 80 personas", lambda t: "calama" in t and "80" in t),
    ("Tránsito irregular Putre", lambda t: "putre" in t and ("irregular" in t or "14" in t or "persona" in t)),
    ("Ruta 5 Sur habilitada", lambda t: "ruta 5" in t),
    ("Alerta roja Biobío", lambda t: "roja" in t and "biob" in t),
]


def evaluar(contenido: dict, hechos: list[dict], textos: dict[str, str]) -> dict:
    detalle = []
    for seccion, nombre, f in CHECKS:
        try:
            ok = bool(f(contenido))
        except Exception:  # noqa: BLE001
            ok = False
        detalle.append({"seccion": seccion, "dato": nombre, "ok": ok})
    por_seccion: dict[str, list[int]] = {}
    for d in detalle:
        por_seccion.setdefault(d["seccion"], [0, 0])
        por_seccion[d["seccion"]][1] += 1
        por_seccion[d["seccion"]][0] += int(d["ok"])
    # Citas: ¿el texto_origen aparece tal cual en algún documento?
    fuente = _n(" ".join(textos.values()))
    fuente = re.sub(r"\s+", " ", fuente)
    con_cita = [h for h in hechos if str(h.get("texto_origen") or "").strip()]
    fieles = sum(1 for h in con_cita if re.sub(r"\s+", " ", _n(h["texto_origen"])).strip()[:60] in fuente)
    todo_hechos = _n(json.dumps(hechos, ensure_ascii=False))
    eventos = [{"evento": n, "ok": bool(f(todo_hechos))} for n, f in EVENTOS_CLAVE]
    traza = contenido.get("trazabilidad") or {}
    ids = {h["id"] for h in hechos}
    traza_ok = sum(1 for v in traza.values() for i in (v or []) if str(i) in ids)
    return {
        "aciertos": sum(d["ok"] for d in detalle), "total": len(detalle),
        "pct": round(100 * sum(d["ok"] for d in detalle) / len(detalle), 1),
        "por_seccion": {k: f"{a}/{t}" for k, (a, t) in por_seccion.items()},
        "detalle": detalle,
        "hechos": len(hechos), "hechos_con_cita": len(con_cita), "citas_fieles": fieles,
        "eventos_clave": eventos, "eventos_clave_ok": sum(e["ok"] for e in eventos),
        "trazas_validas": traza_ok, "avisos": (contenido.get("generacion") or {}).get("avisos", []),
        "modo_sintesis": (contenido.get("generacion") or {}).get("modo"),
        "bullets": len(_lista(contenido, "resumen_ejecutivo")),
    }


# ---------------------------------------------------------------------------
#  Pipeline (el mismo del worker: extracción paralela -> contradicciones -> síntesis)
# ---------------------------------------------------------------------------
def _extraer(texto: str, p) -> list[dict]:
    aj = p.aj
    trozos = presupuesto.fragmentar(texto, presupuesto.max_chars_extraccion(aj))
    if len(trozos) == 1:
        return p.extraer_hechos(texto)
    vistos, crudos = set(), []
    for t in trozos:
        for h in p.extraer_hechos(t):
            k = (str(h.get("evento", "")).lower(), str(h.get("texto_origen", "")).lower())
            if k not in vistos:
                vistos.add(k)
                crudos.append(h)
    return crudos


def _fase(llamadas: list[dict]) -> dict:
    return {
        "llamadas": len(llamadas),
        "reintentos": sum(1 for x in llamadas if x["intento"] > 1),
        "fallas": sum(1 for x in llamadas if not x["resultado"].startswith("ok")),
        "errores": sorted({x["error"] for x in llamadas if x["error"]}),
        "truncadas": sum(1 for x in llamadas if x["resultado"] == "truncado"),
        "tokens_in": sum(x["tokens_in"] for x in llamadas),
        "tokens_out": sum(x["tokens_out"] for x in llamadas),
        "latencia_llamada_prom_s": round(sum(x["latencia_s"] for x in llamadas) / len(llamadas), 2) if llamadas else None,
    }


def correr(p, docs: list[tuple[str, str]]) -> dict:
    textos = dict(docs)
    res: dict = {"fases": {}}
    CAP.tomar()

    # 1) Extracción por documento, en paralelo como el worker
    t0 = time.perf_counter()
    errores_doc = {}

    def uno(item):
        nombre, texto = item
        try:
            return nombre, _extraer(texto, p)
        except Exception as e:  # noqa: BLE001 — el sistema marca la fuente en ERROR y sigue
            errores_doc[nombre] = f"{type(e).__name__}: {str(e)[:200]}"
            return nombre, []

    with ThreadPoolExecutor(CONCURRENCIA) as ex:
        por_doc = dict(ex.map(uno, docs))
    t_ext = time.perf_counter() - t0
    hechos = []
    for nombre, hs in por_doc.items():
        for h in hs:
            hechos.append({**h, "id": f"h{len(hechos)}", "fuente": nombre})
    res["fases"]["extraccion"] = {"tiempo_s": round(t_ext, 1), "errores_doc": errores_doc,
                                  "hechos_por_doc": {k: len(v) for k, v in por_doc.items()}, **_fase(CAP.tomar())}

    # 2) Contradicciones (best-effort, como el sistema)
    t0 = time.perf_counter()
    payload = [{k: h.get(k, "") for k in ("id", "evento", "ocurrido_en", "ubicacion", "responsable", "estado")} for h in hechos]
    try:
        contra = p.detectar_contradicciones(payload)
        err_contra = None
    except Exception as e:  # noqa: BLE001
        contra, err_contra = [], f"{type(e).__name__}: {str(e)[:200]}"
    res["fases"]["contradicciones"] = {"tiempo_s": round(time.perf_counter() - t0, 1), "detectadas": len(contra),
                                       "error": err_contra, **_fase(CAP.tomar())}

    # 3) Síntesis del SITREP (con los topes de contexto del modelo)
    max_hechos, max_ctx, por_fuente = presupuesto.limites_sintesis(p.aj)
    prio = {"ABIERTO": 0, "EN_CURSO": 1}
    sel = sorted(hechos, key=lambda h: prio.get(str(h.get("estado", "")).upper(), 2))[:max_hechos]
    hp = [{k: h.get(k, "") for k in ("id", "evento", "ocurrido_en", "ubicacion", "responsable", "impacto", "estado")} for h in sel]
    contexto = "\n---\n".join(f"[{n}]\n{t[:por_fuente]}" for n, t in docs if t)[:max_ctx]
    t0 = time.perf_counter()
    contenido, err_sint = None, None
    try:
        contenido = p.sintetizar_briefing(hp, {"contexto_fuentes": contexto})
    except Exception as e:  # noqa: BLE001
        err_sint = f"{type(e).__name__}: {str(e)[:300]}"
    res["fases"]["sintesis"] = {"tiempo_s": round(time.perf_counter() - t0, 1), "error": err_sint,
                                "hechos_enviados": len(hp), "contexto_chars": len(contexto), **_fase(CAP.tomar())}

    res["tiempo_total_s"] = round(sum(f["tiempo_s"] for f in res["fases"].values()), 1)
    res["sitrep_ok"] = contenido is not None
    res["calidad"] = evaluar(contenido or {}, hechos, textos)
    res["tokens_in"] = sum(f["tokens_in"] for f in res["fases"].values())
    res["tokens_out"] = sum(f["tokens_out"] for f in res["fases"].values())
    res["llamadas"] = sum(f["llamadas"] for f in res["fases"].values())
    res["sitrep"] = contenido
    res["hechos"] = hechos
    res["contradicciones"] = contra
    return res


# ---------------------------------------------------------------------------
#  Modelos
# ---------------------------------------------------------------------------
NUBE = [
    # (proveedor, modelo, etiqueta, cambios extra, corridas)
    ("gemini", "gemini-2.5-flash", "Gemini 2.5 Flash", {}, 2),
    ("gemini", "gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite", {}, 2),
    ("gemini", "gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", {}, 2),
    ("gemini", "gemini-3.8-flash", "Gemini 3.8 Flash", {}, 2),
    ("deepseek", "deepseek-chat", "DeepSeek chat (config actual)", {}, 2),
    ("deepseek", "deepseek-flash", "DeepSeek Flash (V4.1)", {}, 2),
    ("deepseek", "deepseek-flash", "DeepSeek Flash sin razonamiento", {"extra_params": {"thinking": {"type": "disabled"}}}, 2),
    ("deepseek", "deepseek-v4-pro", "DeepSeek V4 Pro", {}, 2),
    ("groq", "openai/gpt-oss-20b", "Groq gpt-oss-20b", {}, 2),
    ("groq", "openai/gpt-oss-120b", "Groq gpt-oss-120b", {}, 2),
    ("groq", "qwen/qwen3.8-27b", "Groq Qwen3.8 27B", {}, 2),
    ("groq", "llama-3.3-70b-versatile", "Groq Llama 3.3 70B (config actual)", {}, 1),
    ("github", "openai/gpt-4o", "GitHub Models gpt-4o (config actual)", {}, 1),
    # --- QA nov-2026: los mejores modelos de cada proveedor para sintetizar ---
    ("anthropic", "claude-opus-5-5", "Claude Opus 5.5", {}, 3),
    ("anthropic", "claude-sonnet-5-5", "Claude Sonnet 5.5", {}, 3),
    ("github", "openai/gpt-5", "OpenAI GPT-5 (GitHub Models gratis)", {}, 3),
    ("gemini", "gemini-4-argon", "Gemini 4 Argon", {}, 3),
    ("gemini", "gemini-3.1-pro-preview", "Gemini 3.1 Pro", {}, 3),
    ("gemini", "gemini-4-hydrogen", "Gemini 4 Hydrogen", {}, 3),
]


def modelos_locales(vram_gb: float | None) -> list[str]:
    forzados = os.environ.get("BENCH_LOCALES", "").strip()
    if forzados:
        return [m.strip() for m in forzados.split(",") if m.strip()]
    if vram_gb is None:
        return ["qwen3:8b"]  # sin GPU: solo un modelo chico (CPU)
    if vram_gb >= 22:
        return ["qwen3.8:27b", "gpt-oss:20b", "gemma4:12b", "qwen3:8b"]
    if vram_gb >= 15:
        return ["gpt-oss:20b", "qwen3:14b", "gemma4:12b", "qwen3:8b"]
    if vram_gb >= 11:
        return ["qwen3:14b", "gemma4:12b", "qwen3:8b"]
    return ["qwen3:8b", "llama3.1:8b"]


def leer_vram() -> tuple[str, float | None]:
    try:
        with open(os.path.join(BASE, "gpu.txt"), encoding="utf-8", errors="ignore") as f:
            linea = f.read().strip().splitlines()[0]
        nombre, mem = [x.strip() for x in linea.split(",")[:2]]
        return nombre, round(float(re.findall(r"[\d.]+", mem)[0]) / 1024, 1)
    except Exception:  # noqa: BLE001
        return "sin GPU NVIDIA detectada", None


def guardar(nombre: str, data: dict) -> None:
    with open(os.path.join(OUT, nombre), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, default=str)


def resumen(linea: dict) -> None:
    with open(os.path.join(OUT, "resumen.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(linea, ensure_ascii=False, default=str) + "\n")


def evaluar_modelo(proveedor, modelo, etiqueta, cambios, corridas, docs, grupo, extra_info=None):
    slug = re.sub(r"[^a-z0-9]+", "-", f"{etiqueta}".lower()).strip("-")
    base = {"etiqueta": etiqueta, "proveedor": proveedor, "modelo": modelo, "grupo": grupo,
            "cambios": cambios, **(extra_info or {})}
    try:
        aj = ajustes.construir(proveedor, {"modelo": modelo, **cambios}, origen="env")
    except ConfigIAError as e:
        log(f"  {etiqueta}: configuración inválida: {e}")
        resumen({**base, "estado": "SIN_CONFIG", "error": str(e)})
        return
    prueba = probar_conexion(aj)
    if not prueba["ok"]:
        log(f"  {etiqueta}: NO DISPONIBLE — {prueba.get('error', '')[:160]}")
        resumen({**base, "estado": "NO_DISPONIBLE", "error": prueba.get("error"), "prueba_ms": prueba["latencia_ms"]})
        return
    log(f"  {etiqueta}: conexión OK en {prueba['latencia_ms']} ms (modo síntesis {aj.sintesis_modo}, ctx {aj.context_tokens or 'sin tope'})")
    for n in range(1, corridas + 1):
        p = crear_proveedor(aj)
        t0 = time.time()
        try:
            r = correr(p, docs)
        except Exception as e:  # noqa: BLE001
            log(f"  {etiqueta} corrida {n}: ERROR {type(e).__name__}: {e}")
            resumen({**base, "corrida": n, "estado": "ERROR", "error": traceback.format_exc()[-800:]})
            continue
        r.update(base, corrida=n, inicio=datetime.fromtimestamp(t0, timezone.utc).isoformat(), prueba_ms=prueba["latencia_ms"],
                 max_output_tokens=aj.max_output_tokens, context_tokens=aj.context_tokens, sintesis_modo=aj.sintesis_modo)
        guardar(f"{slug}__corrida{n}.json", r)
        q = r["calidad"]
        linea = {**base, "corrida": n, "estado": "OK" if r["sitrep_ok"] else "SIN_SITREP",
                 "tiempo_total_s": r["tiempo_total_s"],
                 "t_extraccion_s": r["fases"]["extraccion"]["tiempo_s"],
                 "t_contradicciones_s": r["fases"]["contradicciones"]["tiempo_s"],
                 "t_sintesis_s": r["fases"]["sintesis"]["tiempo_s"],
                 "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"], "llamadas": r["llamadas"],
                 "reintentos": sum(f["reintentos"] for f in r["fases"].values()),
                 "fallas": sum(f["fallas"] for f in r["fases"].values()),
                 "errores": sorted({e for f in r["fases"].values() for e in f["errores"]}),
                 "errores_doc": r["fases"]["extraccion"]["errores_doc"],
                 "error_sintesis": r["fases"]["sintesis"]["error"],
                 "calidad_pct": q["pct"], "aciertos": f"{q['aciertos']}/{q['total']}", "por_seccion": q["por_seccion"],
                 "hechos": q["hechos"], "citas_fieles": f"{q['citas_fieles']}/{q['hechos_con_cita']}",
                 "eventos_clave": f"{q['eventos_clave_ok']}/{len(EVENTOS_CLAVE)}", "trazas_validas": q["trazas_validas"],
                 "modo_sintesis": q["modo_sintesis"], "avisos": len(q["avisos"]), "contradicciones": len(r["contradicciones"])}
        resumen(linea)
        log(f"  {etiqueta} corrida {n}: {linea['estado']} {r['tiempo_total_s']} s · calidad {q['pct']}% "
            f"({q['aciertos']}/{q['total']}) · tokens {r['tokens_in']}/{r['tokens_out']} · fallas {linea['fallas']}")
        if PAUSA_ENTRE_CORRIDAS and grupo == "nube":
            time.sleep(PAUSA_ENTRE_CORRIDAS)


def main() -> None:
    docs = cargar_documentos()
    guardar("documentos.json", {n: {"chars": len(t), "texto": t} for n, t in docs})
    log(f"Documentos: {len(docs)} ({sum(len(t) for _, t in docs)} caracteres)")
    solo = os.environ.get("BENCH_SOLO", "")  # "nube" | "local" | ""

    if solo in ("", "nube"):
        log("=== Modelos en la nube ===")
        for prov in ("gemini", "deepseek", "groq", "anthropic", "github"):
            try:
                aj = ajustes.construir(prov, {"modelo": "-"}, origen="env")
                lista = listar_modelos(aj)
                guardar(f"catalogo_{prov}.json", lista)
                log(f"  catálogo {prov}: {len(lista)} modelos")
            except Exception as e:  # noqa: BLE001
                log(f"  catálogo {prov}: no disponible ({str(e)[:120]})")
        filtro = [f.strip().lower() for f in os.environ.get("BENCH_FILTRO", "").split(",") if f.strip()]
        sufijo = os.environ.get("BENCH_SUFIJO", "")
        corridas_forzadas = int(os.environ.get("BENCH_CORRIDAS", "0") or 0)
        for prov, modelo, etiqueta, cambios, corridas in NUBE:
            if filtro and not any(f in etiqueta.lower() for f in filtro):
                continue
            evaluar_modelo(prov, modelo, etiqueta + sufijo, cambios, corridas_forzadas or corridas, docs, "nube")

    if solo in ("", "local"):
        gpu, vram = leer_vram()
        modo = os.environ.get("BENCH_GPU_DOCKER", "?")
        log(f"=== Modelos locales (GPU: {gpu}, VRAM {vram} GB, Docker con GPU: {modo}) ===")
        for modelo in modelos_locales(vram if modo == "1" else None):
            log(f"  descargando {modelo} …")
            t0 = time.time()
            ultimo = {"t": 0}

            def av(m):
                if time.time() - ultimo["t"] > 30:
                    ultimo["t"] = time.time()
                    log(f"    {modelo}: {m.get('estado')} {m.get('pct') if m.get('pct') is not None else ''}%")
            err = None
            for intento in range(1, 7):  # el registro de Ollama a veces responde 503: reintentar (reanuda)
                try:
                    ollama.descargar(OLLAMA_URL, modelo, av)
                    err = None
                    break
                except Exception as e:  # noqa: BLE001
                    err = e
                    log(f"    {modelo}: intento {intento} de descarga falló ({str(e)[:120]}); reintento en 30 s")
                    time.sleep(30)
            if err is not None:
                e = err
                log(f"  {modelo}: no se pudo descargar ({str(e)[:160]})")
                resumen({"etiqueta": f"Local {modelo}", "proveedor": "local", "modelo": modelo, "grupo": "local",
                         "estado": "NO_DESCARGADO", "error": str(e)[:300]})
                continue
            descarga_s = round(time.time() - t0)
            log(f"  {modelo} descargado en {descarga_s} s")
            evaluar_modelo("local", modelo, f"Local {modelo}",
                           {"base_url": OLLAMA_URL, "context_tokens": CTX_LOCAL, "timeout_s": 600},
                           1, docs, "local", {"gpu": gpu, "vram_gb": vram, "gpu_docker": modo, "descarga_s": descarga_s})
    log("FIN")


if __name__ == "__main__":
    main()
