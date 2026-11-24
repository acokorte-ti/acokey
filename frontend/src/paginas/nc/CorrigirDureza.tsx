import { useMemo, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Cabecalho, Carregando, ErroCarga, Faixa, Vazio } from '../../componentes/Estados';
import { Confirmacao } from '../../componentes/Modal';
import { SeloTipo } from '../../componentes/Selos';
import { api, ErroApi, mensagemDeErro } from '../../lib/api';
import { useAvisos } from '../../lib/avisos';
import { dataHoraLocal, TRACO } from '../../lib/formato';
import { enterVaiParaProximo } from '../../lib/teclado';
import { useCarga } from '../../lib/useCarga';
import type { DetalheNc, RespostaCorrecao, TelaCorrecaoDureza } from './tipos';

/** O sistema antigo mostrava 5 leituras por corpo de prova; se algum CP tiver mais, mostra todas. */
const LEITURAS_MINIMAS = 5;

interface Linha {
  cp: string;
  valores: string[];
}

interface Dados {
  nc: DetalheNc;
  tela: TelaCorrecaoDureza;
}

/** 36.5 -> "36,5" */
function mostrar(valor: number): string {
  return String(valor).replace('.', ',');
}

/** "36,5" -> 36.5; "" -> null; texto que não é número -> NaN. */
function ler(texto: string): number | null {
  const limpo = texto.trim().replace(',', '.');
  if (!limpo) return null;
  return /^-?\d+(\.\d+)?$/.test(limpo) ? Number(limpo) : Number.NaN;
}

type Situacao = 'ok' | 'fora' | 'invalido' | '';

function situacao(texto: string, minimo: number | null, maximo: number | null): Situacao {
  const valor = ler(texto);
  if (valor === null) return '';
  if (Number.isNaN(valor)) return 'invalido';
  if (minimo === null || maximo === null) return '';
  return valor < minimo || valor > maximo ? 'fora' : 'ok';
}

function Formulario({ dados }: { dados: Dados }) {
  const { nc, tela } = dados;
  const navegar = useNavigate();
  const avisos = useAvisos();
  const colunas = Math.max(LEITURAS_MINIMAS, ...tela.leituras.map((l) => l.valores.length));
  const [linhas, setLinhas] = useState<Linha[]>(() =>
    tela.leituras.map((l) => ({
      cp: l.cp,
      valores: Array.from({ length: colunas }, (_, j) => (j < l.valores.length ? mostrar(l.valores[j]) : '')),
    })),
  );
  const [erro, setErro] = useState<string | null>(null);
  const [confirmando, setConfirmando] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const { esp_min: minimo, esp_max: maximo } = tela;

  const resumo = useMemo(() => {
    const valores: number[] = [];
    let invalidos = 0;
    for (const linha of linhas) {
      for (const texto of linha.valores) {
        const v = ler(texto);
        if (v === null) continue;
        if (Number.isNaN(v)) invalidos += 1;
        else valores.push(v);
      }
    }
    const fora = minimo === null || maximo === null ? 0 : valores.filter((v) => v < minimo || v > maximo).length;
    return {
      valores,
      invalidos,
      fora,
      aprovado: valores.length > 0 && invalidos === 0 && fora === 0,
      minimoLido: valores.length ? Math.min(...valores) : null,
      maximoLido: valores.length ? Math.max(...valores) : null,
      media: valores.length ? valores.reduce((a, b) => a + b, 0) / valores.length : null,
    };
  }, [linhas, minimo, maximo]);

  function mudarValor(i: number, j: number, texto: string) {
    setLinhas((atual) => atual.map((l, k) => (k === i ? { ...l, valores: l.valores.map((v, m) => (m === j ? texto : v)) } : l)));
  }

  function mudarCp(i: number, texto: string) {
    setLinhas((atual) => atual.map((l, k) => (k === i ? { ...l, cp: texto } : l)));
  }

  function pedirConfirmacao(evento: FormEvent) {
    evento.preventDefault();
    if (resumo.invalidos > 0) {
      setErro('Valores de dureza inválidos — use números (ex.: 36,0). Os campos com problema estão marcados.');
    } else if (resumo.valores.length === 0) {
      setErro('Informe pelo menos uma leitura.');
    } else {
      setErro(null);
      setConfirmando(true);
    }
  }

  async function salvar() {
    setEnviando(true);
    try {
      const resposta = await api<RespostaCorrecao>(`/registros/${tela.registro.id}/corrigir-dureza`, {
        metodo: 'POST',
        corpo: { nc_id: nc.id, leituras: linhas.map((l) => ({ cp: l.cp, valores: l.valores })) },
      });
      setConfirmando(false);
      if (resposta.status === 'aprovado') {
        avisos.sucesso(resposta.mensagem);
        navegar(`/lotes/${resposta.lote_id}`);
      } else {
        avisos.info(resposta.mensagem);
        navegar(`/nao-conformidades/${nc.id}`);
      }
    } catch (e) {
      setConfirmando(false);
      setErro(mensagemDeErro(e));
    } finally {
      setEnviando(false);
    }
  }

  if (minimo === null || maximo === null) {
    return (
      <Faixa tipo="erro">
        <strong>Especificação não cadastrada</strong> para o tipo {tela.lote.tipo}: não dá para recalcular o resultado automaticamente.
        Cadastre a dureza mínima e máxima em <Link to="/especificacoes">Especificações</Link> antes de corrigir.
      </Faixa>
    );
  }
  if (tela.leituras.length === 0) {
    return (
      <Vazio titulo="Não encontrei leituras de dureza neste registro.">
        Volte à NC, anule-a (erro de digitação) e grave um novo registro da etapa.
      </Vazio>
    );
  }

  return (
    <>
      <Faixa tipo="info">
        Especificação para {tela.lote.tipo}: dureza entre <strong>{mostrar(minimo)}</strong> e <strong>{mostrar(maximo)}</strong> HRc. Valores
        fora dessa faixa aparecem em vermelho.
      </Faixa>
      <form onSubmit={pedirConfirmacao} onKeyDown={enterVaiParaProximo} className="cartao" aria-labelledby="nc-titulo-leituras" noValidate>
        <h2 id="nc-titulo-leituras">Leituras por corpo de prova</h2>
        <p className="dica">Corrija os valores errados. Cada coluna é uma leitura HRc feita no corpo de prova (CP). Deixe em branco onde não houve leitura.</p>
        <div className="tabela-rolagem">
          <table className="tabela nc-leituras">
            <caption className="so-leitor">Leituras de dureza</caption>
            <thead>
              <tr>
                <th scope="col">CP</th>
                {Array.from({ length: colunas }, (_, j) => (
                  <th key={j} scope="col" className="num">
                    Leitura {j + 1}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {linhas.map((linha, i) => (
                <tr key={i}>
                  <td>
                    <input
                      type="text"
                      className="nc-cp"
                      aria-label={`Nome do CP ${i + 1}`}
                      value={linha.cp}
                      maxLength={60}
                      onChange={(e) => mudarCp(i, e.target.value)}
                    />
                  </td>
                  {linha.valores.map((texto, j) => {
                    const s = situacao(texto, minimo, maximo);
                    return (
                      <td key={j}>
                        <input
                          type="text"
                          inputMode="decimal"
                          className={`nc-leitura ${s ? `nc-leitura-${s}` : ''}`}
                          aria-label={`${linha.cp || `CP ${i + 1}`}, leitura ${j + 1}`}
                          aria-invalid={s === 'invalido' || s === 'fora' ? true : undefined}
                          value={texto}
                          onChange={(e) => mudarValor(i, j, e.target.value)}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className={`nc-previa ${resumo.aprovado ? 'nc-previa-ok' : 'nc-previa-fora'}`} aria-live="polite">
          {resumo.valores.length === 0 ? (
            'Nenhuma leitura preenchida.'
          ) : (
            <>
              {resumo.valores.length} leitura(s) · mínimo {mostrar(resumo.minimoLido ?? 0)} · máximo {mostrar(resumo.maximoLido ?? 0)} · média{' '}
              {(resumo.media ?? 0).toFixed(1).replace('.', ',')} HRc —{' '}
              <strong>
                {resumo.invalidos > 0
                  ? 'há valores que não são números'
                  : resumo.aprovado
                    ? 'com estes valores o registro fica APROVADO'
                    : `continua REPROVADO (${resumo.fora} fora da faixa)`}
              </strong>
            </>
          )}
        </p>
        {erro && (
          <p className="erro-formulario" role="alert">
            {erro}
          </p>
        )}
        <div className="acoes acoes-form">
          <button type="submit" className="botao botao-primario" disabled={enviando}>
            Salvar correção
          </button>
          <Link to={`/nao-conformidades/${nc.id}`} className="botao">
            Cancelar
          </Link>
        </div>
      </form>
      {confirmando && (
        <Confirmacao
          titulo="Salvar a correção"
          rotuloConfirmar="Salvar correção"
          aoConfirmar={salvar}
          aoFechar={() => setConfirmando(false)}
          enviando={enviando}
        >
          {resumo.aprovado ? (
            <p>
              O registro passa para <strong>APROVADO</strong>
              {tela.nc ? ` e a ${tela.nc.numero} é encerrada automaticamente (anulada por erro de digitação)` : ''}. Os valores de antes ficam
              guardados na auditoria.
            </p>
          ) : (
            <p>
              Os valores serão atualizados, mas o registro continua <strong>REPROVADO</strong> e a NC segue aberta para você decidir a disposição.
              Os valores de antes ficam guardados na auditoria.
            </p>
          )}
        </Confirmacao>
      )}
    </>
  );
}

/** Correção dos valores de dureza digitados errado (só quem pode aprovar; só registro de dureza reprovado). */
export function CorrigirDureza() {
  const { id = '' } = useParams();
  const idValido = /^\d+$/.test(id);
  const carga = useCarga<Dados>(async (sinal) => {
    if (!idValido) throw new ErroApi(404, 'Não conformidade não encontrada.');
    const nc = await api<DetalheNc>(`/nao-conformidades/${id}`, { sinal });
    if (!nc.registro) throw new ErroApi(404, 'Esta NC não tem registro ligado a ela.');
    const tela = await api<TelaCorrecaoDureza>(`/registros/${nc.registro.id}/corrigir-dureza`, { sinal });
    return { nc, tela };
  }, [id]);
  const dados = carga.dados && carga.dados.nc.id === Number(id) ? carga.dados : null;

  return (
    <>
      <Cabecalho
        titulo="Corrigir valores digitados — Dureza HRC"
        apoio={
          dados ? (
            <>
              OP <span className="mono">{dados.tela.lote.op || TRACO}</span> · Lote <span className="mono">{dados.tela.lote.numero}</span>{' '}
              <SeloTipo tipo={dados.tela.lote.tipo} /> · Registro #{dados.tela.registro.id} (reprovado em {dataHoraLocal(dados.tela.registro.quando)}
              {dados.tela.registro.responsavel && <> por {dados.tela.registro.responsavel}</>})
            </>
          ) : undefined
        }
      >
        <Link to={`/nao-conformidades/${idValido ? id : ''}`} className="botao">
          ← Voltar à {dados ? dados.nc.numero : 'NC'}
        </Link>
      </Cabecalho>

      <Faixa tipo="alerta">
        <strong>Atenção:</strong> use esta tela só quando os valores foram digitados errado (ex.: "2,5" em vez de "25"). Ao salvar:
        <ul className="nc-lista-regras">
          <li>
            se os novos valores ficarem <strong>dentro da especificação</strong>, o registro passa para APROVADO e a NC é encerrada
            automaticamente (anulada por erro de digitação);
          </li>
          <li>
            se continuarem <strong>fora da especificação</strong>, os valores são atualizados, mas o registro segue reprovado e você decide a
            disposição na NC.
          </li>
        </ul>
        O valor de antes da correção fica registrado na auditoria.
      </Faixa>

      {carga.erro && <ErroCarga mensagem={carga.erro} aoTentar={idValido ? carga.recarregar : undefined} />}
      {!carga.erro && !dados && <Carregando />}
      {dados && <Formulario key={dados.tela.registro.id} dados={dados} />}
    </>
  );
}
