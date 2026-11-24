import { useMemo, useState } from 'react';
import { Campo } from '../../componentes/Campo';
import { EnvioArquivos } from '../../componentes/EnvioArquivos';
import { Cabecalho, Carregando, ErroCarga, Faixa, Vazio } from '../../componentes/Estados';
import { ModalFormulario } from '../../componentes/Modal';
import { SeloTipo } from '../../componentes/Selos';
import { TabelaOrdenavel, type Coluna } from '../../componentes/Tabela';
import { api, baixarArquivo, enviarArquivos, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { contemTermos, dataCurta, inteiro, TRACO } from '../../lib/formato';
import { useCarga } from '../../lib/useCarga';
import type { Comparacao, OrdemEntrada, OrdemProducao } from './tipos';

type FormOrdem = Record<keyof OrdemEntrada, string>;

const CAMPOS_TEXTO: { chave: keyof OrdemEntrada; rotulo: string; maximo: number; classe?: string; mono?: boolean; dica?: string }[] = [
  { chave: 'cliente', rotulo: 'Cliente', maximo: 160, classe: 'col-2' },
  { chave: 'coditem', rotulo: 'CODITEM', maximo: 40, mono: true },
  { chave: 'projeto', rotulo: 'Projeto', maximo: 120 },
  { chave: 'descricao', rotulo: 'Descrição', maximo: 300, classe: 'col-4' },
  { chave: 'nf', rotulo: 'NF', maximo: 40, mono: true },
  { chave: 'piv', rotulo: 'Pedido (PIV)', maximo: 40, mono: true },
  { chave: 'po', rotulo: 'PO (pedido do cliente)', maximo: 60, mono: true, classe: 'col-2' },
];

function formularioVazio(): FormOrdem {
  return {
    op: '', cliente: '', coditem: '', descricao: '', tipo: '', data_faturamento: '', nf: '', piv: '', qt_lote: '',
    qt_faturada: '', projeto: '', po: '',
  };
}

function formularioDe(o: OrdemProducao): FormOrdem {
  return {
    op: o.op, cliente: o.cliente, coditem: o.coditem, descricao: o.descricao, tipo: o.tipo ?? '',
    data_faturamento: o.data_faturamento ?? '', nf: o.nf, piv: o.piv, qt_lote: o.qt_lote === null ? '' : String(o.qt_lote),
    qt_faturada: o.qt_faturada === null ? '' : String(o.qt_faturada), projeto: o.projeto, po: o.po,
  };
}

function numeroOuNada(texto: string): number | null {
  const valor = Number.parseInt(texto, 10);
  return Number.isFinite(valor) ? valor : null;
}

function paraEnvio(f: FormOrdem): OrdemEntrada {
  return {
    op: f.op.trim(), cliente: f.cliente.trim(), coditem: f.coditem.trim(), descricao: f.descricao.trim(), tipo: f.tipo || null,
    data_faturamento: f.data_faturamento || null, nf: f.nf.trim(), piv: f.piv.trim(), qt_lote: numeroOuNada(f.qt_lote),
    qt_faturada: numeroOuNada(f.qt_faturada), projeto: f.projeto.trim(), po: f.po.trim(),
  };
}

// ---------------------------------------------------------------- importação da planilha nova

/**
 * Compara a planilha nova com o cadastro e inclui SÓ as OPs novas que o usuário confirmar
 * (legado: tela de atualização da planilha de OPs). OPs alteradas e as que não vieram aparecem só como aviso.
 */
function ImportarPlanilha({ aoFechar, aoIncluir }: { aoFechar: () => void; aoIncluir: () => void }) {
  const avisos = useAvisos();
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [comparacao, setComparacao] = useState<Comparacao | null>(null);
  const [marcadas, setMarcadas] = useState<Set<string>>(new Set());
  const [confirmando, setConfirmando] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function comparar() {
    if (!arquivos[0]) return;
    setErro(null);
    setEnviando(true);
    setConfirmando(false);
    try {
      const r = await enviarArquivos<Comparacao>('/ordens-producao/importacao/comparar', { arquivo: arquivos[0] });
      setComparacao(r);
      setMarcadas(new Set(r.novas.map((n) => n.op)));
    } catch (falha) {
      setComparacao(null);
      setErro(mensagemDeErro(falha));
    } finally {
      setEnviando(false);
    }
  }

  async function aplicar() {
    if (!arquivos[0] || marcadas.size === 0) return;
    setErro(null);
    setEnviando(true);
    try {
      const r = await enviarArquivos<{ incluidas: string[]; mensagem: string }>('/ordens-producao/importacao/aplicar', {
        arquivo: arquivos[0],
        ops: JSON.stringify([...marcadas]),
      });
      avisos.sucesso(r.mensagem);
      aoIncluir();
    } catch (falha) {
      setErro(mensagemDeErro(falha));
      setConfirmando(false);
    } finally {
      setEnviando(false);
    }
  }

  function marcar(op: string, sim: boolean) {
    setMarcadas((atual) => {
      const nova = new Set(atual);
      if (sim) nova.add(op);
      else nova.delete(op);
      return nova;
    });
    setConfirmando(false);
  }

  return (
    <section className="cartao cad-importacao" aria-labelledby="cad-titulo-importar">
      <div className="cartao-topo">
        <h2 id="cad-titulo-importar">Atualizar pelo arquivo do Excel</h2>
        <button type="button" className="botao" onClick={aoFechar}>
          Fechar
        </button>
      </div>
      <p className="apoio">
        Compara o cadastro atual com uma planilha nova (aba <strong>Dados</strong>, colunas A a L: Cliente, OP, CODITEM, Descrição,
        Classificação, Data Fat., NF, Pedido, QT_Lote, Qtd.Faturada, PROJETO, PO). Só as OPs <strong>novas</strong> são incluídas, e
        só as que você confirmar. OPs alteradas ou que não vieram na planilha são só mostradas: nada é alterado nem removido sem
        você decidir (para mudar uma OP existente, use “Editar” na tabela).
      </p>
      <EnvioArquivos
        arquivos={arquivos}
        aoMudar={(lista) => {
          setArquivos(lista);
          setComparacao(null);
          setConfirmando(false);
        }}
        aceita=".xlsx"
        multiplos={false}
        limiteMb={10}
        rotulo="Planilha nova (.xlsx)"
        dica="Arquivo do Excel, até 10 MB."
        desabilitado={enviando}
      />
      <div className="acoes">
        <button type="button" className="botao botao-primario" onClick={() => void comparar()} disabled={!arquivos[0] || enviando}>
          {enviando && !comparacao ? 'Comparando…' : 'Comparar'}
        </button>
      </div>
      {erro && (
        <p className="erro-formulario" role="alert">
          {erro}
        </p>
      )}

      {comparacao && (
        <div className="cad-resultado">
          <div className="cad-contagens">
            <div className="cad-contagem cad-contagem-ok">
              <strong>{inteiro(comparacao.novas.length)}</strong>
              <span>OPs novas</span>
            </div>
            <div className={`cad-contagem ${comparacao.alteradas.length ? 'cad-contagem-alerta' : ''}`}>
              <strong>{inteiro(comparacao.alteradas.length)}</strong>
              <span>OPs alteradas</span>
            </div>
            <div className={`cad-contagem ${comparacao.ausentes.length ? 'cad-contagem-erro' : ''}`}>
              <strong>{inteiro(comparacao.ausentes.length)}</strong>
              <span>No cadastro e não na planilha</span>
            </div>
            <div className="cad-contagem">
              <strong>{inteiro(comparacao.iguais)}</strong>
              <span>Iguais</span>
            </div>
          </div>

          {comparacao.avisos.length > 0 && (
            <Faixa tipo="info">
              <strong>Avisos da leitura da planilha:</strong>
              <ul className="cad-lista">
                {comparacao.avisos.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </Faixa>
          )}

          {comparacao.novas.length > 0 && (
            <div>
              <h3>OPs novas: serão incluídas as marcadas</h3>
              <div className="tabela-rolagem">
                <table className="tabela">
                  <caption className="so-leitor">OPs novas da planilha</caption>
                  <thead>
                    <tr>
                      <th scope="col">
                        <input
                          type="checkbox"
                          aria-label="Marcar todas"
                          checked={marcadas.size === comparacao.novas.length}
                          onChange={(e) => {
                            setMarcadas(e.target.checked ? new Set(comparacao.novas.map((n) => n.op)) : new Set());
                            setConfirmando(false);
                          }}
                        />
                      </th>
                      <th scope="col">OP</th>
                      <th scope="col">Cliente</th>
                      <th scope="col">CODITEM</th>
                      <th scope="col">Classificação</th>
                      <th scope="col" className="num">
                        QT_Lote
                      </th>
                      <th scope="col">Projeto</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparacao.novas.map((n) => (
                      <tr key={n.op}>
                        <td>
                          <input type="checkbox" aria-label={`Incluir a OP ${n.op}`} checked={marcadas.has(n.op)}
                            onChange={(e) => marcar(n.op, e.target.checked)} />
                        </td>
                        <td className="mono">
                          <strong>{n.op}</strong>
                        </td>
                        <td>{n.cliente || TRACO}</td>
                        <td className="mono">{n.coditem || TRACO}</td>
                        <td>{n.tipo ? <SeloTipo tipo={n.tipo} /> : TRACO}</td>
                        <td className="num">{inteiro(n.qt_lote)}</td>
                        <td>{n.projeto || TRACO}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {comparacao.alteradas.length > 0 && (
            <div>
              <h3 className="texto-alerta">OPs alteradas: não são aplicadas, só para revisão</h3>
              <ul className="cad-lista cad-alteradas">
                {comparacao.alteradas.map((a) => (
                  <li key={a.op}>
                    <strong>OP {a.op}:</strong>{' '}
                    {Object.entries(a.diferencas).map(([campo, [antes, depois]], i) => (
                      <span key={campo}>
                        {i > 0 && ', '}
                        <code>{campo}</code>: “{antes || TRACO}” → “{depois || TRACO}”
                      </span>
                    ))}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {comparacao.ausentes.length > 0 && (
            <div>
              <h3 className="texto-erro">OPs do cadastro que não aparecem na planilha nova</h3>
              <p>{comparacao.ausentes.join(', ')}</p>
              <p className="dica">Não foram removidas: confira se era mesmo para tirar ou se é só um recorte diferente da planilha.</p>
            </div>
          )}

          {comparacao.novas.length === 0 ? (
            <p className="dica">Nenhuma OP nova para incluir.</p>
          ) : !confirmando ? (
            <div className="acoes">
              <button type="button" className="botao botao-primario" disabled={marcadas.size === 0 || enviando} onClick={() => setConfirmando(true)}>
                Incluir {inteiro(marcadas.size)} OP(s) nova(s)
              </button>
            </div>
          ) : (
            <Faixa tipo="alerta" papel="alert">
              <p>
                Incluir <strong>{inteiro(marcadas.size)} OP(s) nova(s)</strong> no cadastro? As OPs alteradas e as que não vieram na
                planilha não serão tocadas.
              </p>
              <div className="acoes">
                <button type="button" className="botao botao-primario" disabled={enviando} onClick={() => void aplicar()}>
                  {enviando ? 'Incluindo…' : 'Sim, incluir'}
                </button>
                <button type="button" className="botao" disabled={enviando} onClick={() => setConfirmando(false)}>
                  Voltar
                </button>
              </div>
            </Faixa>
          )}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- tela

export function OrdensProducao() {
  const avisos = useAvisos();
  const lista = useCarga<OrdemProducao[]>((sinal) => api('/ordens-producao', { sinal }), []);
  const [busca, setBusca] = useState('');
  const [tipo, setTipo] = useState('');
  const [importando, setImportando] = useState(false);
  const [exportando, setExportando] = useState(false);
  const [edicao, setEdicao] = useState<{ item: OrdemProducao | null; f: FormOrdem } | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const filtradas = useMemo(
    () =>
      (lista.dados ?? []).filter(
        (o) =>
          (!tipo || (tipo === 'sem' ? !o.tipo : o.tipo === tipo)) &&
          contemTermos(`${o.op} ${o.cliente} ${o.coditem} ${o.descricao} ${o.piv} ${o.po} ${o.projeto} ${o.nf}`, busca),
      ),
    [lista.dados, busca, tipo],
  );

  const colunas = useMemo<Coluna<OrdemProducao>[]>(
    () => [
      { chave: 'op', titulo: 'OP', mono: true, valor: (o) => o.op, celula: (o) => <strong>{o.op}</strong> },
      { chave: 'cliente', titulo: 'Cliente', valor: (o) => o.cliente, celula: (o) => o.cliente || TRACO },
      { chave: 'coditem', titulo: 'CODITEM', mono: true, valor: (o) => o.coditem, celula: (o) => o.coditem || TRACO },
      { chave: 'descricao', titulo: 'Descrição', valor: (o) => o.descricao, celula: (o) => <span className="cad-descricao">{o.descricao || TRACO}</span> },
      { chave: 'tipo', titulo: 'Tipo', valor: (o) => o.tipo, celula: (o) => (o.tipo ? <SeloTipo tipo={o.tipo} /> : TRACO) },
      { chave: 'data', titulo: 'Data fat.', valor: (o) => o.data_faturamento, celula: (o) => dataCurta(o.data_faturamento) },
      { chave: 'nf', titulo: 'NF', mono: true, valor: (o) => o.nf, celula: (o) => o.nf || TRACO },
      { chave: 'piv', titulo: 'Pedido (PIV)', mono: true, valor: (o) => o.piv, celula: (o) => o.piv || TRACO },
      { chave: 'qt_lote', titulo: 'QT lote', numerica: true, valor: (o) => o.qt_lote, celula: (o) => inteiro(o.qt_lote) },
      { chave: 'qt_fat', titulo: 'Qtd. faturada', numerica: true, valor: (o) => o.qt_faturada, celula: (o) => inteiro(o.qt_faturada) },
      { chave: 'projeto', titulo: 'Projeto', valor: (o) => o.projeto, celula: (o) => o.projeto || TRACO },
      { chave: 'po', titulo: 'PO', mono: true, valor: (o) => o.po, celula: (o) => o.po || TRACO },
      { chave: 'lotes', titulo: 'Lotes', numerica: true, dica: 'Lotes do sistema com esta OP', valor: (o) => o.lotes, celula: (o) => inteiro(o.lotes) },
      {
        chave: '_acoes',
        titulo: 'Ações',
        ordenavel: false,
        valor: () => null,
        celula: (o) => (
          <button type="button" className="botao botao-pequeno" onClick={() => { setErro(null); setEdicao({ item: o, f: formularioDe(o) }); }}>
            Editar
          </button>
        ),
      },
    ],
    [],
  );

  async function exportar() {
    setExportando(true);
    try {
      await baixarArquivo('/ordens-producao/exportar');
    } catch (falha) {
      avisos.erro(mensagemDeErro(falha));
    } finally {
      setExportando(false);
    }
  }

  async function salvar() {
    if (!edicao) return;
    setErro(null);
    setEnviando(true);
    try {
      const corpo = paraEnvio(edicao.f);
      if (edicao.item) await api(`/ordens-producao/${edicao.item.id}`, { metodo: 'PUT', corpo });
      else await api('/ordens-producao', { metodo: 'POST', corpo });
      avisos.sucesso(`OP ${corpo.op} gravada.`);
      setEdicao(null);
      lista.recarregar();
    } catch (falha) {
      setErro(mensagemDeErro(falha));
    } finally {
      setEnviando(false);
    }
  }

  const mudar = (parcial: Partial<FormOrdem>) => setEdicao((atual) => (atual ? { ...atual, f: { ...atual.f, ...parcial } } : atual));
  const opTravada = !!edicao?.item && edicao.item.lotes > 0;

  return (
    <>
      <Cabecalho
        titulo="Ordens de produção"
        apoio="Cadastro mestre das OPs (cliente, item, quantidade, pedidos), que era a planilha de OPs. É dele que vêm o CODITEM e os dados do pedido nas telas de lote, OF e databook."
      >
        <button type="button" className="botao" onClick={() => void exportar()} disabled={exportando}>
          {exportando ? 'Gerando…' : 'Exportar para Excel'}
        </button>
        <button type="button" className="botao" onClick={() => setImportando(true)} disabled={importando}>
          Atualizar pelo Excel
        </button>
        <button type="button" className="botao botao-primario" onClick={() => { setErro(null); setEdicao({ item: null, f: formularioVazio() }); }}>
          Nova OP
        </button>
      </Cabecalho>

      {importando && (
        <ImportarPlanilha
          aoFechar={() => setImportando(false)}
          aoIncluir={() => {
            setImportando(false);
            lista.recarregar();
          }}
        />
      )}

      <section className="cartao" aria-label="Ordens de produção cadastradas">
        <div className="filtros">
          <div className="campo campo-busca">
            <label htmlFor="op-busca">Buscar</label>
            <input id="op-busca" type="search" placeholder="OP, cliente, item, pedido…" value={busca} onChange={(e) => setBusca(e.target.value)} />
          </div>
          <div className="campo">
            <label htmlFor="op-tipo">Tipo</label>
            <select id="op-tipo" value={tipo} onChange={(e) => setTipo(e.target.value)}>
              <option value="">Todos</option>
              <option value="PIN">PIN</option>
              <option value="BOX">BOX</option>
              <option value="ARK">ARK</option>
              <option value="sem">Sem classificação</option>
            </select>
          </div>
        </div>
        {lista.erro && <ErroCarga mensagem={lista.erro} aoTentar={lista.recarregar} />}
        {!lista.dados && lista.carregando && <Carregando />}
        {lista.dados && filtradas.length === 0 && (
          <Vazio titulo={lista.dados.length === 0 ? 'Nenhuma OP cadastrada ainda.' : 'Nenhuma OP com esses filtros.'} />
        )}
        {lista.dados && filtradas.length > 0 && (
          <div className={lista.carregando ? 'recarregando' : undefined}>
            <TabelaOrdenavel legenda="Ordens de produção" colunas={colunas} linhas={filtradas} chaveLinha={(o) => o.id} limite={100}
              ordemInicial={{ chave: 'op', direcao: 'desc' }} />
            <p className="contagem">
              {inteiro(filtradas.length)} de {inteiro(lista.dados.length)}
            </p>
          </div>
        )}
      </section>

      {edicao && (
        <ModalFormulario
          titulo={edicao.item ? `Editar OP ${edicao.item.op}` : 'Nova OP'}
          largura="larga"
          aoFechar={() => setEdicao(null)}
          aoEnviar={() => void salvar()}
          enviando={enviando}
          erro={erro}
        >
          <div className="form-grade">
            <Campo rotulo="OP" para="op-numero" obrigatorio
              dica={opTravada ? `Já há ${edicao.item?.lotes} lote(s) com esta OP: o número não pode mudar.` : undefined}>
              <input id="op-numero" type="text" className="mono" required maxLength={20} disabled={opTravada} value={edicao.f.op}
                onChange={(e) => mudar({ op: e.target.value })} />
            </Campo>
            <Campo rotulo="Classificação" para="op-classificacao">
              <select id="op-classificacao" value={edicao.f.tipo} onChange={(e) => mudar({ tipo: e.target.value })}>
                <option value="">(sem classificação)</option>
                <option value="PIN">PIN</option>
                <option value="BOX">BOX</option>
                <option value="ARK">ARK</option>
              </select>
            </Campo>
            {CAMPOS_TEXTO.map((c) => (
              <Campo key={c.chave} rotulo={c.rotulo} para={`op-${c.chave}`} classe={c.classe} dica={c.dica}>
                <input id={`op-${c.chave}`} type="text" className={c.mono ? 'mono' : undefined} maxLength={c.maximo} value={edicao.f[c.chave]}
                  onChange={(e) => mudar({ [c.chave]: e.target.value } as Partial<FormOrdem>)} />
              </Campo>
            ))}
            <Campo rotulo="Data de faturamento" para="op-data">
              <input id="op-data" type="date" value={edicao.f.data_faturamento} onChange={(e) => mudar({ data_faturamento: e.target.value })} />
            </Campo>
            <Campo rotulo="QT lote" para="op-qt-lote">
              <input id="op-qt-lote" type="number" inputMode="numeric" className="num" min={0} step={1} value={edicao.f.qt_lote}
                onChange={(e) => mudar({ qt_lote: e.target.value })} />
            </Campo>
            <Campo rotulo="Qtd. faturada" para="op-qt-fat">
              <input id="op-qt-fat" type="number" inputMode="numeric" className="num" min={0} step={1} value={edicao.f.qt_faturada}
                onChange={(e) => mudar({ qt_faturada: e.target.value })} />
            </Campo>
          </div>
        </ModalFormulario>
      )}
    </>
  );
}
