"""Linha do tempo de cada lote (texto para leitura humana, mostrado na página do lote)."""
from sqlalchemy.orm import Session

from app.config import agora_local
from app.models import Evento


def registrar_evento(db: Session, lote_id: int, texto: str) -> None:
    """Grava na mesma transação de quem chama (quem chama faz o commit)."""
    db.add(Evento(lote_id=lote_id, quando=agora_local(), texto=texto))
