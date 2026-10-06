"""
Modelos Pydantic para validar la salida del LLM (Groq).

Groq (Llama 3.3) NO garantiza JSON-schema estricto como OpenAI, así que la
salida se valida aquí con Pydantic y se rechaza/reintenta si no cumple. Los
modelos son permisivos en lo accesorio (extra="ignore") pero exigen la
estructura mínima que el resto del sistema necesita.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

_ESTADOS = {"ABIERTO", "EN_CURSO", "CERRADO"}


# ---------- Extracción de hechos (RF-003) ----------
class HechoLLM(BaseModel):
    model_config = ConfigDict(extra="ignore")
    evento: str
    ocurrido_en: str = ""
    ubicacion: str = ""
    responsable: str = ""
    impacto: str = ""
    estado: str = "ABIERTO"
    texto_origen: str = ""

    @field_validator("estado", mode="before")
    @classmethod
    def _norm_estado(cls, v):
        # El LLM a veces devuelve "" u otros valores; se normaliza al enum válido.
        s = str(v or "").strip().upper().replace(" ", "_")
        return s if s in _ESTADOS else "ABIERTO"

    @field_validator("evento", mode="before")
    @classmethod
    def _evento_str(cls, v):
        return str(v or "").strip()


class HechosResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    hechos: list[HechoLLM] = Field(default_factory=list)


# ---------- Detección de contradicciones (RF-005) ----------
class Contradiccion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    descripcion: str
    hechos_involucrados: list[str] = Field(default_factory=list)
    severidad: int = 2


class ContradiccionesResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    contradicciones: list[Contradiccion] = Field(default_factory=list)


# ---------- Síntesis del briefing institucional (RF-004) ----------
# Estructura fiel a la plantilla de 6 páginas. Todo es permisivo: lo que el
# LLM no pueda completar queda vacío y la plantilla lo muestra como "-.-".
class AsuntoCritico(BaseModel):
    model_config = ConfigDict(extra="allow")
    asunto: str = ""
    impacto: str = ""
    responsable: str = ""


# ---------- Hojas adicionales configurables por el usuario ----------
TIPOS_BLOQUE = {"texto", "vinetas", "tabla", "kpis", "grafico", "imagen"}


class BloqueHoja(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tipo: str = "texto"
    titulo: str = ""
    texto: str = ""
    items: list = Field(default_factory=list)       # vinetas: [str] · kpis: [{etiqueta, valor}]
    columnas: list[str] = Field(default_factory=list)
    filas: list[list] = Field(default_factory=list)
    estilo: str = "barras"                           # grafico: barras | barras_h | dona
    categorias: list[str] = Field(default_factory=list)
    valores: list = Field(default_factory=list)
    objeto: str = ""                                 # imagen: clave en MinIO
    pie: str = ""

    @field_validator("tipo", mode="before")
    @classmethod
    def _tipo_ok(cls, v):
        s = str(v or "texto").strip().lower()
        return s if s in TIPOS_BLOQUE else "texto"


class DocumentoHoja(BaseModel):
    """Documento adjunto a una hoja: de él se extrae la información para completarla."""
    model_config = ConfigDict(extra="ignore")
    nombre: str = ""
    objeto: str = ""                                 # clave en MinIO (hojas/<briefing>/docs/...)
    tipo: str = ""


class HojaAdicional(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = ""
    seccion: str = "INFORMACIÓN ADICIONAL"
    titulo: str = ""
    despues_de: int | None = None                    # 0..5 = tras la página N+1; None = al final
    instrucciones_ia: str = ""
    documentos: list[DocumentoHoja] = Field(default_factory=list)
    bloques: list[BloqueHoja] = Field(default_factory=list)


class HojaCompletada(BaseModel):
    model_config = ConfigDict(extra="ignore")
    titulo: str = ""                                 # solo si la hoja no traía título
    bloques: list[BloqueHoja] = Field(default_factory=list)
    trazabilidad: dict[str, list[str]] = Field(default_factory=dict)


class BriefingOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Página portada / resumen ejecutivo (RF-004)
    resumen_ejecutivo: list[str] = Field(default_factory=list)  # 5–10 bullets
    asuntos_criticos: list[AsuntoCritico] = Field(default_factory=list)
    proyeccion_24_72h: str = ""

    # Resumen por sección — SITUACIÓN (RF-004). Narrativa del panorama operacional
    # general; las demás secciones (logística/personal/incidentes/meteorología)
    # viven en sus bloques institucionales.
    situacion: dict = Field(default_factory=dict)  # { "resumen": str, "aspectos": [str] }

    # Página PERSONAL
    personal: dict = Field(default_factory=dict)
    # Página INTELIGENCIA
    inteligencia: dict = Field(default_factory=dict)
    # Páginas OPERACIONES
    operaciones: dict = Field(default_factory=dict)
    # Página LOGÍSTICA
    logistica: dict = Field(default_factory=dict)

    # Hojas extra que agrega el usuario desde el editor (no las genera la síntesis)
    hojas_adicionales: list[HojaAdicional] = Field(default_factory=list)

    # Trazabilidad bullet -> ids de hechos (RF-006)
    trazabilidad: dict[str, list[str]] = Field(default_factory=dict)
