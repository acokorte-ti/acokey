import { api, enderecoApi } from '../../lib/api';
import { useCarga } from '../../lib/useCarga';
import type { Instrucao, StatusCarga } from './tipos';

const STATUS: Record<StatusCarga, { rotulo: string; classe: string }> = {
  planejada: { rotulo: 'Planejada', classe: 'selo-espera' },
  em_andamento: { rotulo: 'Em andamento', classe: 'selo-andamento' },
  concluida: { rotulo: 'Concluída', classe: 'selo-ok' },
  cancelada: { rotulo: 'Cancelada', classe: 'selo-inativo' },
};

export function SeloCarga({ status }: { status: StatusCarga }) {
  const aparencia = STATUS[status] ?? { rotulo: status, classe: '' };
  return <span className={`selo ${aparencia.classe}`}>{aparencia.rotulo}</span>;
}

export function rotuloStatus(status: StatusCarga): string {
  return STATUS[status]?.rotulo.toLowerCase() ?? status;
}

/** Instruções de trabalho (ITT) da Qualidade, para abrir em outra aba antes de rodar a carga. */
export function Instrucoes() {
  const lista = useCarga<Instrucao[]>((sinal) => api('/recursos/instrucoes', { sinal }), []);
  return (
    <section className="cartao" aria-labelledby="titulo-itt">
      <h2 id="titulo-itt">Instruções de trabalho (ITT)</h2>
      {lista.erro && <p className="texto-erro">{lista.erro}</p>}
      {!lista.erro && lista.dados && lista.dados.length === 0 && (
        <p className="dica">Nenhuma instrução em PDF na pasta de instruções da Qualidade.</p>
      )}
      {lista.dados && lista.dados.length > 0 && (
        <>
          <p className="dica">Documentos oficiais da Qualidade. Abra em outra aba antes de executar a carga.</p>
          <ul className="ctt-instrucoes">
            {lista.dados.map((it) => (
              <li key={it.arquivo}>
                <a href={enderecoApi(`/recursos/instrucoes/${encodeURIComponent(it.arquivo)}`)} target="_blank" rel="noopener">
                  {it.nome}
                  <span className="so-leitor"> (PDF, abre em outra aba)</span>
                </a>
                <span className="sub-linha">{it.tamanho_kb} KB</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
