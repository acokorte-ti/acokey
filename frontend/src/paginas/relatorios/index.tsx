/**
 * Relatórios gerados pelo sistema (portados de legado/app.py e legado/templates_html.py: gerar_dureza, gerar_tt,
 * gerar_visual):
 *   /relatorios/dureza?lote=ID   Dureza HRC (RIP-35), só PIN/BOX — Qualidade
 *   /relatorios/tt?lote=ID       Tratamento térmico de um lote (pode incluir outras OPs) — Produção TT ou Qualidade
 *   /relatorios/tt?carga=ID      Tratamento térmico de uma carga (replica em todos os lotes e conclui a carga)
 *   /relatorios/visual?lote=ID   Inspeção visual e marcação a laser — Qualidade
 * Depois de salvar, a tela volta para o lote.
 */
import type { ReactNode } from 'react';
import { Link, Route, Routes, useSearchParams } from 'react-router-dom';
import { Cabecalho, Vazio } from '../../componentes/Estados';
import { useSessao } from '../../lib/sessao';
import { RelatorioDureza } from './RelatorioDureza';
import { RelatorioTT } from './RelatorioTT';
import { RelatorioVisual } from './RelatorioVisual';
import './relatorios.css';

function numero(texto: string | null): number | null {
  const valor = Number(texto);
  return texto && Number.isInteger(valor) && valor > 0 ? valor : null;
}

function SemPermissao() {
  return (
    <>
      <Cabecalho titulo="Sem acesso" />
      <Vazio titulo="Seu usuário não tem permissão para gerar este relatório.">
        <Link to="/">Voltar para o início</Link>
      </Vazio>
    </>
  );
}

function SemLote() {
  return (
    <>
      <Cabecalho titulo="Relatório" />
      <Vazio titulo="Abra o relatório a partir da página do lote (ou da carga de TT).">
        <Link to="/">Voltar ao painel</Link>
      </Vazio>
    </>
  );
}

function ComLote({ permitido, children }: { permitido: boolean; children: (loteId: number) => ReactNode }) {
  const [parametros] = useSearchParams();
  const loteId = numero(parametros.get('lote'));
  if (!permitido) return <SemPermissao />;
  if (loteId === null) return <SemLote />;
  // key: trocar de lote (atalhos da carga no RIP-35) recomeça o formulário do zero
  return <div key={loteId}>{children(loteId)}</div>;
}

function TelaTT({ permitido }: { permitido: boolean }) {
  const [parametros] = useSearchParams();
  const loteId = numero(parametros.get('lote'));
  const cargaId = numero(parametros.get('carga'));
  if (!permitido) return <SemPermissao />;
  if (loteId === null && cargaId === null) return <SemLote />;
  return <RelatorioTT key={`${loteId}-${cargaId}`} loteId={loteId} cargaId={cargaId} />;
}

export function ModuloRelatorios() {
  const { pode } = useSessao();
  return (
    <Routes>
      <Route path="dureza" element={<ComLote permitido={pode.qualidade}>{(id) => <RelatorioDureza loteId={id} />}</ComLote>} />
      <Route path="tt" element={<TelaTT permitido={pode.tt} />} />
      <Route path="visual" element={<ComLote permitido={pode.qualidade}>{(id) => <RelatorioVisual loteId={id} />}</ComLote>} />
      <Route path="*" element={<SemLote />} />
    </Routes>
  );
}
