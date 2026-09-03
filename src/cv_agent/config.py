from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Fuente única de la raíz del repo — evita que cada módulo recalcule su propia cadena de
# `.parent` (un error de conteo ahí es silencioso hasta que algo intenta leer `data/`).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str = ""
    gcp_project: str = ""
    vertex_region: str = "us-east5"
    cloud_run_region: str = "northamerica-south1"
    model_id: str = "claude-sonnet-4-5"
    # "anthropic_direct" es la decisión de producción (ARCHITECTURE.md §6) — la cuota de Vertex
    # para el modelo de chat nunca se aprobó a tiempo para el reto. "vertex" queda soportado
    # (mismo Protocol `Provider`, ver providers/vertex_anthropic.py) por si se retoma después.
    provider_backend: Literal["vertex", "anthropic_direct"] = "anthropic_direct"
    anthropic_api_key: str = ""
    embedding_model: str = "text-multilingual-embedding-002"
    retrieval_backend: str = "local"
    max_loop_iterations: int = 6
    state_ttl_seconds: int = 3600
    max_output_tokens_cap: int = 4096
    provider_timeout_seconds: float = 30.0
    log_level: str = "INFO"
    env: str = "dev"


settings = Settings()
