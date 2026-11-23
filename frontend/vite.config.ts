import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// O site roda com CSP restrita (sem scripts inline, sem CDN): tudo sai do próprio build.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // No desenvolvimento a API roda em outra porta; o cookie de sessão passa pelo proxy
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // Nada de fontes embutidas como data: (a CSP só aceita arquivos do próprio site)
    assetsInlineLimit: 0,
    sourcemap: false,
  },
});
