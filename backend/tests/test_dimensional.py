"""Verificação dimensional de um RIP-33A. O PDF é gerado aqui, com valores fictícios."""
import io
from datetime import datetime

from conftest import lote_exemplo
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from app.dimensional import analisar_rip33a
from app.models import Anexo
from app.pdf_comum import fontes

VAZIO8 = [""] * 4


def _rip33a() -> bytes:
    """Tabela no formato do RIP-33A: CAR, requisito, especificação, tolerância, 4 colunas livres, P1..P10 e rodapé."""
    fonte = fontes()["normal"]
    cab = ["CAR", "Requisito", "Especificação", "Tolerância", "Instr.", "Freq.", "Obs.", "Res."] + [f"P{i}" for i in range(1, 11)]
    amostras = lambda *v: list(v) + [""] * (10 - len(v))  # noqa: E731
    linhas = [
        cab,
        ["1", "Comprimento total", "100,00", "+0,10/-0,10", *VAZIO8, *amostras("100.02", "99.95", "100.20", "100.00")],
        ["2", "Largura da chaveta", "20 (2x)", "± 0,05", *VAZIO8, *amostras("20.01", "20.00", "19.99", "20.03")],
        ["3", "Aspecto", "---", "---", *VAZIO8, *amostras("OK", "OK")],
        ["4", "Raio", "R5", "conforme desenho", *VAZIO8, *amostras("5.0", "5.1")],
        ["Inspecionado por\nFulano", "", "Data\n20/11/2026", "", "Aprovado por\nBeltrano", "Data\n21/11/2026"] + [""] * 12,
        ["Situação do lote: Aprovado - Inspeção", "", "", "", "", "", "", "", "X"] + [""] * 9,
    ]
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=8 * mm, rightMargin=8 * mm)
    tabela = Table(linhas, colWidths=[10 * mm, 40 * mm, 24 * mm, 26 * mm] + [18 * mm] * 4 + [10.5 * mm] * 10)
    # Como no relatório de verdade, os campos do rodapé ocupam células mescladas
    tabela.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONTSIZE", (0, 0), (-1, -1), 7),
                                ("FONTNAME", (0, 0), (-1, -1), fonte), ("SPAN", (0, 5), (1, 5)), ("SPAN", (2, 5), (3, 5)),
                                ("SPAN", (0, 6), (7, 6))]))  # fmt: skip
    doc.build([tabela])
    return buffer.getvalue()


def test_analise_aponta_cotas_fora_e_le_o_rodape():
    r = analisar_rip33a(dados=_rip33a())
    assert r["ok"] is True and r["total_cars"] == 4
    por_car = {c["car"]: c for c in r["cars"]}
    assert por_car["1"]["faixa"] == [99.9, 100.1] and por_car["1"]["requisito"] == "Comprimento total"
    assert [f["amostra"] for f in por_car["1"]["fora"]] == ["P3"] and por_car["1"]["fora"][0]["valor"] == 100.2
    assert por_car["2"]["faixa"] == [19.95, 20.05] and por_car["2"]["fora"] == []
    assert por_car["2"]["minimo"] == 19.99 and por_car["2"]["maximo"] == 20.03
    assert por_car["3"]["fora"] == [] and por_car["3"]["aviso"] is False  # qualitativo: nada a calcular
    assert [c["car"] for c in r["cars_fora"]] == ["1"]
    assert [c["car"] for c in r["cars_aviso"]] == ["4"]  # tolerância em texto: revisar à mão
    assert r["rodape"] == {"inspecionado_por": "Fulano", "data_inspecao": "20/11/2026", "aprovado_por": "Beltrano",
                           "data_aprovacao": "21/11/2026", "status": "Aprovado - Inspeção"}  # fmt: skip


def test_pdf_sem_tabela_ou_invalido():
    buffer = io.BytesIO()
    SimpleDocTemplate(buffer).build([Table([["texto solto"]])])
    assert analisar_rip33a(dados=buffer.getvalue())["ok"] is False
    r = analisar_rip33a(dados=b"%PDF-1.4 quebrado")
    assert r["ok"] is False and "PDF" in r["erro"]


def test_rota_de_envio(cliente, admin):
    arquivos = {"arquivo": ("RIP-33A exemplo.pdf", _rip33a(), "application/pdf")}
    r = cliente.post("/api/dimensional/verificar", files=arquivos, headers={"X-CSRF-Token": admin})
    assert r.status_code == 200, r.text
    assert r.json()["nome"] == "RIP-33A exemplo.pdf" and len(r.json()["resultado"]["cars_fora"]) == 1
    falso = {"arquivo": ("falso.pdf", b"MZ\x90\x00", "application/pdf")}
    assert cliente.post("/api/dimensional/verificar", files=falso, headers={"X-CSRF-Token": admin}).status_code == 422
    texto = {"arquivo": ("notas.txt", b"abc", "text/plain")}
    assert cliente.post("/api/dimensional/verificar", files=texto, headers={"X-CSRF-Token": admin}).status_code == 422


def test_rota_de_anexo_existente(cliente, admin, db, pasta_arquivos):
    lote = lote_exemplo(db)
    (pasta_arquivos / "lotes" / str(lote.id) / "anexos").mkdir(parents=True)
    (pasta_arquivos / "lotes" / str(lote.id) / "anexos" / "rip33a.pdf").write_bytes(_rip33a())
    anexo = Anexo(lote_id=lote.id, etapa="dim_final", nome="RIP-33A.pdf", arquivo=f"lotes/{lote.id}/anexos/rip33a.pdf",
                  quando=datetime(2026, 11, 21, 10, 0))  # fmt: skip
    foto = Anexo(lote_id=lote.id, etapa="dim_final", nome="foto.jpg", arquivo=f"lotes/{lote.id}/anexos/foto.jpg")
    removido = Anexo(lote_id=lote.id, etapa="dim_final", nome="velho.pdf", arquivo=f"lotes/{lote.id}/anexos/rip33a.pdf",
                     removido_em=datetime(2026, 11, 21, 11, 0))  # fmt: skip
    db.add_all([anexo, foto, removido])
    db.commit()
    r = cliente.get(f"/api/dimensional/anexos/{anexo.id}")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["anexo"]["etapa"] == "dim_final" and corpo["lote"]["id"] == lote.id and corpo["resultado"]["total_cars"] == 4
    assert cliente.get(f"/api/dimensional/anexos/{foto.id}").status_code == 422
    assert cliente.get(f"/api/dimensional/anexos/{removido.id}").status_code == 404
    assert cliente.get("/api/dimensional/anexos/9999").status_code == 404


def test_so_qualidade_verifica(como, db):
    outro, csrf = como(modulos=["producao_usinagem"])
    assert outro.get("/api/dimensional/anexos/1").status_code == 403
    arquivos = {"arquivo": ("r.pdf", _rip33a(), "application/pdf")}
    assert outro.post("/api/dimensional/verificar", files=arquivos, headers={"X-CSRF-Token": csrf}).status_code == 403
