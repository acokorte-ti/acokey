/* Envios a prestador externo: lote ou corpos de prova saindo para laboratório, revestimento ou NDT
   (legado/app.py, seção "ENVIOS A PRESTADOR"; telas envios_prestador_* de templates_html.py). */
import { Link, Route, Routes } from 'react-router-dom';
import { Cabecalho, Vazio } from '../../componentes/Estados';
import { DetalheEnvio } from './DetalheEnvio';
import './envios.css';
import { FormularioEnvio } from './FormularioEnvio';
import { ListaEnvios } from './ListaEnvios';

export function ModuloEnvios() {
  return (
    <Routes>
      <Route index element={<ListaEnvios />} />
      <Route path="novo" element={<FormularioEnvio />} />
      <Route path=":id" element={<DetalheEnvio />} />
      <Route path=":id/editar" element={<FormularioEnvio />} />
      <Route
        path="*"
        element={
          <>
            <Cabecalho titulo="Página não encontrada" />
            <Vazio titulo="Este endereço não existe nos envios a prestador.">
              <Link to="/envios">Voltar para a lista de envios</Link>
            </Vazio>
          </>
        }
      />
    </Routes>
  );
}
