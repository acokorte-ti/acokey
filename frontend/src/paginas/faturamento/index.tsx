/* Ordem de faturamento: lotes prontos saindo fisicamente da fábrica
   (legado/app.py, seção "ORDEM DE FATURAMENTO (OF)"; telas of_* de templates_html.py).
   Não confundir com o "Enviado-DB" (databook mandado ao cliente), que é outro fluxo. */
import { Link, Route, Routes } from 'react-router-dom';
import { Cabecalho, Vazio } from '../../componentes/Estados';
import '../envios/envios.css';
import { DetalheOF } from './DetalheOF';
import './faturamento.css';
import { FormularioOF } from './FormularioOF';
import { ListaOFs } from './ListaOFs';

export function ModuloFaturamento() {
  return (
    <Routes>
      <Route index element={<ListaOFs />} />
      <Route path="nova" element={<FormularioOF />} />
      <Route path=":id" element={<DetalheOF />} />
      <Route path=":id/editar" element={<FormularioOF />} />
      <Route
        path="*"
        element={
          <>
            <Cabecalho titulo="Página não encontrada" />
            <Vazio titulo="Este endereço não existe nas ordens de faturamento.">
              <Link to="/faturamento">Voltar para a lista de ordens</Link>
            </Vazio>
          </>
        }
      />
    </Routes>
  );
}
