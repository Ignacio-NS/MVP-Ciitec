"""Adaptador REST hacia la API de MVP-Ciitec.

Reusa el flujo de autenticacion y carga de `scripts/loadtest.py` (login LDAP ->
JWT -> POST /fuentes -> POST /briefings -> poll) pero lo expone como acciones
nombradas (`case.input["action"]`) para que un mismo adaptador cubra las
familias funcional, RAG, seguridad, robustez y rendimiento sin que cada
evaluador conozca detalles de transporte HTTP.

Limitacion documentada (Guia S10, "todo resultado debe poder reconstruirse"):
la API de MVP-Ciitec no expone tokens/costo del LLM en sus respuestas, asi que
`Observation.tokens_in/out/cost_usd` quedan en None salvo que el llamador los
calcule aparte. El evaluador `budget` solo controla latencia por ese motivo.
"""
from __future__ import annotations

import io
import mimetypes
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ..models import Observation, TestCase

_DEFAULT_TIMEOUT = 120.0


class LoginError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class ApiAdapter:
    """SutAdapter concreto: invoke(case) -> Observation via la API REST."""

    def __init__(
        self,
        base_url: str,
        users: dict[str, str],
        *,
        verify: bool = False,
        timeout: float = _DEFAULT_TIMEOUT,
        default_poll_timeout: float = 180.0,
        sut_version: str = "",
        sut_root: Path | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.users = users
        self.verify = verify
        self.timeout = timeout
        self.default_poll_timeout = default_poll_timeout
        self.sut_version = sut_version
        # raiz del monorepo: permite a los casos referenciar el corpus real
        # (./corpus, generado por scripts/gen_corpus.py) via setup.corpus_glob.
        self.sut_root = sut_root or Path(__file__).resolve().parents[4]
        self._client = httpx.Client(base_url=self.base_url, verify=verify, timeout=timeout)
        self._tokens: dict[str, str] = {}

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------- helpers
    def _password_for(self, username: str) -> str:
        if username not in self.users:
            raise KeyError(
                f"Usuario '{username}' sin password configurada (robot-qa/config: users)"
            )
        return self.users[username]

    def _login(self, username: str, password: str | None = None) -> tuple[str, dict]:
        """Devuelve (token, usuario) usando cache de sesion por usuario."""
        pwd = password if password is not None else self._password_for(username)
        r = self._client.post("/auth/login", json={"username": username, "password": pwd})
        if r.status_code != 200:
            raise LoginError(r.status_code, f"login fallo para {username}: {r.status_code} {r.text[:300]}")
        body = r.json()
        self._tokens[username] = body["token"]
        return body["token"], body.get("usuario", {})

    def _headers(self, username: str) -> dict:
        token = self._tokens.get(username)
        if token is None:
            token, _ = self._login(username)
        return {"Authorization": f"Bearer {token}"}

    def _resolve_documents(self, case: TestCase) -> list[dict]:
        """Documentos inline (`setup.documents`, versionados en el YAML del caso)
        mas, opcionalmente, archivos reales del corpus sintetico
        (`setup.corpus_glob` + `setup.corpus_limit`, generado por
        `scripts/gen_corpus.py`) -- usado por las suites de cobertura de
        formato (PDF/Word/Excel real) y de rendimiento (50 documentos)."""
        docs = list(case.setup.get("documents", []))
        glob_pat = case.setup.get("corpus_glob")
        if glob_pat:
            corpus_dir = self.sut_root / "corpus"
            limit = case.setup.get("corpus_limit")
            files = sorted(corpus_dir.glob(glob_pat))
            if limit:
                files = files[:limit]
            if not files:
                raise RuntimeError(
                    f"corpus_glob '{glob_pat}' no encontro archivos en {corpus_dir}. "
                    "Ejecuta: python scripts/gen_corpus.py"
                )
            docs += [{"name": f.name, "path": str(f)} for f in files]
        return docs

    def _upload_documents(self, username: str, documents: list[dict], nivel: str) -> list[dict]:
        """Sube documentos via multipart: cada uno inline ({name, content}) o
        real en disco ({name, path}, para PDF/Word/Excel del corpus sintetico)."""
        headers = self._headers(username)
        files = []
        for doc in documents:
            name = doc["name"]
            if "path" in doc:
                data = Path(doc["path"]).read_bytes()
                ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            else:
                data = doc.get("content", "").encode("utf-8")
                ctype = doc.get("content_type", "text/plain")
            files.append(("files", (name, io.BytesIO(data), ctype)))
        r = self._client.post(
            "/fuentes", data={"nivel_clasificacion": nivel}, files=files, headers=headers
        )
        if r.status_code != 200:
            raise RuntimeError(f"subida de fuentes fallo: {r.status_code} {r.text[:300]}")
        return r.json()["fuentes"]

    # -------------------------------------------------------------- invoke
    def invoke(self, case: TestCase, *, repetition: int, run_id: str) -> Observation:
        action = case.input.get("action", "flujo_briefing")
        handler = getattr(self, f"_action_{action}", None)
        if handler is None:
            return Observation(
                case_id=case.case_id, repetition=repetition, run_id=run_id,
                sut_version=self.sut_version, error=f"accion desconocida: {action}",
            )
        t0 = time.perf_counter()
        try:
            output, http_status, extra = handler(case)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return Observation(
                case_id=case.case_id, repetition=repetition, run_id=run_id,
                output=output, latency_ms=latency_ms, http_status=http_status,
                sut_version=self.sut_version, traces=extra.get("traces", {}),
                sources_used=extra.get("sources_used", []),
            )
        except Exception as exc:  # el fallo del SUT/red es evidencia, no una excepcion del robot
            latency_ms = (time.perf_counter() - t0) * 1000.0
            return Observation(
                case_id=case.case_id, repetition=repetition, run_id=run_id,
                latency_ms=latency_ms, sut_version=self.sut_version, error=str(exc),
            )

    # ------------------------------------------------------------ acciones
    def _action_login(self, case: TestCase):
        username = case.input["username"]
        password = case.input.get("password")  # None -> valida; string explicito -> caso negativo
        try:
            _, usuario = self._login(username, password)
            return {"login_ok": True, "usuario": usuario}, 200, {}
        except LoginError as exc:
            return {"login_ok": False, "detalle": str(exc)}, exc.status_code, {}

    def _action_flujo_briefing(self, case: TestCase):
        username = case.input.get("username", "operaciones")
        titulo = case.input.get("titulo", case.case_id)
        nivel = case.input.get("nivel_clasificacion", "RESERVADO")
        documents = self._resolve_documents(case)
        poll_timeout = case.input.get("poll_timeout", self.default_poll_timeout)
        fetch = case.input.get("fetch", ["trazabilidad", "inconsistencias"])

        headers = self._headers(username)
        fuentes = self._upload_documents(username, documents, nivel) if documents else []
        fuente_ids = case.input.get("fuente_ids") or [f["id"] for f in fuentes] or None

        body = {"titulo": titulo, "nivel_clasificacion": nivel}
        if fuente_ids:
            body["fuente_ids"] = fuente_ids
        r = self._client.post("/briefings", json=body, headers=headers)
        if r.status_code != 200:
            return {"fuentes": fuentes, "error_creacion": r.text[:500]}, r.status_code, {}
        creacion = r.json()
        briefing_id = creacion["briefing_id"]

        t0 = time.time()
        contenido = None
        version = None
        while time.time() - t0 < poll_timeout:
            det = self._client.get(f"/briefings/{briefing_id}", headers=headers)
            if det.status_code == 200:
                data = det.json()
                if data.get("contenido"):
                    contenido = data["contenido"]
                    version = data.get("version")
                    break
            time.sleep(2)

        out = {
            "briefing_id": briefing_id, "fuentes": fuentes, "version": version,
            "contenido": contenido, "timed_out": contenido is None,
            "generation_seconds": time.time() - t0,
        }
        sources_used = []
        if "trazabilidad" in fetch:
            tr = self._client.get(f"/briefings/{briefing_id}/trazabilidad", headers=headers)
            if tr.status_code == 200:
                out["trazabilidad"] = tr.json()
                sources_used = [t.get("hecho_id") for t in out["trazabilidad"].get("trazas", [])]
        if "inconsistencias" in fetch:
            inc = self._client.get(f"/briefings/{briefing_id}/inconsistencias", headers=headers)
            if inc.status_code == 200:
                out["inconsistencias"] = inc.json()
        return out, 200, {"sources_used": sources_used}

    def _action_edit_version_check(self, case: TestCase):
        """RF-007: editar el contenido activo debe crear una version NUEVA (append-only),
        nunca sobreescribir la existente, y el diff entre ambas debe reflejar el cambio."""
        out, status_code, extra = self._action_flujo_briefing(case)
        if status_code != 200 or not out.get("contenido"):
            return out, status_code, extra
        username = case.input.get("username", "operaciones")
        headers = self._headers(username)
        editado = dict(out["contenido"])
        bullets = list(editado.get("resumen_ejecutivo") or [""])
        bullets[0] = f"[EDITADO-QA] {bullets[0]}"
        editado["resumen_ejecutivo"] = bullets

        r = self._client.post(
            f"/briefings/{out['briefing_id']}/versiones",
            json={"contenido": editado, "base_version": out["version"], "comentario": "robot-qa edit_version_check"},
            headers=headers,
        )
        out["edit_status"] = r.status_code
        if r.status_code != 200:
            return out, r.status_code, extra
        nueva_version = r.json().get("version") or r.json().get("numero_version")
        out["new_version"] = nueva_version

        diff = self._client.get(
            f"/briefings/{out['briefing_id']}/diff/{out['version']}/{nueva_version}", headers=headers
        )
        out["diff_status"] = diff.status_code
        out["diff"] = diff.json() if diff.status_code == 200 else diff.text[:300]
        return out, r.status_code, extra

    def _action_point_in_time_check(self, case: TestCase):
        """RF-009: reconstruir el briefing tal como estaba ANTES de que existiera
        version alguna debe devolver 404; reconstruirlo a "ahora" debe devolver la
        version activa."""
        t_before = datetime.now(timezone.utc).isoformat()
        out, status_code, extra = self._action_flujo_briefing(case)
        if status_code != 200 or not out.get("contenido"):
            return out, status_code, extra
        t_after = datetime.now(timezone.utc).isoformat()
        headers = self._headers(case.input.get("username", "operaciones"))

        antes = self._client.get(f"/briefings/{out['briefing_id']}/versiones", params={"at": t_before}, headers=headers)
        despues = self._client.get(f"/briefings/{out['briefing_id']}/versiones", params={"at": t_after}, headers=headers)
        out["status_antes"] = antes.status_code
        out["status_despues"] = despues.status_code
        ok = antes.status_code == 404 and despues.status_code == 200
        return out, (200 if ok else 500), extra

    def _action_rbac_check(self, case: TestCase):
        owner = case.input["owner_username"]
        prober = case.input["prober_username"]
        nivel = case.input.get("nivel_clasificacion", "RESERVADO")
        documents = case.setup.get("documents") or [
            {"name": "doc_rbac.txt", "content": "Documento de prueba RBAC para robot-qa."}
        ]
        owner_headers = self._headers(owner)
        fuentes = self._upload_documents(owner, documents, nivel)
        fuente_id = fuentes[0]["id"]

        target = case.input.get("target", "fuente")  # "fuente" | "briefing"
        if target == "briefing":
            r = self._client.post(
                "/briefings",
                json={"titulo": case.case_id, "fuente_ids": [fuente_id], "nivel_clasificacion": nivel},
                headers=owner_headers,
            )
            resource_id = r.json()["briefing_id"]
            path = f"/briefings/{resource_id}"
        else:
            resource_id = fuente_id
            path = f"/fuentes/{resource_id}"

        prober_headers = self._headers(prober)
        probe = self._client.get(path, headers=prober_headers)
        return (
            {"target": target, "resource_id": resource_id, "probed_status": probe.status_code,
             "probed_body": probe.text[:300]},
            probe.status_code,
            {},
        )

    def _action_audit_check(self, case: TestCase):
        username = case.input.get("username", "auditor")
        headers = self._headers(username)
        r = self._client.get("/audit/verificar", headers=headers)
        body = r.json() if r.status_code == 200 else {"error": r.text[:300]}
        return body, r.status_code, {}

    def _action_export_check(self, case: TestCase):
        out, status_code, extra = self._action_flujo_briefing(case)
        if status_code != 200 or not out.get("briefing_id"):
            return out, status_code, extra
        username = case.input.get("username", "operaciones")
        formato = case.input.get("formato", "PDF")
        headers = self._headers(username)
        r = self._client.post(
            f"/briefings/{out['briefing_id']}/exportar", json={"formato": formato}, headers=headers
        )
        out["export_status"] = r.status_code
        out["export_content_type"] = r.headers.get("content-type", "")
        out["export_bytes"] = len(r.content)
        return out, r.status_code, extra

    def _action_approve_check(self, case: TestCase):
        out, status_code, extra = self._action_flujo_briefing(case)
        if status_code != 200 or not out.get("briefing_id"):
            return out, status_code, extra
        versiones_headers = self._headers(case.input.get("username", "operaciones"))
        vs = self._client.get(f"/briefings/{out['briefing_id']}/versiones", headers=versiones_headers)
        vlist = vs.json().get("versiones", [])
        if not vlist:
            out["approve_status"] = 404
            return out, 404, extra
        version_id = vlist[-1]["id"]
        approver = case.input.get("approver_username", "comandante")
        approver_headers = self._headers(approver)
        r = self._client.post(f"/briefings/versiones/{version_id}/aprobar", headers=approver_headers)
        out["approve_status"] = r.status_code
        out["approve_body"] = r.text[:300]
        return out, r.status_code, extra
