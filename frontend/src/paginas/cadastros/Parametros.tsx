import { useState } from 'react';
import { Campo } from '../../componentes/Campo';
import { Cabecalho, Carregando, ErroCarga, Faixa } from '../../componentes/Estados';
import { ModalFormulario } from '../../componentes/Modal';
import { api, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { dataHoraSistema, TRACO } from '../../lib/formato';
import { useCarga } from '../../lib/useCarga';
import type { Parametro } from './tipos';

/** Parâmetros com texto longo ganham uma caixa de várias linhas. */
const LONGOS = new Set(['empresa_endereco', 'cliente_nome', 'especificacao_codigo']);

type Edicao = { novo: false; parametro: Parametro; valor: string } | { novo: true; chave: string; valor: string };

/**
 * Valores que os documentos usam e que não podem ficar no código (o repositório é público):
 * razão social, endereço, cliente final, código da especificação, formato do laser, fornos e elementos químicos.
 */
export function Parametros() {
  const avisos = useAvisos();
  const lista = useCarga<Parametro[]>((sinal) => api('/parametros', { sinal }), []);
  const [edicao, setEdicao] = useState<Edicao | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function salvar() {
    if (!edicao) return;
    const chave = edicao.novo ? edicao.chave.trim() : edicao.parametro.chave;
    setErro(null);
    setEnviando(true);
    try {
      await api<Parametro>(`/parametros/${encodeURIComponent(chave)}`, { metodo: 'PUT', corpo: { valor: edicao.valor } });
      avisos.sucesso(`Parâmetro ${chave} gravado.`);
      setEdicao(null);
      lista.recarregar();
    } catch (falha) {
      setErro(mensagemDeErro(falha));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <>
      <Cabecalho
        titulo="Parâmetros"
        apoio="Dados da empresa e padrões usados nos documentos. Ficam no banco, e não no programa, porque o código do sistema é público."
      >
        <button type="button" className="botao" onClick={() => { setErro(null); setEdicao({ novo: true, chave: '', valor: '' }); }}>
          Outro parâmetro
        </button>
      </Cabecalho>

      <Faixa tipo="info" papel="note">
        O nome do cliente final só aparece em documentos <strong>internos</strong>: nunca em documento que sai da empresa (ex.: PDF
        para prestador externo). Campo vazio usa o valor padrão, quando houver.
      </Faixa>

      {lista.erro && <ErroCarga mensagem={lista.erro} aoTentar={lista.recarregar} />}
      {!lista.dados && lista.carregando && <Carregando />}
      {lista.dados && (
        <section className={`cartao ${lista.carregando ? 'recarregando' : ''}`} aria-label="Parâmetros do sistema">
          <div className="tabela-rolagem">
            <table className="tabela">
              <caption className="so-leitor">Parâmetros do sistema</caption>
              <thead>
                <tr>
                  <th scope="col">Parâmetro</th>
                  <th scope="col">Valor em uso</th>
                  <th scope="col">Alterado</th>
                  <th scope="col">
                    <span className="so-leitor">Ações</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {lista.dados.map((p) => (
                  <tr key={p.chave}>
                    <td className="celula-larga">
                      <strong className="mono">{p.chave}</strong>
                      <span className="sub-linha cad-param-descricao">
                        {p.descricao || (p.conhecido ? '' : 'Parâmetro lido por algum módulo (não está na lista padrão).')}
                      </span>
                    </td>
                    <td className="cad-param-valor">
                      {p.valor ? (
                        p.valor
                      ) : p.padrao ? (
                        <span className="automatico-vazio">padrão: {p.padrao}</span>
                      ) : (
                        <span className="texto-alerta">não preenchido</span>
                      )}
                    </td>
                    <td>
                      {p.alterado_em ? (
                        <>
                          {dataHoraSistema(p.alterado_em)}
                          <span className="sub-linha"> · {p.alterado_por || TRACO}</span>
                        </>
                      ) : (
                        TRACO
                      )}
                    </td>
                    <td>
                      <button type="button" className="botao botao-pequeno"
                        onClick={() => { setErro(null); setEdicao({ novo: false, parametro: p, valor: p.valor }); }}>
                        Editar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {edicao && (
        <ModalFormulario
          titulo={edicao.novo ? 'Outro parâmetro' : `Parâmetro ${edicao.parametro.chave}`}
          largura="larga"
          aoFechar={() => setEdicao(null)}
          aoEnviar={() => void salvar()}
          enviando={enviando}
          erro={erro}
        >
          {edicao.novo ? (
            <Campo rotulo="Nome do parâmetro" para="par-chave" obrigatorio
              dica="O nome exato que o módulo lê: letras minúsculas, números e sublinhado (ex.: cliente_nome).">
              <input id="par-chave" type="text" className="mono" required pattern="[a-z][a-z0-9_]{1,59}" maxLength={60} value={edicao.chave}
                onChange={(e) => setEdicao({ ...edicao, chave: e.target.value.toLowerCase() })} />
            </Campo>
          ) : (
            edicao.parametro.descricao && <p>{edicao.parametro.descricao}</p>
          )}
          <Campo
            rotulo="Valor"
            para="par-valor"
            dica={!edicao.novo && edicao.parametro.padrao ? `Vazio = usa o padrão: ${edicao.parametro.padrao}` : 'Vazio = sem valor.'}
          >
            {!edicao.novo && LONGOS.has(edicao.parametro.chave) ? (
              <textarea id="par-valor" rows={3} maxLength={2000} value={edicao.valor} onChange={(e) => setEdicao({ ...edicao, valor: e.target.value })} />
            ) : (
              <input id="par-valor" type="text" maxLength={2000} value={edicao.valor} onChange={(e) => setEdicao({ ...edicao, valor: e.target.value })} />
            )}
          </Campo>
          {!edicao.novo && edicao.parametro.chave === 'laser_formato' && (
            <p className="dica">
              Campos disponíveis: <code>{'{ano}'}</code>, <code>{'{tri}'}</code> (trimestre), <code>{'{corrida}'}</code>,{' '}
              <code>{'{lote}'}</code> e <code>{'{seq}'}</code> (número da peça; <code>{'{seq:03d}'}</code> = 3 dígitos com zeros).
            </p>
          )}
        </ModalFormulario>
      )}
    </>
  );
}
