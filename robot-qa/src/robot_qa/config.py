"""Configuracion del robot: reusa el MISMO `.env` del SUT (una sola fuente de
verdad para credenciales) y la combina con `robot-qa/config/*.yaml`.

No se agrega python-dotenv como dependencia nueva: el archivo `.env` de este
proyecto es `KEY=VALUE` por linea, sin interpolacion ni comillas complejas,
asi que un parser de 10 lineas basta y evita una dependencia mas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]  # raiz del monorepo MVP-Ciitec
ROBOT_QA_DIR = ROOT / "robot-qa"

_USUARIOS_DEMO = ["operaciones", "analista", "comandante", "auditor", "admin"]


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


@dataclass
class GeminiConfig:
    api_key: str = ""
    base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    model: str = "gemini-2.5-flash"

    @property
    def available(self) -> bool:
        return bool(self.api_key)


@dataclass
class RobotQaConfig:
    base_url: str = "https://localhost/api"
    verify_tls: bool = False
    users: dict[str, str] = field(default_factory=dict)
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    default_thresholds: dict = field(default_factory=dict)
    campaigns_dir: Path = ROBOT_QA_DIR / "config" / "campaigns"
    testcases_dir: Path = ROBOT_QA_DIR / "testcases"
    datasets_dir: Path = ROBOT_QA_DIR / "datasets"
    rubrics_dir: Path = ROBOT_QA_DIR / "rubrics"
    evidence_dir: Path = ROBOT_QA_DIR / "evidence"
    reports_dir: Path = ROBOT_QA_DIR / "reports"
    sut_root: Path = ROOT


def load_config(env_path: Path | None = None, thresholds_path: Path | None = None) -> RobotQaConfig:
    env = _parse_env_file(env_path or (ROOT / ".env"))
    users = {u: env.get("LDAP_DEMO_PASSWORD", "demo1234") for u in _USUARIOS_DEMO}

    thresholds_path = thresholds_path or (ROBOT_QA_DIR / "config" / "thresholds.yaml")
    default_thresholds = {}
    if thresholds_path.is_file():
        default_thresholds = yaml.safe_load(thresholds_path.read_text(encoding="utf-8")) or {}

    return RobotQaConfig(
        base_url=env.get("VITE_API_URL", "https://localhost/api"),
        users=users,
        gemini=GeminiConfig(
            api_key=env.get("GEMINI_API_KEY", ""),
            base_url=env.get("GEMINI_BASE_URL", GeminiConfig.base_url),
            model=env.get("GEMINI_MODEL", GeminiConfig.model),
        ),
        default_thresholds=default_thresholds,
    )
