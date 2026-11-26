import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Campo } from '../../componentes/Campo';
import { Cabecalho, Carregando, Faixa } from '../../componentes/Estados';
import { SeloTipo } from '../../componentes/Selos';
import { api, enderecoApi, ErroApi, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { enterVaiParaProximo } from '../../lib/teclado';
import { useCarga } from '../../lib/useCarga';
import {
  decimal,
  ErroRelatorio,
  escolhaInicial,
  numeroDigitado,
  Resumo,
  SeletorEquipamento,
  SeletorPessoa,
} from './Comuns';
import type { RespostaRelatorio, TelaDureza } from './tipos';

const PONTOS = [0, 1, 2, 3, 4];

interface LinhaCP {
  chave: number;
  cp: string;
  valores: string[];
}

type Situacao = 'vazio' | 'ok' | 'fora' | 'invalido';

function situacaoDaLeitura(texto: string, min: number, max: number): Situacao {
  if (!texto.trim()) return 'vazio';
  const numero = numeroDigitado(texto);
  if (numero === null) return 'invalido';
  return numero >= min && numero <= max ? 'ok' : 'fora';
}

function numerosDaLinha(linha: LinhaCP): number[] {
  return linha.valores.map(numeroDigitado).filter((n): n is number => n !== null);
}

function linhaVazia(op: string, n: number): LinhaCP {
  return { chave: n, cp: `OP${op}-DUR${n}`, valores: ['', '', '', '', ''] };
}

function StatusTexto({ status }: { status: 'APROVADO' | 'REPROVADO' | '' }) {
  if (!status) return <span className="sub-linha">—</span>;
  return <span className={`selo ${status === 'APROVADO' ? 'selo-ok' : 'selo-erro'}`}>{status}</span>;
}

export function RelatorioDureza({ loteId }: { loteId: number }) {
  const navegar = useNavigate();
  const avisos = useAvisos();
  const tela = useCarga<TelaDureza>((sinal) => api(`/relatorios/dureza/${loteId}`, { sinal }), [loteId]);
  const dados = tela.dados;

  const [linhas, setLinhas] = useState<LinhaCP[]>([]);
  const contador = useRef(1);
  const [equipamento, setEquipamento] = useState('');
  const [executor, setExecutor] = useState<number | ''>('');
  const [aprovador, setAprovador] = useState<number | ''>('');
  const [data, setData] = useState('');
  const [dataAprovacao, setDataAprovacao] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  // Valores iniciais quando a tela carrega (e ao trocar de lote pelos atalhos da carga)
  useEffect(() => {
    if (!dados) return;
    // A tabela já vem com a amostra: 10% das peças do lote (DUR1, DUR2...)
    const n = Math.max(1, dados.amostra.linhas);
    contador.current = n;
    setLinhas(Array.from({ length: n }, (_, i) => linhaVazia(dados.lote.op, i + 1)));
    setEquipamento(dados.durometros.length === 1 ? dados.durometros[0].codigo : '');
    setExecutor(escolhaInicial(dados.executores, dados.usuario_id));
    setAprovador(escolhaInicial(dados.aprovadores, dados.usuario_id));
    setData(dados.hoje);
    setDataAprovacao(dados.hoje);
    setErro(null);
  }, [dados]);

  const min = dados?.info.esp_min ?? 0;
  const max = dados?.info.esp_max ?? 0;

  const geral = useMemo(() => {
    const todos = linhas.flatMap(numerosDaLinha);
    if (todos.length === 0) return null;
    const menor = Math.min(...todos);
    const maior = Math.max(...todos);
    return { n: todos.length, menor, maior, aprovado: menor >= min && maior <= max };
  }, [linhas, min, max]);

  if (tela.erro) {
    return (
      <>
        <Cabecalho titulo="Relatório de Dureza HRC (RIP-35)" />
        <ErroRelatorio mensagem={tela.erro} loteId={loteId} />
      </>
    );
  }
  if (!dados) return <Carregando />;
  const { lote, info, amostra } = dados;
  const comLeitura = linhas.filter((l) => numerosDaLinha(l).length > 0).length;

  function mudarValor(chave: number, ponto: number, valor: string) {
    setLinhas((atual) =>
      atual.map((l) => (l.chave === chave ? { ...l, valores: l.valores.map((v, i) => (i === ponto ? valor : v)) } : l)),
    );
  }

  function adicionarLinha() {
    contador.current += 1;
    const n = contador.current;
    setLinhas((atual) => [...atual, linhaVazia(lote.op, n)]);
  }

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    if (enviando) return;
    setErro(null);
    if (!geral) {
      setErro('Informe pelo menos uma leitura de dureza.');
      return;
    }
    const invalida = linhas.some((l) => l.valores.some((v) => situacaoDaLeitura(v, min, max) === 'invalido'));
    if (invalida) {
      setErro('Há leitura que não é número (use vírgula, ex.: 36,0). Corrija os campos marcados.');
      return;
    }
    setEnviando(true);
    try {
      const resposta = await api<RespostaRelatorio>(`/relatorios/dureza/${lote.id}`, {
        metodo: 'POST',
        corpo: {
          leituras: linhas.map((l) => ({ cp: l.cp, valores: l.valores })),
          equipamento_codigo: equipamento,
          executado_por: executor === '' ? null : executor,
          aprovado_por: aprovador === '' ? null : aprovador,
          data: data || null,
          data_aprovacao: dataAprovacao || null,
        },
      });
      if (resposta.status === 'APROVADO') avisos.sucesso(resposta.mensagem);
      else avisos.info(resposta.mensagem);
      navegar(`/lotes/${lote.id}`);
    } catch (falha) {
      setErro(falha instanceof ErroApi ? falha.message : mensagemDeErro(falha));
      setEnviando(false);
    }
  }

  return (
    <>
      <Cabecalho
        titulo="Relatório de Dureza HRC (RIP-35)"
        apoio={
          <>
            <Link to={`/lotes/${lote.id}`}>Lote {lote.numero}</Link> · O PDF é gerado pelo sistema e anexado na etapa Dureza HRC. A
            faixa aceitável e o status são calculados enquanto você digita as leituras.
          </>
        }
      />
      <div className="pilha rel-pagina">
        {dados.carga && (
          <Faixa tipo="info">
            <p>
              Este lote faz parte da <Link to={`/cargas-tt/${dados.carga.id}`}>carga {dados.carga.numero}</Link>. O RIP-35 é emitido um
              por lote: use os atalhos para fazer o dos outros lotes da mesma carga.
            </p>
            {dados.carga_outros_lotes.length > 0 ? (
              <p className="chips rel-atalhos">
                {dados.carga_outros_lotes.map((o) => (
                  <Link
                    key={o.id}
                    to={`/relatorios/dureza?lote=${o.id}`}
                    className={`chip ${o.ja_feito ? 'rel-feito' : ''}`}
                    title={o.ja_feito ? 'RIP-35 já aprovado' : 'Gerar o RIP-35 deste lote'}
                  >
                    {o.ja_feito ? '✓' : '▶'} OP {o.op} <SeloTipo tipo={o.tipo} /> {o.qtd} pç
                  </Link>
                ))}
              </p>
            ) : (
              <p className="dica">Nenhum outro lote PIN/BOX na carga.</p>
            )}
          </Faixa>
        )}

        <Resumo
          itens={[
            ['OP', <span className="mono">{lote.op}</span>],
            ['Lote', <span className="mono">{lote.numero}</span>],
            ['Tipo', <SeloTipo tipo={lote.tipo} />],
            ['Cliente', info.cliente],
            ['Código da peça', <span className="mono">{lote.coditem}</span>],
            ['Item', info.nome_peca],
            ['Desenho', info.desenho],
            ['Especificação', <strong>{info.especificacao}</strong>],
            ['Padrão de aceitação', info.padrao_aceitacao],
            ['Material', info.material],
          ]}
        />

        <form className="pilha" onSubmit={enviar} onKeyDown={enterVaiParaProximo} noValidate>
          <section className="cartao" aria-labelledby="titulo-pontos">
            <h2 id="titulo-pontos">Pontos de medição</h2>
            {dados.tem_imagem_pontos ? (
              <div className="rel-figura">
                <img
                  src={enderecoApi(`/recursos/relatorios/${dados.imagem_pontos}`)}
                  alt={`Pontos de medição da dureza na peça ${lote.tipo}`}
                />
              </div>
            ) : (
              <p className="dica">
                A imagem dos pontos ({dados.imagem_pontos}) não está na pasta de recursos do servidor. O PDF sai sem a figura.
              </p>
            )}
          </section>

          <section className="cartao" aria-labelledby="titulo-medicoes">
            <h2 id="titulo-medicoes">Medições (HRc)</h2>
            <p className="dica">
              Cada linha é um corpo de prova (DUR1, DUR2…). Digite as 5 leituras feitas nos pontos da imagem. Faixa aceitável:{' '}
              <strong>{info.especificacao}</strong>. Verde = dentro, vermelho = fora.
            </p>
            <p className="dica" id="dureza-amostra">
              {amostra.base === 'op' ? 'A OP' : 'O lote'} tem <strong>{amostra.qtd}</strong> {amostra.qtd === 1 ? 'peça' : 'peças'}: a
              amostra é de 10%, arredondado para cima ={' '}
              <strong>
                {amostra.linhas} {amostra.linhas === 1 ? 'corpo de prova' : 'corpos de prova'}
              </strong>
              . As linhas já vêm prontas. Linha sem leitura não entra no relatório.
            </p>
            <div className="tabela-rolagem">
              <table className="tabela rel-medicoes">
                <caption className="so-leitor">Leituras de dureza por corpo de prova</caption>
                <thead>
                  <tr>
                    <th scope="col">Código do CP</th>
                    {PONTOS.map((p) => (
                      <th scope="col" key={p} className="num">
                        Leitura {p + 1}
                      </th>
                    ))}
                    <th scope="col" className="num">
                      Média
                    </th>
                    <th scope="col">Faixa</th>
                    <th scope="col">Status</th>
                    <th scope="col">
                      <span className="so-leitor">Ações</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {linhas.map((linha, indice) => {
                    const numeros = numerosDaLinha(linha);
                    const status = numeros.length ? (numeros.every((n) => n >= min && n <= max) ? 'APROVADO' : 'REPROVADO') : '';
                    return (
                      <tr key={linha.chave}>
                        <td>
                          <input
                            type="text"
                            aria-label={`Código do corpo de prova ${indice + 1}`}
                            value={linha.cp}
                            maxLength={60}
                            onChange={(e) => setLinhas((atual) => atual.map((l) => (l.chave === linha.chave ? { ...l, cp: e.target.value } : l)))}
                          />
                        </td>
                        {PONTOS.map((p) => {
                          const situacao = situacaoDaLeitura(linha.valores[p], min, max);
                          return (
                            <td key={p}>
                              <input
                                type="text"
                                inputMode="decimal"
                                className={`rel-leitura rel-leitura-${situacao}`}
                                aria-label={`Leitura ${p + 1} do corpo de prova ${indice + 1}`}
                                aria-invalid={situacao === 'fora' || situacao === 'invalido'}
                                placeholder="HRc"
                                value={linha.valores[p]}
                                maxLength={8}
                                onChange={(e) => mudarValor(linha.chave, p, e.target.value)}
                              />
                            </td>
                          );
                        })}
                        <td className="num">{numeros.length ? decimal(numeros.reduce((a, b) => a + b, 0) / numeros.length) : '—'}</td>
                        <td className="mono">
                          {numeros.length ? `${decimal(Math.min(...numeros))}–${decimal(Math.max(...numeros))}` : '—'}
                        </td>
                        <td>
                          <StatusTexto status={status} />
                        </td>
                        <td>
                          {indice > 0 ? (
                            <button
                              type="button"
                              className="botao botao-pequeno botao-perigo-contorno"
                              onClick={() => setLinhas((atual) => atual.filter((l) => l.chave !== linha.chave))}
                              aria-label={`Tirar o corpo de prova ${linha.cp}`}
                            >
                              ×
                            </button>
                          ) : (
                            <span className="sub-linha">1ª peça</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="acoes">
              <button type="button" className="botao" onClick={adicionarLinha} disabled={linhas.length >= amostra.limite}>
                + Adicionar mais uma peça (DUR{contador.current + 1})
              </button>
              <span className="dica">Use para medir mais corpos de prova no mesmo lote.</span>
            </p>
            {geral && comLeitura < amostra.linhas && (
              <Faixa tipo="alerta">
                Há leitura em {comLeitura} de {amostra.linhas} {amostra.linhas === 1 ? 'peça' : 'peças'} da amostra (10% da{' '}
                {amostra.base === 'op' ? 'OP' : 'quantidade do lote'}). O relatório pode ser gerado assim, mas confira se faltou medir
                alguma peça.
              </Faixa>
            )}
            <div
              className={`rel-status ${geral ? (geral.aprovado ? 'rel-status-ok' : 'rel-status-erro') : ''}`}
              role="status"
              aria-live="polite"
            >
              <span>Status:</span>
              <strong>{geral ? (geral.aprovado ? 'APROVADO' : 'REPROVADO') : '—'}</strong>
              {geral && (
                <span className="sub-linha">
                  {geral.n} {geral.n === 1 ? 'medição' : 'medições'} em {comLeitura} {comLeitura === 1 ? 'peça' : 'peças'}, faixa{' '}
                  {decimal(geral.menor)} a {decimal(geral.maior)} HRc (especificação {min}–{max})
                </span>
              )}
            </div>
          </section>

          <section className="cartao" aria-labelledby="titulo-equipamento">
            <h2 id="titulo-equipamento">Equipamento</h2>
            <SeletorEquipamento
              id="dureza-durometro"
              rotulo="Durômetro utilizado"
              lista={dados.durometros}
              valor={equipamento}
              aoMudar={setEquipamento}
              obrigatorio
              vazio="Nenhum durômetro no cadastro de equipamentos: cadastre antes de gerar o RIP-35."
            />
          </section>

          <section className="cartao" aria-labelledby="titulo-responsaveis">
            <h2 id="titulo-responsaveis">Responsáveis e datas</h2>
            {dados.aprovadores.length === 0 && (
              <Faixa tipo="erro">Nenhum usuário ativo tem “pode aprovar”. Peça ao administrador para marcar quem aprova pela Qualidade.</Faixa>
            )}
            <div className="linha-campos">
              <SeletorPessoa
                id="dureza-executor"
                rotulo="Executado por"
                lista={dados.executores}
                valor={executor}
                aoMudar={setExecutor}
              />
              <SeletorPessoa
                id="dureza-aprovador"
                rotulo="Aprovado por"
                dica="No relatório sai o cargo do cadastro da pessoa (tela Usuários)."
                lista={dados.aprovadores}
                valor={aprovador}
                aoMudar={setAprovador}
              />
              <Campo rotulo="Data do ensaio" para="dureza-data" dica="Usada como data de emissão do laudo.">
                <input id="dureza-data" type="date" value={data} onChange={(e) => setData(e.target.value)} />
              </Campo>
              <Campo rotulo="Data de aprovação" para="dureza-data-aprovacao">
                <input id="dureza-data-aprovacao" type="date" value={dataAprovacao} onChange={(e) => setDataAprovacao(e.target.value)} />
              </Campo>
            </div>
          </section>

          <section className="cartao acoes-form rel-rodape">
            {erro && (
              <p className="erro-formulario" role="alert">
                {erro}
              </p>
            )}
            <div className="acoes">
              <button type="submit" className="botao botao-primario" disabled={enviando || dados.aprovadores.length === 0}>
                {enviando ? 'Gerando o PDF…' : 'Salvar e gerar PDF'}
              </button>
              <Link to={`/lotes/${lote.id}`} className="botao">
                Cancelar
              </Link>
              <span className="dica">
                O PDF é anexado na etapa Dureza HRC. Aprovado, a etapa é concluída; reprovado, abre uma não conformidade.
              </span>
            </div>
          </section>
        </form>
      </div>
    </>
  );
}
