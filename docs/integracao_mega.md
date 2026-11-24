# Integração com o ERP Mega — mapeamento do AçoKey Q

Mapeado em 24/11/2026 a partir do system-lab, com o usuário `acokey_ro` (somente leitura). OP, item, cliente e
pedido seguem o mapeamento já validado do EstoqueACK (`estoqueack/docs/integracao_mega.md`). Esquema `ACOKORTE`,
filial de Itu `FIL_IN_CODIGO = 3`.

## De onde vem cada dado das ordens de produção (antiga planilha de OPs)

| Dado | Mega | Validação (amostra da planilha) |
|---|---|---|
| OP | `PRO_ORDENS.ORD_IN_CODIGO` | 8/8 encontradas |
| Item (CODITEM) | `PRO_ORDENS.PRO_IN_CODIGO` | 8/8 |
| Descrição | `EST_PRODUTOS.PRO_ST_DESCRICAO` | — |
| Classificação PIN/BOX/ARK | calculada pela descrição (não vem do Mega) | — |
| Quantidade da OP | `PRO_ORDENS.ORD_RE_QTDE_ORDEM` | 6/8: em 2 OPs a planilha tem a quantidade do lote, menor que a da OP (confirmar com a Qualidade) |
| Situação da OP | `PRO_ORDENS.ORD_ST_SITUACAO` (`AB` aberta, `EN` encerrada, `CA` cancelada...) | — |
| Pedido (PIV) | `PRO_ORIGEM` (`ORI_CH_TIPOORIGEM = 'D'`) → `VEN_PEDIDOVENDA.PED_IN_CODIGO`; sem origem, `PRO_ORDENS.ORD_ST_ALTERNATIVO` | 6/6 |
| Cliente | `VEN_PEDIDOVENDA` (`CLI_*`) → `GLO_AGENTES.AGN_ST_FANTASIA` | — |
| PO (pedido do cliente) | `VEN_ITEMPEDIDOVENDA.ITP_ST_PEDIDOCLIENTE` (também `VEN_ITEMNOTAFISCAL.ITN_ST_PEDIDOCLIENTE`) | presente nas 6 (a planilha não tinha) |
| NF de saída e data | `VEN_ITEMPEDI_VEN_ITEMNOT` (vínculo item do pedido ↔ item da nota) → `VEN_NOTAFISCAL.NOT_IN_NUMERO`, `NOT_DT_EMISSAO` | 6/6 NF e data |
| Quantidade faturada | por nota: `VEN_ITEMPEDI_VEN_ITEMNOT.IPN_RE_QUANTIDADE`; total do item do pedido: `VEN_ITEMPEDIDOVENDA.ITP_RE_QTDEFATURADA` | 5/6 com o total do pedido; usar a do vínculo |
| Nota cancelada | `VEN_NOTAFISCAL.NOT_CH_SITUACAO`, `NOT_DT_CANCELAMENTO` | — |
| "Projeto" da planilha | **não é do Mega**: é o código da especificação técnica do cliente (parâmetro `especificacao_codigo`); os campos `PROJ_*` do Mega estão vazios | — |

### Chaves do vínculo pedido ↔ nota (`VEN_ITEMPEDI_VEN_ITEMNOT`)

- Lado do pedido: `PE_ORG_TAB_IN_CODIGO, PE_ORG_PAD_IN_CODIGO, PE_ORG_IN_CODIGO, PE_ORG_TAU_ST_CODIGO, PE_SER_ST_CODIGO,
  PE_PED_IN_CODIGO, PE_ITP_IN_SEQUENCIA` (item do pedido em `VEN_ITEMPEDIDOVENDA`).
- Lado da nota: `NF_ORG_TAB_IN_CODIGO, NF_ORG_PAD_IN_CODIGO, NF_ORG_IN_CODIGO, NF_ORG_TAU_ST_CODIGO, NF_SEQ_TAB_IN_CODIGO,
  NF_SEQ_IN_CODIGO, NF_NOT_IN_CODIGO, NF_ITN_IN_SEQUENCIA` (item da nota em `VEN_ITEMNOTAFISCAL`, nota em `VEN_NOTAFISCAL`).
- Quantidade daquele item do pedido naquela nota: `IPN_RE_QUANTIDADE`.

## Busca das OPs: o que a comparação com a planilha mostrou (24/11/2026)

Consulta nova rodada na produção, só leitura, e aplicada num banco de teste carregado com a planilha de OPs do
sistema antigo (só contagens; nenhum dado real no repositório):

- A busca leu 171 OPs de chaveta da filial desde 2024; 104 das 106 OPs da planilha vieram (das 2 que faltaram, uma
  foi aberta antes de 2024 e a outra não existe no Mega). Item, descrição e classificação batem em 103 de 104.
- As 67 OPs que estão no Mega e não na planilha estão **encerradas** ou canceladas (histórico que a Qualidade não
  controlou): por isso só entra como OP nova a que não estiver encerrada nem cancelada.
- **Pedido de origem ≠ pedido do faturamento.** O pedido que o Mega liga à OP (`PRO_ORIGEM`) é aquele para o qual
  ela foi aberta. Em 4 de 13 OPs com os dois preenchidos, a planilha tem outro PIV, e a NF digitada estava em
  20 de 20 casos entre as notas do **PIV da planilha**. Preencher NF pelo pedido de origem gravaria nota errada em
  3 de 9 OPs. Por isso a busca nunca preenche PIV, NF, data nem quantidade faturada; ela guarda as notas do item
  no pedido como referência, buscando primeiro pelo PIV digitado. Com essa regra, as notas mostradas contêm a NF
  digitada em 19 de 19 OPs.
- 80 das 104 OPs não têm pedido nem cliente no Mega (sem `PRO_ORIGEM` e sem número em `ORD_ST_ALTERNATIVO`).
- O nome do cliente no Mega (`AGN_ST_FANTASIA`) é escrito diferente do usado na planilha: a busca reaproveita o
  nome que a Qualidade já usa para o mesmo cliente (é o que sai nos relatórios).
- O PO (vazio em toda a planilha) é preenchido em 19 OPs, sempre a partir do PIV digitado.
- Situação das notas ligadas: `NOT_CH_SITUACAO` L (129 vínculos) e N (23); nota cancelada é descartada por
  `NOT_DT_CANCELAMENTO`.

## Matéria-prima (entrada das peças fundidas)

Uso: botão "Buscar no Mega" da tela Matéria-prima (`GET /api/materia-prima/entradas-mega`, `mega.consulta_entradas`),
lido na hora, sem cópia local. Conferido na produção em 24/11/2026: 22 itens de 14 notas nos últimos 12 meses.

Mapeado em 24/11/2026 com as tabelas já liberadas, comparando com os registros de matéria-prima do sistema antigo
(amostra pequena: 4 registros de 2 notas; só contagens):

| Dado da tela Matéria-prima | Mega | Validação |
|---|---|---|
| NF de entrada | `EST_RECEBIMENTO.RCB_ST_NOTA` (filial `FIL_IN_CODIGO = 3`) | 2/2 notas. O número **repete entre fornecedores**: a busca tem de usar a nota inteira (chave com o fornecedor), nunca só o número |
| Data de recebimento | `EST_RECEBIMENTO.RCB_DT_MOVIMENTO` (data de entrada) | 4/4 (a data de emissão `RCB_DT_DOCUMENTO` bateu só em 3/4) |
| Fornecedor | `GLO_AGENTES.AGN_ST_NOME` pelo `AGN_*` da nota | o sistema antigo usava um apelido que não existe no Mega: a razão social é outra |
| Peça e tipo PIN/BOX/ARK | `EST_ITENSRECEB.PRO_IN_CODIGO` → `EST_PRODUTOS.PRO_ST_DESCRICAO` (descrição com "FUNDID" e PIN/BOX/ARK) | tipo igual ao "tipo destino" em 4/4 |
| Quantidade fundida | `EST_ITENSRECEB.RCI_RE_QUANTIDADE` | igual em 2/2 notas; quando a nota traz várias corridas, a soma das corridas dá a quantidade da nota |
| **Corrida** | **não existe no Mega** (ver abaixo): continua sendo digitada a partir do certificado do fornecedor | 0/4 |

Entradas de peças fundidas na filial 3 desde 2025: 17 notas (27 itens), 2 fornecedores, 4 produtos, todas com
tipo de documento 7 e aplicação 4. Os produtos fundidos estão marcados para **controlar lotes**
(`EST_PRODUTOS.PRO_BO_CONTROLALOTES = 'S'` em 10 de 11 cadastros e em 27/27 entradas), então procuramos a corrida
nas tabelas de lote (liberadas só para isso e depois revogadas):

- `EST_LOTESMOVIMENTO` (`MVL_ST_LOTEFORNE`, ligada à entrada por `EST_MOVIMENTO`: `MVT_IN_LANCAM`, tipo de movimento 1,
  `MVT_ST_NUMDOC` = NF): as 27 entradas têm lote, 1 por item, com a quantidade do item; mas o "lote do fornecedor"
  é o **número da NF** em 24 de 27 (5 dígitos, nunca o formato da corrida), e `MVL_ST_REFERENCIA` é "*" ou um código
  interno. Nenhuma das 4 corridas do sistema antigo aparece.
- `EST_LOTERECEBXML` (lotes do XML da NF-e, ligado por `RCB_ST_CHAVEACESSO`): nenhum lote nessas notas.
- `EST_LOTESINSPECAODET` (inspeção de recebimento): tabela vazia; a inspeção do Mega não é usada.

Conclusão: o Mega dá NF, data, fornecedor, peça/tipo e quantidade de cada entrada de peças fundidas; a corrida só
existe no certificado. Ela viria sozinha se o recebimento lançasse a corrida como "lote do fornecedor" na entrada
(decisão de processo, fora do sistema); aí bastaria liberar de novo `EST_LOTESMOVIMENTO` e `EST_MOVIMENTO`.

## Permissões

Bloco C de `scripts/mega/01_criar_usuario_leitura.sql`. Durante o mapeamento o usuário tem `SELECT ANY TABLE`
(bloco B); depois que a sincronização estiver pronta, rodar o bloco D (revoga).
