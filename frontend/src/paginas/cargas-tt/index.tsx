/**
 * Cargas de tratamento térmico (portado de legado/app.py, /cargas-tt, e legado/templates_html.py: cargas_tt_lista,
 * cargas_tt_form, cargas_tt_detalhe). Produção TT ou Qualidade (o App.tsx já esconde de quem não tem).
 *   /cargas-tt              lista (abas Em aberto / Concluídas / Canceladas)
 *   /cargas-tt/nova         montar uma carga
 *   /cargas-tt/:id          detalhe e ações (iniciar, gerar relatório, concluir, cancelar)
 *   /cargas-tt/:id/editar   editar fornos, lotes e observações
 */
import type { ReactElement } from 'react';
import { Link, Route, Routes, useParams } from 'react-router-dom';
import { Cabecalho, Vazio } from '../../componentes/Estados';
import { DetalheCarga } from './DetalheCarga';
import { FormCarga } from './FormCarga';
import { ListaCargas } from './ListaCargas';
import './cargas-tt.css';

function comId(Componente: (props: { cargaId: number }) => ReactElement) {
  return function ComId() {
    const { id } = useParams();
    const cargaId = Number(id);
    if (!Number.isInteger(cargaId) || cargaId <= 0) {
      return (
        <>
          <Cabecalho titulo="Carga não encontrada" />
          <Vazio titulo="Este endereço não corresponde a uma carga.">
            <Link to="/cargas-tt">Voltar para as cargas</Link>
          </Vazio>
        </>
      );
    }
    return <Componente key={cargaId} cargaId={cargaId} />;
  };
}

const Detalhe = comId(DetalheCarga);
const Editar = comId(({ cargaId }) => <FormCarga cargaId={cargaId} />);

export function ModuloCargasTT() {
  return (
    <Routes>
      <Route index element={<ListaCargas />} />
      <Route path="nova" element={<FormCarga cargaId={null} />} />
      <Route path=":id" element={<Detalhe />} />
      <Route path=":id/editar" element={<Editar />} />
      <Route path="*" element={<ListaCargas />} />
    </Routes>
  );
}
