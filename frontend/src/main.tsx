import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

// Fontes servidas pelo próprio site (a CSP não permite CDN). Só o subconjunto latino, que cobre o português.
import '@fontsource/ibm-plex-sans/latin-400.css';
import '@fontsource/ibm-plex-sans/latin-500.css';
import '@fontsource/ibm-plex-sans/latin-600.css';
import '@fontsource/ibm-plex-sans/latin-700.css';
import '@fontsource/ibm-plex-mono/latin-400.css';
import '@fontsource/ibm-plex-mono/latin-500.css';
import '@fontsource/ibm-plex-mono/latin-600.css';
import './estilos.css';

import { App } from './App';
import { ProvedorAvisos } from './lib/avisos';
import { ProvedorSessao } from './lib/sessao';

const raiz = document.getElementById('root');
if (!raiz) throw new Error('Elemento #root não encontrado no index.html.');

createRoot(raiz).render(
  <StrictMode>
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <ProvedorAvisos>
        <ProvedorSessao>
          <App />
        </ProvedorSessao>
      </ProvedorAvisos>
    </BrowserRouter>
  </StrictMode>,
);
