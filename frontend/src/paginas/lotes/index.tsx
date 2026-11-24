import { Route, Routes } from 'react-router-dom';
import './lotes.css';
import { MapaLote } from './MapaLote';
import { PaginaEtapa } from './PaginaEtapa';
import { PaginaLote } from './PaginaLote';

/** Rotas /lotes/:id/*: a página do lote, cada etapa (registro, anexos, aprovação) e o mapa para impressão. */
export function ModuloLote() {
  return (
    <Routes>
      <Route index element={<PaginaLote />} />
      <Route path="etapas/:chave" element={<PaginaEtapa />} />
      <Route path="mapa" element={<MapaLote />} />
      <Route path="*" element={<PaginaLote />} />
    </Routes>
  );
}
