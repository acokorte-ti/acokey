/* Não conformidades: lista (Em aberto / Encerradas), detalhe com a decisão de disposição e correção de dureza. */
import { Route, Routes } from 'react-router-dom';
import { CorrigirDureza } from './CorrigirDureza';
import { DetalheNaoConformidade } from './DetalheNc';
import { ListaNaoConformidades } from './ListaNc';
import './nc.css';

/** Rotas: /nao-conformidades, /nao-conformidades/:id e /nao-conformidades/:id/corrigir-dureza. */
export function ModuloNC() {
  return (
    <Routes>
      <Route index element={<ListaNaoConformidades />} />
      <Route path=":id" element={<DetalheNaoConformidade />} />
      <Route path=":id/corrigir-dureza" element={<CorrigirDureza />} />
    </Routes>
  );
}
