/**
 * Databooks (Qualidade): controle de envio do dossiê ao cliente ("Enviado-DB") e conferência do PDF final.
 * A geração fica na página do lote (SecaoDatabookLote). "Enviado-DB" é o envio do DOCUMENTO; a saída física
 * do lote é a Ordem de Faturamento, outro módulo.
 *
 * Rotas: /databooks (abas A enviar / Enviados-DB; aceita ?aba=enviados ou ?tab=enviados e ?tipo=PIN|BOX|ARK)
 *        /databooks/conferir/:loteId (aceita ?arquivo= para conferir uma revisão anterior)
 */
import { Link, Route, Routes } from 'react-router-dom';
import { Cabecalho, Vazio } from '../../componentes/Estados';
import { ConferenciaDatabookTela } from './ConferenciaDatabook';
import { ListaDatabooks } from './ListaDatabooks';
import './databooks.css';

export function ModuloDatabooks() {
  return (
    <Routes>
      <Route index element={<ListaDatabooks />} />
      <Route path="conferir/:loteId" element={<ConferenciaDatabookTela />} />
      <Route
        path="*"
        element={
          <>
            <Cabecalho titulo="Databooks" />
            <Vazio titulo="Este endereço não existe.">
              <Link to="/databooks">Ir para Databooks</Link>
            </Vazio>
          </>
        }
      />
    </Routes>
  );
}
