"""Configuração lida do ambiente (.env no servidor). Nenhum segredo fica no código."""
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

FUSO = ZoneInfo("America/Sao_Paulo")


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "producao"  # producao | dev | teste
    database_url: str = "postgresql+psycopg://acokeyq:acokeyq@db:5432/acokeyq"
    # Pasta dos arquivos enviados (anexos dos lotes, certificados, fotos, assinaturas). No servidor é um volume.
    arquivos_dir: str = "/dados/arquivos"

    admin_login: str = "admin"
    admin_nome: str = "Administrador"
    admin_senha_inicial: str = ""

    sessao_horas: int = 12  # sem uso por esse tempo, a sessão expira
    sessao_max_dias: int = 7  # mesmo em uso contínuo, exige novo login depois disso
    login_max_tentativas: int = 5
    login_bloqueio_minutos: int = 15
    senha_tamanho_minimo: int = 10

    @property
    def producao(self) -> bool:
        return self.app_env == "producao"

    @property
    def pasta_arquivos(self) -> Path:
        return Path(self.arquivos_dir).resolve()


@lru_cache
def config() -> Config:
    return Config()


def agora_local() -> datetime:
    """Data e hora da fábrica (Itu/SP), sem fuso — é como os registros de produção são gravados."""
    return datetime.now(FUSO).replace(tzinfo=None, microsecond=0)
