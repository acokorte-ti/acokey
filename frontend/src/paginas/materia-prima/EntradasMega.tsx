import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Carregando, ErroCarga, Vazio } from '../../componentes/Estados';
import { SeloTipo } from '../../componentes/Selos';
import { api } from '../../lib/api';
import { dataCurta, inteiro, TRACO } from '../../lib/formato';
import { useCarga } from '../../lib/useCarga';
import type { EntradaMega } from './tipos';

/**
 * Entradas de peças fundidas lidas no Mega na hora (só leitura). Cada uma mostra o que já foi lançado aqui e quanto
 * falta; "Lançar corrida" abre o formulário com NF, fornecedor, data, tipo e QT-FUND. preenchidos.
 */
export function EntradasMega({ aoLancar, aoFechar }: { aoLancar: (entrada: EntradaMega) => void; aoFechar: () => void }) {
  const consulta = useCarga<{ desde: string; entradas: EntradaMega[] }>((sinal) => api('/materia-prima/entradas-mega', { sinal }), []);
  const [todas, setTodas] = useState(false);
  const visiveis = useMemo(() => (consulta.dados?.entradas ?? []).filter((e) => todas || e.falta > 0), [consulta.dados, todas]);

  return (
    <section className="cartao mp-mega" aria-labelledby="mp-titulo-mega">
      <div className="cartao-topo">
        <h2 id="mp-titulo-mega">Entradas de peças fundidas no Mega</h2>
        <button type="button" className="botao" onClick={aoFechar}>
          Fechar
        </button>
      </div>
      <p className="apoio">
        Notas de entrada dos últimos 12 meses{consulta.dados ? ` (desde ${dataCurta(consulta.dados.desde)})` : ''}. NF, fornecedor, data, tipo e
        quantidade vêm da nota; a <strong>corrida não existe no Mega</strong> e é digitada a partir do certificado. Se a nota tiver mais de uma
        corrida, lance uma de cada vez com a quantidade de cada uma.
      </p>
      <label className="mp-mega-todas">
        <input type="checkbox" checked={todas} onChange={(e) => setTodas(e.target.checked)} /> Mostrar também as já lançadas
      </label>

      {consulta.erro && <ErroCarga mensagem={consulta.erro} aoTentar={consulta.recarregar} />}
      {!consulta.dados && consulta.carregando && <Carregando />}
      {consulta.dados && visiveis.length === 0 && (
        <Vazio titulo={consulta.dados.entradas.length === 0 ? 'Nenhuma entrada de peças fundidas no período.' : 'Todas as entradas já foram lançadas.'} />
      )}
      {consulta.dados && visiveis.length > 0 && (
        <div className="tabela-rolagem">
          <table className="tabela">
            <caption className="so-leitor">Entradas de peças fundidas no Mega</caption>
            <thead>
              <tr>
                <th scope="col">Entrada</th>
                <th scope="col">NF</th>
                <th scope="col">Fornecedor</th>
                <th scope="col">Peça</th>
                <th scope="col">Tipo</th>
                <th scope="col" className="num">
                  Qtd. na nota
                </th>
                <th scope="col">Já lançado</th>
                <th scope="col" className="num">
                  Falta
                </th>
                <th scope="col">
                  <span className="so-leitor">Ações</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {visiveis.map((e) => (
                <tr key={e.chave}>
                  <td>{dataCurta(e.entrada)}</td>
                  <td className="mono">
                    <strong>{e.nf}</strong>
                  </td>
                  <td>{e.fornecedor || TRACO}</td>
                  <td>
                    <span className="mp-mega-peca">{e.descricao}</span>
                  </td>
                  <td>{e.tipo ? <SeloTipo tipo={e.tipo} /> : TRACO}</td>
                  <td className="num">
                    {inteiro(e.qtde)} {e.unidade.toLowerCase()}
                  </td>
                  <td>
                    {e.corridas.length === 0
                      ? TRACO
                      : e.corridas.map((c, i) => (
                          <span key={c.id}>
                            {i > 0 && ', '}
                            <Link className="link-forte mono" to={`/materia-prima/${c.id}`}>
                              {c.corrida}
                            </Link>
                          </span>
                        ))}
                  </td>
                  <td className="num">
                    <strong>{inteiro(e.falta)}</strong>
                  </td>
                  <td>
                    {e.falta > 0 && e.tipo ? (
                      <button type="button" className="botao botao-pequeno botao-primario" onClick={() => aoLancar(e)}>
                        Lançar corrida
                      </button>
                    ) : (
                      <span className="selo selo-ok">Lançada</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
