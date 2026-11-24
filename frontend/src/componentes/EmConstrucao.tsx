import { Link } from 'react-router-dom';
import { Cabecalho, Vazio } from './Estados';

/** Tela provisória de um módulo que ainda está sendo portado do sistema antigo. */
export function EmConstrucao({ titulo, apoio }: { titulo: string; apoio?: string }) {
  return (
    <div className="em-construcao">
      <Cabecalho titulo={titulo} apoio={apoio} />
      <Vazio titulo="Este módulo está sendo trazido do sistema antigo.">
        Enquanto isso, use o sistema antigo para esta tela. <Link to="/">Voltar ao painel</Link>
      </Vazio>
    </div>
  );
}
