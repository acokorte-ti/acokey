"""Configuração lida do ambiente (.env no servidor). Nenhum segredo fica no código."""
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

FUSO = ZoneInfo("America/Sao_Paulo")


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "producao"  # producao | dev | teste
    database_url: str = "postgresql+psycopg://acokey:acokey@db:5432/acokey"
    # Pasta dos arquivos enviados (anexos dos lotes, certificados, fotos, assinaturas). No servidor é um volume.
    arquivos_dir: str = "/dados/arquivos"

    admin_login: str = "admin"
    admin_nome: str = "Administrador"
    admin_senha_inicial: str = ""

    sessao_horas: int = 12  # sem uso por esse tempo, a sessão expira
    sessao_max_dias: int = 7  # mesmo em uso contínuo, exige novo login depois disso
    login_max_tentativas: int = 5
    login_bloqueio_minutos: int = 15

    # ERP Mega (Oracle), SOMENTE LEITURA, com usuário próprio deste sistema (acokey_ro). Ver backend/app/mega.py,
    # docs/integracao_mega.md e scripts/mega/01_criar_usuario_leitura.sql
    mega_habilitado: bool = False
    mega_dsn: str = ""
    mega_usuario: str = ""
    mega_senha: str = ""
    mega_instant_client: str = "/opt/instantclient"
    mega_esquema: str = "ACOKORTE"  # dono das tabelas do ERP
    mega_filial: int = 3  # filial de Itu no Mega
    mega_ops_desde: date = date(2024, 1, 1)  # OPs abertas antes disso não são lidas

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
