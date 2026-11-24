/* Matéria-prima: corridas recebidas, certificados e carimbo APROVADO (legado/app.py, seção "MATÉRIA-PRIMA"). */
import { Link, Route, Routes } from 'react-router-dom';
import { Cabecalho, Vazio } from '../../componentes/Estados';
import { DetalheCorrida } from './DetalheCorrida';
import { ListaCorridas } from './ListaCorridas';
import './materia-prima.css';

export function ModuloMateriaPrima() {
  return (
    <Routes>
      <Route index element={<ListaCorridas />} />
      <Route path=":id" element={<DetalheCorrida />} />
      <Route
        path="*"
        element={
          <>
            <Cabecalho titulo="Página não encontrada" />
            <Vazio titulo="Este endereço não existe na matéria-prima.">
              <Link to="/materia-prima">Voltar para a lista de corridas</Link>
            </Vazio>
          </>
        }
      />
    </Routes>
  );
}
