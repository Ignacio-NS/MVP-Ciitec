import base64
import os

# Entorno mínimo para importar la app sin .env (clave AES válida de 32 bytes).
os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(b"0" * 32).decode())
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("LLM_PROVIDER", "local")  # sin API key: no depende de servicios externos
