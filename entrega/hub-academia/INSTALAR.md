# Hub de Gerenciamento da Academia — instalação

Pacote da **única** página redesenhada: o hub `Gerenciamento — <Academia>`.

## Arquivos

| Arquivo do pacote | Onde vai | Ação |
|---|---|---|
| `templates/painel/painel_academia.html` | `templates/painel/painel_academia.html` | **substituir** |
| `templates/base_um.html` | `templates/base_um.html` | conferir se já existe (é o que você já tem — vai igual, só de referência) |
| `templates/components/_shell.html` | `templates/components/_shell.html` | idem |
| `routes_snippet.py` | — | opcional, ver abaixo |

Ou seja: na prática **só 1 arquivo muda**. Os outros dois vão no pacote porque a
página herda deles (`{% extends 'base_um.html' %}`); se já estiverem no
servidor, não precisa copiar.

## Python

Nada obrigatório. A rota `academia.painel_academia` já entrega tudo que a
página precisa (`academia`, `academias`, `academia_id`, `aniversariantes`,
`aniversariantes_hoje`, `zempo_prontos`).

O `routes_snippet.py` é opcional: acrescenta os contadores de solicitações
pendentes, mensalidades em atraso, pré-cadastros a converter e os totais de
alunos/turmas do subtítulo. Cada bloco da página só aparece se a variável
existir, então dá para instalar hoje e adicionar os contadores depois.

## Endpoints usados (todos já existentes)

`alunos.lista_alunos`, `alunos.cadastrar_aluno`, `turmas.lista_turmas`,
`presencas.painel_presenca`, `presencas.ata_presenca`,
`presencas.ranking_frequencia_pagina`, `precadastro.lista`,
`academia.lista_visitantes`, `professores.lista`, `academia.dash`,
`financeiro.dashboard`, `financeiro.mensalidades_alunos`,
`academia.locais_treino`, `configuracoes.modalidades_lista`,
`academia.lista_usuarios`, `academia.whatsapp_config`,
`academia.configuracoes_academia`, `eventos_competicoes.lista_eventos`,
`calendario.index`, `solicitacoes.lista`.

Se algum nome divergir no seu projeto (ex.: `eventos_competicoes.lista` em vez
de `lista_eventos`), é só ajustar a linha correspondente — cada módulo é um
`<a>` só.

## O que muda visualmente

- Sidebar fixa + topbar do shell novo, em vez do `container` com cards soltos.
- Os 12+ cards de borda colorida viram uma grade única, agrupada em
  **Alunos e turmas / Gestão da academia / Atividades e eventos**.
- O card "Aniversariantes" vira a faixa **Precisa da sua atenção**, junto com
  solicitações, inadimplência, pré-cadastros e Zempo — cada um com número e
  ação direta.
- Ações rápidas (Registrar presença, Novo aluno) no cabeçalho da página.
- Vermelho passa a significar urgência, não decoração.
