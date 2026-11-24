import { useMemo } from 'react';
import { Campo } from '../../componentes/Campo';
import { Cabecalho, ErroCarga } from '../../componentes/Estados';
import type { Coluna } from '../../componentes/Tabela';
import { api } from '../../lib/api';
import { TRACO } from '../../lib/formato';
import { useSessao } from '../../lib/sessao';
import { useCarga } from '../../lib/useCarga';
import { CadastroSimples } from './CadastroSimples';
import type { ListasFixas, Prestador } from './tipos';

interface Formulario {
  codigo: string;
  razao_social: string;
  tipo_servico: string;
  contato: string;
  observacoes: string;
}

export function Prestadores() {
  const { pode } = useSessao();
  const listas = useCarga<ListasFixas>((sinal) => api('/cadastros/listas', { sinal }), []);
  const tipos = listas.dados?.tipos_prestador ?? [];

  const colunas = useMemo<Coluna<Prestador>[]>(
    () => [
      { chave: 'codigo', titulo: 'Código', mono: true, valor: (p) => p.codigo, celula: (p) => <strong>{p.codigo}</strong> },
      { chave: 'razao', titulo: 'Razão social', valor: (p) => p.razao_social },
      { chave: 'tipo', titulo: 'Tipo de serviço', valor: (p) => p.tipo_servico, celula: (p) => p.tipo_servico || TRACO },
      { chave: 'contato', titulo: 'Contato', valor: (p) => p.contato, celula: (p) => p.contato || TRACO },
      { chave: 'obs', titulo: 'Observações', valor: (p) => p.observacoes, celula: (p) => p.observacoes || TRACO },
    ],
    [],
  );

  return (
    <>
      <Cabecalho
        titulo="Prestadores de serviço"
        apoio="Laboratórios externos (tração/Charpy, NDT), tratamento térmico externo, revestimento (fosfato, oxidação negra) e serviços de calibração. Prestadores não têm login: é só o cadastro de referência."
      />
      {listas.erro && <ErroCarga mensagem={listas.erro} aoTentar={listas.recarregar} />}
      <CadastroSimples<Prestador, Formulario>
        rota="/prestadores"
        nome="prestador"
        podeEditar={pode.cadastros}
        colunas={colunas}
        textoBusca={(p) => `${p.codigo} ${p.razao_social} ${p.tipo_servico} ${p.contato}`}
        ordemInicial={{ chave: 'codigo', direcao: 'asc' }}
        efeitoInativar="O prestador deixa de aparecer para escolher nas etapas e nos envios."
        filtro={{ rotulo: 'Tipo de serviço', opcoes: tipos.map((t) => ({ valor: t, rotulo: t })), passa: (p, valor) => p.tipo_servico === valor }}
        novo={() => ({ codigo: '', razao_social: '', tipo_servico: tipos[0] ?? '', contato: '', observacoes: '' })}
        editar={(p) => ({ codigo: p.codigo, razao_social: p.razao_social, tipo_servico: p.tipo_servico, contato: p.contato, observacoes: p.observacoes })}
        envio={(f) => ({
          codigo: f.codigo.trim().toUpperCase(),
          razao_social: f.razao_social.trim(),
          tipo_servico: f.tipo_servico,
          contato: f.contato.trim(),
          observacoes: f.observacoes.trim(),
        })}
        campos={(f, mudar, item) => (
          <div className="form-grade">
            <Campo rotulo="Código" para="pr-codigo" obrigatorio classe="col-2" dica="Sempre em maiúsculas.">
              <input id="pr-codigo" type="text" className="mono cad-maiusculas" required maxLength={30} placeholder="Ex.: LAB-EXEMPLO"
                value={f.codigo} onChange={(e) => mudar({ codigo: e.target.value.toUpperCase() })} />
            </Campo>
            <Campo rotulo="Tipo de serviço" para="pr-tipo" obrigatorio classe="col-2">
              <select id="pr-tipo" required value={f.tipo_servico} onChange={(e) => mudar({ tipo_servico: e.target.value })}>
                {item && item.tipo_servico && !tipos.includes(item.tipo_servico) && (
                  <option value={item.tipo_servico}>{item.tipo_servico} (fora da lista)</option>
                )}
                {tipos.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </Campo>
            <Campo rotulo="Razão social" para="pr-razao" obrigatorio classe="col-4">
              <input id="pr-razao" type="text" required maxLength={160} placeholder="Ex.: Laboratório Exemplo Ltda." value={f.razao_social}
                onChange={(e) => mudar({ razao_social: e.target.value })} />
            </Campo>
            <Campo rotulo="Contato" para="pr-contato" classe="col-2">
              <input id="pr-contato" type="text" maxLength={200} placeholder="Telefone, e-mail, responsável…" value={f.contato}
                onChange={(e) => mudar({ contato: e.target.value })} />
            </Campo>
            <Campo rotulo="Observações" para="pr-obs" classe="col-2">
              <input id="pr-obs" type="text" maxLength={2000} value={f.observacoes} onChange={(e) => mudar({ observacoes: e.target.value })} />
            </Campo>
          </div>
        )}
      />
    </>
  );
}
