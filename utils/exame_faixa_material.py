# -*- coding: utf-8 -*-
"""Material de estudo do programa de exame: o que cada item quer dizer.

O programa (`exame_faixa_dados`) diz *o que* se cobra — "Ukemi-waza: um tipo",
"Nage-waza: O-soto-gari". Ele não diz *quais* são os tipos nem o que cada
técnica é. Quem já treina sabe; quem está estudando em casa, não. Este módulo
é a camada de estudo que faltava: para cada item do programa, a tradução, a
família a que pertence e como se executa.

É só consulta, indexada pelo nome. Nada aqui entra no banco e nada aqui muda o
que a banca cobra: se um item do programa não tiver ficha, a tela mostra o
nome sozinho, exatamente como antes.

Fontes
  * Apostilas do Curso de Faixa Preta e Graus Superiores da FPJU, em
    /var/www/CFPGs — "Katame-Waza" (Prof. Márcio Andrade), de onde vêm os
    passos de execução das técnicas de solo, "Terminologia e Pronúncia"
    (Tadao Nagai, 9º Dan), de onde vêm as traduções, e "Nage-Waza"
    (Prof. Jonas Nascimento, 6º Dan).
  * Classificação por família e série do Go-kyo: lista oficial do Kodokan.

Os passos de execução são resumos das apostilas, não a transcrição delas —
a tela é um lembrete de estudo, e quem vai ao exame estuda pelo original.
"""

import unicodedata

# ------------------------------------------------------------------ famílias
# Rótulo curto de cada família, como aparece ao lado do nome da técnica.
FAMILIAS = {
    "te":       "Te-waza — projeção de braço",
    "koshi":    "Koshi-waza — projeção de quadril",
    "ashi":     "Ashi-waza — projeção de perna",
    "ma":       "Ma-sutemi-waza — sacrifício para trás",
    "yoko":     "Yoko-sutemi-waza — sacrifício de lado",
    "osaekomi": "Osaekomi-waza — imobilização",
    "shime":    "Shime-waza — estrangulamento",
    "kansetsu": "Kansetsu-waza — chave de articulação",
    "grupo":    "Grupo de técnicas",
}


# --------------------------------------------------------------------- ukemi
# As quatro quedas do judô. O programa cobra "um tipo", "dois tipos" e assim
# por diante até nomeá-las uma a uma na promoção para a amarela — é desta
# lista que o aluno escolhe.
UKEMI_NOTA = (
    "As quatro quedas têm três coisas em comum: o queixo preso ao peito para a "
    "cabeça nunca tocar o tatame, o braço batendo aberto para espalhar o "
    "impacto, e o corpo redondo, sem articulação travada."
)

UKEMI = [
    {
        "nome": "Ushiro-ukemi",
        "traducao": "queda para trás",
        "resumo": "A primeira queda que se aprende, e a base de todas as outras: "
                  "ensina a proteger a cabeça quando o corpo cai de costas.",
        "passos": [
            "Comece sentado, queixo colado no peito, olhando para o nó da própria faixa.",
            "Role as costas para trás, deixando a coluna tocar o tatame aos poucos, "
            "e não de uma vez.",
            "Bata os dois braços no tatame ao mesmo tempo, abertos a cerca de 45° do "
            "corpo, palmas para baixo.",
            "A cabeça não toca o tatame em momento nenhum — é o queixo no peito que "
            "garante isso.",
        ],
    },
    {
        "nome": "Yoko-ukemi",
        "traducao": "queda para o lado",
        "resumo": "A queda mais usada no treino, porque é nela que termina a maior "
                  "parte das projeções. Vale para os dois lados: migi (direita) e "
                  "hidari (esquerda).",
        "passos": [
            "Projete uma perna à frente e deixe o corpo descer pelo lado dela.",
            "O tatame é tocado em ordem: panturrilha, coxa, quadril e lateral das costas.",
            "Bata o braço do mesmo lado da queda, aberto a 45°, palma para baixo.",
            "O queixo fica preso ao peito e o outro braço à frente, protegendo o rosto.",
        ],
    },
    {
        "nome": "Mae-ukemi",
        "traducao": "queda para a frente",
        "resumo": "A queda de quem cai de cara para o tatame sem ter como rolar. "
                  "O corpo para no ar: só os antebraços e as pontas dos pés encostam.",
        "passos": [
            "De joelhos, no começo, e depois de pé, deixe o corpo cair à frente.",
            "Receba o tatame com os dois antebraços e as palmas, formando um triângulo "
            "à frente do rosto.",
            "Os cotovelos flexionam amortecendo — eles não batem travados.",
            "Vire a cabeça para o lado: o rosto, o peito e os joelhos não tocam o tatame.",
        ],
    },
    {
        "nome": "Zempo-kaiten-ukemi",
        "traducao": "rolamento amortecido para a frente",
        "resumo": "O rolamento. Também chamado de mae-mawari-ukemi. Transforma a "
                  "queda em giro, e por isso é a que permite levantar já de pé.",
        "passos": [
            "De pé, ponha à frente a mão e o pé do mesmo lado, com os dedos da mão "
            "apontando para dentro.",
            "O rolamento entra pelo braço estendido e sai na diagonal das costas, do "
            "ombro até o quadril do lado oposto.",
            "A cabeça fica virada para dentro e não toca o tatame.",
            "Termine batendo o braço livre, saindo em pé ou sentado, de frente para "
            "onde começou.",
        ],
    },
]


# ----------------------------------------------------------------- kumi-kata
# Kumi-kata é a pegada. O programa cobra "um tipo", "dois tipos", "três tipos":
# é desta lista que saem. As oito formas nomeadas são as da FPJU.
KUMI_KATA_NOTA = (
    "Antes das formas, os dois nomes que aparecem em toda aula: hikite é a mão "
    "que puxa, a que segura a manga; tsurite é a mão que suspende, a que segura "
    "a gola. Com a direita na gola é migi-gumi (pegada de direita); com a "
    "esquerda, hidari-gumi."
)

KUMI_KATA = [
    {
        "nome": "Kumi-kata fundamental",
        "traducao": "pegada de gola e manga",
        "resumo": "A pegada básica, de onde sai quase toda projeção do judô: uma mão "
                  "na gola (tsurite) e a outra na manga (hikite) do lado oposto.",
        "passos": [
            "A mão da gola pega na altura do peitoral, com o cotovelo baixo.",
            "A mão da manga pega por fora, na altura do cotovelo do oponente.",
            "Os braços ficam soltos: a pegada é firme nos dedos, não nos ombros.",
        ],
    },
    {"nome": "Mae-sode", "traducao": "manga, na ponta",
     "resumo": "Pegada na ponta da manga. Dá distância e serve para abrir espaço."},
    {"nome": "Naka-sode", "traducao": "manga, no meio",
     "resumo": "Pegada no meio da manga, na altura do antebraço. É a pegada de manga "
               "mais comum no hikite."},
    {"nome": "Oku-sode", "traducao": "manga, na parte alta",
     "resumo": "Pegada alta na manga, junto ao cotovelo ou acima dele. Controla o "
               "braço inteiro e prende o ombro do oponente."},
    {"nome": "Mae-eri", "traducao": "gola, na parte inferior",
     "resumo": "Pegada baixa na gola, na altura do peito. Pegada de ataque: aproxima "
               "e puxa para a frente."},
    {"nome": "Naka-eri", "traducao": "gola, no meio",
     "resumo": "Pegada no meio da gola, na altura da clavícula. É a do kumi-kata "
               "fundamental."},
    {"nome": "Uwa-eri", "traducao": "gola, na parte alta",
     "resumo": "Pegada alta na gola, junto ao pescoço. Levanta a postura do oponente "
               "e prepara as técnicas de quadril."},
    {"nome": "Ushiro-eri", "traducao": "gola, por trás",
     "resumo": "Pegada na parte de trás da gola, na nuca. Puxa a cabeça para baixo e "
               "quebra a postura."},
    {"nome": "Ushiro-obi", "traducao": "faixa, nas costas",
     "resumo": "Pegada na faixa, por trás do corpo. É a pegada do tsuri-goshi e das "
               "técnicas que levantam o oponente."},
]


# ------------------------------------------------------------------ técnicas
# Nome -> ficha. `serie` é a série do Go-kyo quando a técnica está nela; as
# demais trazem o grupo do Kodokan a que pertencem (shinmeisho, habukareta) ou
# dizem que são variação de uma técnica oficial.
#
# A chave é o nome como ele aparece no programa. A busca é por `ficha()`, que
# ignora hífen, acento e caixa — então uma academia que escreva "Osoto-gari"
# ou "O soto gari" continua achando a ficha.
TECNICAS = {
    # ------------------------------------------------------------ te-waza
    "Seoi-nage": {
        "traducao": "arremesso carregando nas costas",
        "familia": "te", "serie": "1ª série do Go-kyo",
        "resumo": "Tori gira de costas, encaixa o oponente sobre os dois ombros usando "
                  "as costas como alavanca e o projeta à frente."},
    "Ippon-seoi-nage": {
        "traducao": "arremesso sobre o ombro com um braço",
        "familia": "te", "serie": "Shinmeisho-no-waza",
        "resumo": "O seoi-nage feito com um braço só: tori passa o próprio braço por "
                  "dentro da axila do oponente e carrega o braço dele no ombro."},
    "Tai-otoshi": {
        "traducao": "queda brusca do corpo",
        "familia": "te", "serie": "2ª série do Go-kyo",
        "resumo": "Tori gira, estende a perna à frente do tornozelo do oponente e o "
                  "derruba pela ação das mãos — a perna é barreira, não varre."},
    "Kata-guruma": {
        "traducao": "giro pelos ombros",
        "familia": "te", "serie": "3ª série do Go-kyo",
        "resumo": "Tori abaixa o corpo, carrega o oponente atravessado sobre os ombros "
                  "e o faz girar para a frente."},
    "Uki-otoshi": {
        "traducao": "queda brusca flutuante",
        "familia": "te", "serie": "4ª série do Go-kyo",
        "resumo": "Só com as mãos: tori recua levando um joelho ao tatame e derruba o "
                  "oponente na diagonal da frente. É a primeira técnica do Nage-no-Kata."},
    "Sumi-otoshi": {
        "traducao": "queda brusca em ângulo",
        "familia": "te", "serie": "5ª série do Go-kyo",
        "resumo": "Também só de mãos, mas para o canto de trás: tori leva o oponente "
                  "para fora da base e o derruba sem encostar perna nenhuma."},
    "Sukui-nage": {
        "traducao": "arremesso em forma de colher",
        "familia": "te", "serie": "4ª série do Go-kyo",
        "resumo": "Tori passa os braços por baixo do quadril ou das pernas do oponente "
                  "e o levanta como quem recolhe com uma pá, girando-o para trás."},
    "Morote-gari": {
        "traducao": "ceifa com as duas mãos",
        "familia": "te", "serie": "Shinmeisho-no-waza",
        "resumo": "Tori abaixa, agarra as duas pernas do oponente ao mesmo tempo e "
                  "empurra o tronco dele para trás."},
    "Kuchiki-taoshi": {
        "traducao": "derrubar a árvore podre",
        "familia": "te", "serie": "Shinmeisho-no-waza",
        "resumo": "Tori agarra uma perna do oponente com a mão e puxa, enquanto empurra "
                  "o tronco no sentido contrário."},
    "Kibisu-gaeshi": {
        "traducao": "virada pelo calcanhar",
        "familia": "te", "serie": "Shinmeisho-no-waza",
        "resumo": "Tori pega o calcanhar do oponente e puxa para cima, empurrando o "
                  "peito dele para trás."},
    "Uchi-mata-sukashi": {
        "traducao": "desvio na defesa do uchi-mata",
        "familia": "te", "serie": "Shinmeisho-no-waza · contragolpe",
        "resumo": "Quando o oponente entra de uchi-mata, tori tira a perna atacada e "
                  "gira as mãos: o oponente cai no vazio, pelo próprio impulso."},
    "O-soto-sukashi": {
        "traducao": "desvio na defesa do o-soto-gari",
        "familia": "te", "serie": "Contragolpe",
        "resumo": "Mesma ideia do uchi-mata-sukashi: tori recolhe a perna que seria "
                  "ceifada e deixa o oponente cair no próprio movimento."},

    # ---------------------------------------------------------- koshi-waza
    "O-goshi": {
        "traducao": "grande golpe de quadril",
        "familia": "koshi", "serie": "1ª série do Go-kyo",
        "resumo": "Tori encaixa o quadril abaixo do quadril do oponente, envolve a "
                  "cintura dele e o projeta por cima, girando."},
    "Uki-goshi": {
        "traducao": "arremesso de quadril em rotação flutuante",
        "familia": "koshi", "serie": "1ª série do Go-kyo",
        "resumo": "O quadril entra de lado e não levanta o oponente: a projeção vem do "
                  "giro, não da elevação. Era a técnica preferida de Jigoro Kano."},
    "Koshi-guruma": {
        "traducao": "giro de quadril",
        "familia": "koshi", "serie": "2ª série do Go-kyo",
        "resumo": "Como o o-goshi, mas o braço de tori envolve o pescoço do oponente, "
                  "que roda sobre o quadril como sobre um eixo."},
    "Tsuri-komi-goshi": {
        "traducao": "arremesso de quadril em suspensão",
        "familia": "koshi", "serie": "2ª série do Go-kyo",
        "resumo": "Tori puxa a gola para cima, abaixa o próprio quadril por baixo do "
                  "oponente e o projeta à frente."},
    "Tsuri-goshi": {
        "traducao": "quadril com suspensão pela faixa",
        "familia": "koshi", "serie": "3ª série do Go-kyo",
        "resumo": "Tori segura a faixa do oponente — por cima ou por baixo do braço — e "
                  "o levanta sobre o quadril."},
    "Harai-goshi": {
        "traducao": "varrida de perna com apoio de quadril",
        "familia": "koshi", "serie": "2ª série do Go-kyo",
        "resumo": "Tori encaixa o quadril, desequilibra o oponente à frente e varre a "
                  "coxa e o lado do corpo dele com a perna estendida."},
    "Hane-goshi": {
        "traducao": "impulso do quadril",
        "familia": "koshi", "serie": "3ª série do Go-kyo",
        "resumo": "Com a perna semiflexionada, tori levanta o lado do corpo do oponente "
                  "num impulso de mola, e não com uma varrida."},
    "Ushiro-goshi": {
        "traducao": "arremesso do oponente de costas",
        "familia": "koshi", "serie": "5ª série do Go-kyo",
        "resumo": "Contragolpe de quadril: quando o oponente entra, tori o levanta pela "
                  "cintura e o derruba de costas no tatame."},
    "Utsuri-goshi": {
        "traducao": "arremesso com troca de quadril",
        "familia": "koshi", "serie": "4ª série do Go-kyo",
        "resumo": "Tori levanta o oponente que atacava e, com ele no ar, troca o quadril "
                  "de lado para projetá-lo no sentido contrário."},

    # ----------------------------------------------------------- ashi-waza
    "De-ashi-harai": {
        "traducao": "varrer o pé que avança",
        "familia": "ashi", "serie": "1ª série do Go-kyo",
        "resumo": "No instante em que o oponente desloca o pé, tori varre a planta dele "
                  "com a sola, no sentido do passo. É tempo, não força."},
    "Hiza-guruma": {
        "traducao": "rodada com apoio no joelho",
        "familia": "ashi", "serie": "1ª série do Go-kyo",
        "resumo": "Tori apoia a sola do pé no joelho do oponente e gira o corpo dele "
                  "sobre esse ponto fixo."},
    "Sasae-tsuri-komi-ashi": {
        "traducao": "bloqueio no pé com puxada",
        "familia": "ashi", "serie": "1ª série do Go-kyo",
        "resumo": "Tori bloqueia o tornozelo do oponente com a sola e o puxa para cima "
                  "e para a frente, fazendo-o girar por cima do bloqueio."},
    "O-soto-gari": {
        "traducao": "grande ceifada externa",
        "familia": "ashi", "serie": "1ª série do Go-kyo",
        "resumo": "Tori desequilibra o oponente para trás e ceifa por fora a perna de "
                  "apoio dele, com a parte de trás da própria coxa."},
    "O-uchi-gari": {
        "traducao": "grande ceifada interna",
        "familia": "ashi", "serie": "1ª série do Go-kyo",
        "resumo": "Tori ceifa por dentro a perna do oponente, no sentido de trás, "
                  "derrubando-o de costas."},
    "Ko-soto-gari": {
        "traducao": "pequena varrida externa",
        "familia": "ashi", "serie": "2ª série do Go-kyo",
        "resumo": "Tori varre por fora o calcanhar do oponente no sentido do passo dele, "
                  "derrubando-o para trás, na diagonal."},
    "Ko-uchi-gari": {
        "traducao": "pequena varredura interna",
        "familia": "ashi", "serie": "2ª série do Go-kyo",
        "resumo": "Tori varre por dentro o calcanhar do pé avançado do oponente, no "
                  "mesmo sentido em que ele estava indo."},
    "Uchi-mata": {
        "traducao": "arremesso com a perna entre as coxas",
        "familia": "ashi", "serie": "2ª série do Go-kyo",
        "resumo": "Tori gira e levanta por dentro a coxa do oponente com a parte de "
                  "trás da própria coxa."},
    "Ko-soto-gake": {
        "traducao": "pequena enganchada externa",
        "familia": "ashi", "serie": "3ª série do Go-kyo",
        "resumo": "Em vez de varrer, tori engancha o próprio pé por fora do calcanhar "
                  "do oponente e empurra o tronco dele para trás."},
    "Ko-uchi-gake": {
        "traducao": "pequena enganchada interna",
        "familia": "ashi", "serie": "Variação do ko-uchi-gari",
        "resumo": "Como o ko-uchi-gari, mas o pé engancha a perna por dentro em vez de "
                  "varrê-la — serve quando o oponente já apoiou o peso."},
    "Ashi-guruma": {
        "traducao": "rodada sobre a perna",
        "familia": "ashi", "serie": "3ª série do Go-kyo",
        "resumo": "Tori põe a perna estendida à frente das do oponente, na altura do "
                  "joelho, e o faz girar por cima dela como sobre um eixo."},
    "Harai-tsuri-komi-ashi": {
        "traducao": "varrida com levantamento de perna",
        "familia": "ashi", "serie": "3ª série do Go-kyo",
        "resumo": "Tori puxa o oponente para cima e para a frente e varre o pé avançado "
                  "no alto do movimento, quando ele está mais leve."},
    "O-guruma": {
        "traducao": "grande roda",
        "familia": "ashi", "serie": "4ª série do Go-kyo",
        "resumo": "A perna estendida de tori passa na altura do ventre do oponente, que "
                  "gira por cima dela. Diferente do harai-goshi, o quadril não encosta."},
    "O-soto-guruma": {
        "traducao": "grande giro externo",
        "familia": "ashi", "serie": "5ª série do Go-kyo",
        "resumo": "Como o o-soto-gari, mas a perna de tori ceifa as duas pernas do "
                  "oponente de uma vez."},
    "O-soto-otoshi": {
        "traducao": "grande queda brusca externa",
        "familia": "ashi", "serie": "Habukareta-waza",
        "resumo": "Tori planta a perna atrás da do oponente e o derruba para trás sem "
                  "ceifar — a perna é apoio, não varrida."},
    "Nidan-ko-soto-gari": {
        "traducao": "pequena varredura externa em dois tempos",
        "familia": "ashi", "serie": "Variação do ko-soto-gari",
        "resumo": "Tori salta duas vezes no mesmo sentido e varre o calcanhar do "
                  "oponente na segunda batida, quando ele já está em desequilíbrio."},
    "Hane-goshi-gaeshi": {
        "traducao": "contragolpe do hane-goshi",
        "familia": "ashi", "serie": "Shinmeisho-no-waza · contragolpe",
        "resumo": "Quando o oponente entra de hane-goshi, tori bloqueia a perna de "
                  "impulso dele e devolve a projeção no sentido do giro."},
    "Harai-goshi-gaeshi": {
        "traducao": "contragolpe do harai-goshi",
        "familia": "ashi", "serie": "Shinmeisho-no-waza · contragolpe",
        "resumo": "Tori segura a perna que varre e derruba o oponente para o mesmo lado "
                  "em que ele estava girando."},

    # -------------------------------------------------------- sutemi-waza
    "Tomoe-nage": {
        "traducao": "arremesso circular",
        "familia": "ma", "serie": "3ª série do Go-kyo",
        "resumo": "Tori senta sob o oponente, apoia o pé no ventre dele e o lança por "
                  "cima da própria cabeça."},
    "Sumi-gaeshi": {
        "traducao": "arremesso encaixado em ângulo para trás",
        "familia": "ma", "serie": "4ª série do Go-kyo",
        "resumo": "Tori senta, apoia o pé na parte interna da coxa do oponente e o "
                  "lança na diagonal por cima da própria cabeça."},
    "Ura-nage": {
        "traducao": "arremesso invertido para trás",
        "familia": "ma", "serie": "5ª série do Go-kyo",
        "resumo": "Tori envolve o oponente pela cintura e se joga para trás, lançando-o "
                  "por cima do próprio ombro."},
    "Tawara-gaeshi": {
        "traducao": "arremesso do saco de arroz",
        "familia": "ma", "serie": "Habukareta-waza",
        "resumo": "Quando o oponente se abaixa para atacar, tori o abraça pelo tronco e "
                  "o joga por cima da cabeça, como quem vira um fardo."},
    "Yoko-otoshi": {
        "traducao": "queda brusca lateral",
        "familia": "yoko", "serie": "3ª série do Go-kyo",
        "resumo": "Tori se joga de lado estendendo a perna junto ao pé do oponente, que "
                  "cai para o lado."},
    "Tani-otoshi": {
        "traducao": "queda no vale",
        "familia": "yoko", "serie": "4ª série do Go-kyo",
        "resumo": "Tori se joga de lado e estende a perna por trás das duas pernas do "
                  "oponente, derrubando-o para trás."},
    "Hane-makikomi": {
        "traducao": "projeção com enrolamento e elevação do quadril",
        "familia": "yoko", "serie": "4ª série do Go-kyo",
        "resumo": "É o hane-goshi em que tori enrola o braço do oponente e cai junto, "
                  "de lado, por cima dele."},
    "Soto-makikomi": {
        "traducao": "projeção de enrolamento externo",
        "familia": "yoko", "serie": "4ª série do Go-kyo",
        "resumo": "Tori enrola o braço do oponente por fora, gira e se joga de lado, "
                  "levando-o junto."},
    "Harai-makikomi": {
        "traducao": "enrolamento com varrida de quadril",
        "familia": "yoko", "serie": "Shinmeisho-no-waza",
        "resumo": "O harai-goshi terminado em enrolamento: tori prende o braço do "
                  "oponente e cai junto com ele."},
    "Uchi-makikomi": {
        "traducao": "projeção de enrolamento interior",
        "familia": "yoko", "serie": "Habukareta-waza",
        "resumo": "Tori entra por dentro, enrola o braço do oponente e se joga de lado."},
    "Uki-waza": {
        "traducao": "arremesso flutuante",
        "familia": "yoko", "serie": "5ª série do Go-kyo",
        "resumo": "Tori se joga de lado estendendo a perna à frente do pé do oponente, "
                  "que cai no próprio avanço."},
    "Yoko-wakare": {
        "traducao": "separação lateral",
        "familia": "yoko", "serie": "5ª série do Go-kyo",
        "resumo": "Tori se joga à frente dos pés do oponente, deslizando de lado e "
                  "puxando-o por cima de si."},
    "Yoko-guruma": {
        "traducao": "roda lateral",
        "familia": "yoko", "serie": "5ª série do Go-kyo",
        "resumo": "Quando o oponente se abaixa, tori passa por baixo, joga-se de lado e "
                  "o faz girar por cima. É o contragolpe clássico do ura-nage defendido."},
    "Yoko-gake": {
        "traducao": "enganchada lateral",
        "familia": "yoko", "serie": "5ª série do Go-kyo",
        "resumo": "Tori engancha o pé do oponente por fora e se joga de lado no mesmo "
                  "tempo, levando-o junto."},

    # --------------------------------------------------------------- grupo
    "Katame-waza": {
        "traducao": "técnicas de controle no solo",
        "familia": "grupo", "serie": "Grupo do Kodokan",
        "resumo": "Não é uma técnica e sim o grupo inteiro do solo — imobilização "
                  "(osaekomi), estrangulamento (shime) e chave (kansetsu). No programa "
                  "aparece como 'siga para o solo', ou seja, a sequência termina em "
                  "qualquer técnica de controle."},
}


# As técnicas de solo trazem também os passos de execução, resumidos da
# apostila de Katame-Waza da FPJU (Prof. Márcio Andrade), que é o material
# que a banca usa como referência.
TECNICAS.update({
    # ------------------------------------------------------- osaekomi-waza
    "Hon-kesa-gatame": {
        "traducao": "imobilização em echarpe, forma básica",
        "familia": "osaekomi", "serie": "Forma oficial do Kodokan",
        "resumo": "A imobilização lateral clássica: tori controla o oponente de lado, "
                  "usando o peso do próprio corpo sobre o peito dele.",
        "passos": [
            "Tori fica de lado ao oponente, em taka-kyoshi, bem próximo.",
            "Um braço segura o braço do oponente junto ao corpo, prendendo o pulso dele "
            "sob a própria axila.",
            "O outro braço envolve o pescoço por baixo da cabeça e segura a lapela.",
            "A perna do lado da cabeça fica estendida e a outra dobrada, com o pé firme "
            "no solo.",
            "O peso do corpo fica distribuído sobre o peito do oponente.",
        ]},
    "Kuzure-kesa-gatame": {
        "traducao": "variação do kesa-gatame",
        "familia": "osaekomi", "serie": "Forma oficial do Kodokan",
        "resumo": "Em vez de envolver a cabeça, tori passa o braço por baixo da axila do "
                  "oponente — dá mais estabilidade e menos risco de ser girado.",
        "passos": [
            "Tori fica de lado, em taka-kyoshi, com o tronco voltado para o tórax do "
            "oponente.",
            "Um braço envolve e prende o braço do oponente contra o próprio corpo.",
            "O outro braço passa por baixo da axila dele, com o antebraço e a mão "
            "espalmados no tatame.",
            "A perna do lado da cabeça estendida, a outra dobrada com o pé no solo.",
            "O tronco fica ereto e o peso projetado sobre o tórax e o abdômen.",
        ]},
    "Kata-gatame": {
        "traducao": "imobilização pelo ombro",
        "familia": "osaekomi", "serie": "Forma oficial do Kodokan",
        "resumo": "Tori prende o próprio braço do oponente contra o rosto dele e fecha "
                  "as mãos do outro lado da cabeça.",
        "passos": [
            "Tori fica de lado ao oponente, em taka-kyoshi.",
            "Com as duas mãos, posiciona o braço do oponente à frente do rosto dele.",
            "A cabeça de tori desce para perto do tatame, com o ombro pressionando o "
            "lado do rosto do oponente.",
            "Os braços abraçam o pescoço até as mãos se encontrarem, formando um cadeado.",
            "Um joelho fica na altura da faixa do oponente e a outra perna estendida.",
        ]},
    "Makura-kesa-gatame": {
        "traducao": "imobilização em echarpe com travesseiro",
        "familia": "osaekomi", "serie": "Variação do kesa-gatame",
        "resumo": "Makura é travesseiro: o braço do oponente — ou a coxa de tori — vira "
                  "apoio da cabeça dele, o que trava o pescoço e impede o giro.",
        "passos": [
            "Tori fica de lado, com o peito voltado para o tronco do oponente.",
            "Segura o interior da manga dele, prendendo o cotovelo sob o próprio braço e "
            "o pulso na axila.",
            "Abraça a cabeça do oponente e segura a parte interna da própria perna — é "
            "isso que dá o efeito makura.",
            "As pernas seguem a base do kesa: uma estendida, a outra dobrada com o pé "
            "firme no solo.",
        ]},
    "Ushiro-kesa-gatame": {
        "traducao": "imobilização em diagonal de costas",
        "familia": "osaekomi", "serie": "Forma oficial do Kodokan",
        "resumo": "O kesa-gatame invertido: tori imobiliza de costas para a cabeça do "
                  "oponente, o que muda a direção inteira do controle.",
        "passos": [
            "Tori fica ao lado e um pouco atrás, de costas para a cabeça do oponente.",
            "Um braço envolve o braço dele, prendendo-o contra o próprio corpo.",
            "O outro passa por baixo do tronco, segurando o judogui ou a faixa.",
            "Uma perna estendida e a outra dobrada, com o pé firme, na base do kesa.",
            "A cabeça de tori fica baixa, perto do solo, para não ser contra-atacado.",
        ]},
    "Kami-shiho-gatame": {
        "traducao": "imobilização pelos quatro apoios, pela cabeça",
        "familia": "osaekomi", "serie": "Forma oficial do Kodokan",
        "resumo": "Tori controla por cima da cabeça, segurando a faixa dos dois lados, "
                  "com o peito sobre o tórax do oponente.",
        "passos": [
            "Tori se posiciona à frente da cabeça do oponente, ajoelhado e centralizado "
            "sobre o tórax dele.",
            "Os dois braços passam por baixo dos braços do oponente e seguram a faixa.",
            "O peito fica colado ao abdômen ou ao peito dele, com o centro de gravidade "
            "baixo.",
            "Os cotovelos tocam o solo e as pernas abrem para a lateral, joelhos "
            "apoiados.",
            "O peso é projetado para a frente e para baixo, de forma contínua.",
        ]},
    "Kuzure-kami-shiho-gatame": {
        "traducao": "variação do kami-shiho-gatame",
        "familia": "osaekomi", "serie": "Forma oficial do Kodokan",
        "resumo": "Quando a pegada por baixo dos dois ombros não dá, um braço passa por "
                  "cima ou ao redor do ombro e o outro segura a gola de lado.",
        "passos": [
            "Tori à frente da cabeça do oponente, ajoelhado e centralizado sobre o tórax.",
            "Um braço passa por cima ou ao redor do ombro; o outro segura a gola "
            "lateralmente.",
            "O peito permanece apoiado sobre o tórax ou abdômen, centro de gravidade "
            "baixo.",
            "As pernas abertas e bem apoiadas, joelhos afastados e pés firmes.",
        ]},
    "Yoko-shiho-gatame": {
        "traducao": "imobilização pelos quatro apoios, de lado",
        "familia": "osaekomi", "serie": "Forma oficial do Kodokan",
        "resumo": "Uma das imobilizações mais seguras do judô: tori atravessa o corpo do "
                  "oponente, dominando tronco e quadril ao mesmo tempo.",
        "passos": [
            "Tori fica ao lado, deitado transversalmente em relação ao corpo do oponente.",
            "Um braço passa por baixo do pescoço e alcança o lado oposto do tronco, a "
            "faixa ou o judogui.",
            "O outro braço passa por baixo das pernas dele, buscando pegada firme.",
            "O peito e o abdômen de tori pressionam a lateral do tronco, corpo baixo.",
            "Os cotovelos apoiados no tatame e as pernas afastadas, formando base sólida.",
        ]},
    "Kuzure-yoko-shiho-gatame": {
        "traducao": "variação do yoko-shiho-gatame",
        "familia": "osaekomi", "serie": "Forma oficial do Kodokan",
        "resumo": "Em vez de passar o braço sob as pernas, tori passa por cima do braço "
                  "ou do tronco do oponente — útil quando ele tenta escapar.",
        "passos": [
            "Tori lateral ao oponente, deitado transversalmente, como no yoko-shiho.",
            "Um braço passa por cima do braço ou do tronco; o outro controla a parte "
            "superior pela faixa, pela gola ou apoiado no ombro.",
            "Peito e abdômen pressionando a lateral do tórax, centro de gravidade baixo.",
            "Cotovelos apoiados no solo e pernas abertas com os joelhos dobrados.",
        ]},
    "Tate-shiho-gatame": {
        "traducao": "imobilização pelos quatro apoios, montado",
        "familia": "osaekomi", "serie": "Forma oficial do Kodokan",
        "resumo": "Tori monta sobre o tronco do oponente de frente, o que dá o controle "
                  "mais amplo de todas as imobilizações.",
        "passos": [
            "Tori se aproxima de frente, em taka-kyoshi.",
            "Segura o interior de uma das mangas, prendendo o cotovelo do lado contrário "
            "sob o próprio braço.",
            "Desliza o outro braço do oponente até a altura do ombro dele e, ao mesmo "
            "tempo, passa a perna por cima, montando.",
            "Abraça o pescoço segurando fundo a parte de trás da lapela, baixando o "
            "tronco ao mesmo tempo.",
            "Os joelhos ficam bem abertos e firmes no chão, impedindo o giro.",
        ]},
    "Kuzure-tate-shiho-gatame": {
        "traducao": "variação do tate-shiho-gatame",
        "familia": "osaekomi", "serie": "Forma oficial do Kodokan",
        "resumo": "A montada com pegada adaptada: tori eleva os dois braços do oponente "
                  "acima da cabeça dele e os prende por baixo, nas próprias mangas.",
        "passos": [
            "Tori se aproxima de frente, em taka-kyoshi.",
            "Com as duas mãos, eleva um braço do oponente acima da cabeça dele e em "
            "seguida o outro.",
            "Passa a perna por cima, montando, mantendo o joelho ainda elevado.",
            "Abaixa o tórax e o joelho ao mesmo tempo, passando os dois braços por baixo "
            "dos braços dele, na altura do cotovelo.",
            "As mãos seguram as mangas do próprio wagui; a pressão vai para baixo e um "
            "pouco à frente.",
        ]},

    # ---------------------------------------------------------- shime-waza
    "Nami-juji-jime": {
        "traducao": "estrangulamento em cruz, forma normal",
        "familia": "shime", "serie": "Forma oficial do Kodokan",
        "resumo": "As duas mãos entram na gola com as palmas voltadas para baixo e os "
                  "punhos se cruzam num X à frente da garganta.",
        "passos": [
            "Tori fica de frente para o oponente, em geral com ele de costas no tatame.",
            "Uma das mãos entra na gola com a palma para baixo, deslizando até a nuca.",
            "A outra entra cruzada, também com a palma para baixo, do lado oposto, "
            "formando um X com os punhos.",
            "Tori aproxima o tronco, mantém os cotovelos junto ao corpo e puxa as golas "
            "para dentro.",
            "A pressão vai para as artérias carótidas, nunca para a traqueia.",
        ]},
    "Gyaku-juji-jime": {
        "traducao": "estrangulamento em cruz invertida",
        "familia": "shime", "serie": "Forma oficial do Kodokan",
        "resumo": "A mesma cruz, mas com as palmas voltadas para cima: a alavanca muda e "
                  "o estrangulamento fica mais profundo.",
        "passos": [
            "Tori de frente, com o oponente de costas no tatame.",
            "A primeira mão entra na gola oposta com a palma para cima; a segunda faz o "
            "mesmo do outro lado, cruzando.",
            "Os polegares ficam por fora da gola e os quatro dedos por dentro.",
            "Tori puxa as mãos na direção do próprio corpo, fechando os cotovelos.",
        ]},
    "Kata-juji-jime": {
        "traducao": "estrangulamento em meia cruz",
        "familia": "shime", "serie": "Forma oficial do Kodokan",
        "resumo": "O meio-termo entre os dois anteriores: uma mão com a palma para cima "
                  "e a outra com a palma para baixo.",
        "passos": [
            "Tori de frente para o oponente, de costas no tatame ou na guarda.",
            "A primeira mão entra na gola oposta com a palma para cima, quatro dedos por "
            "dentro e polegar por fora.",
            "A segunda entra na gola contrária com a palma para baixo.",
            "As mãos cruzadas formam o X à frente do pescoço; tori puxa as golas para "
            "dentro e para baixo.",
        ]},
    "Tsukkomi-jime": {
        "traducao": "estrangulamento de empurrar",
        "familia": "shime", "serie": "Forma oficial do Kodokan",
        "resumo": "Tori segura as duas lapelas e fecha a gola em volta do pescoço, como "
                  "uma guilhotina. É rápido, por isso exige controle.",
        "passos": [
            "Tori de frente, com o oponente sentado ou de costas no tatame.",
            "Segura as duas lapelas, uma com cada mão, polegares por dentro e dedos por "
            "fora.",
            "As mãos deslizam fundo, até a base do pescoço, criando a alavanca.",
            "Tori puxa as duas lapelas para fora e para baixo ao mesmo tempo, com os "
            "antebraços pressionando os lados do pescoço.",
        ]},
    "Ryo-te-jime": {
        "traducao": "estrangulamento com as duas mãos",
        "familia": "shime", "serie": "Forma oficial do Kodokan",
        "resumo": "Sem cruzar os braços: as duas mãos trabalham lado a lado e abrem a "
                  "gola, que pressiona os lados do pescoço.",
        "passos": [
            "Tori de frente, com o oponente sentado ou de costas.",
            "As duas mãos entram ao mesmo tempo nas golas, polegares por fora e dedos "
            "por dentro, paralelas e na mesma altura.",
            "As mãos deslizam fundo até os antebraços quase tocarem o pescoço.",
            "Tori puxa as duas lapelas para fora e para trás, como quem abre a gola.",
        ]},
    "Hadaka-jime": {
        "traducao": "estrangulamento sem auxílio da vestimenta",
        "familia": "shime", "serie": "Forma oficial do Kodokan",
        "resumo": "O estrangulamento 'nu': não usa o judogui, só os braços. É o de "
                  "quando não há gola à mão.",
        "passos": [
            "Tori fica atrás, com o joelho na linha da coluna do oponente para "
            "estabilizar.",
            "Encosta o dorso de uma das mãos no ombro dele.",
            "Com a outra mão, desliza pela frente do pescoço, palma para baixo, e segura "
            "a própria mão.",
            "Fecha os braços e puxa para trás, abaixando a cabeça sobre as mãos.",
        ]},
    "Kata-ha-jime": {
        "traducao": "estrangulamento de uma asa",
        "familia": "shime", "serie": "Forma oficial do Kodokan",
        "resumo": "Uma mão na gola e a outra travando o braço do oponente como uma asa: "
                  "ele perde o lado que usaria para se defender.",
        "passos": [
            "Tori por trás, com o oponente sentado.",
            "Uma das mãos passa por trás da cabeça e pega a gola oposta com firmeza, "
            "quatro dedos por fora e polegar por dentro.",
            "A outra passa por baixo do braço do mesmo lado da gola segurada e o "
            "empurra para cima.",
            "Tori puxa a gola enquanto trava o braço, girando levemente o corpo.",
        ]},
    "Okuri-eri-jime": {
        "traducao": "estrangulamento deslizando a gola",
        "familia": "shime", "serie": "Forma oficial do Kodokan",
        "resumo": "Clássico das transições pelas costas: uma mão entra fundo na gola e a "
                  "outra puxa do lado oposto, em sentidos contrários.",
        "passos": [
            "Tori se posiciona atrás do oponente.",
            "A mão dominante entra fundo na gola oposta, quatro dedos por fora e polegar "
            "por dentro, bem perto da nuca.",
            "A outra mão passa por trás e por baixo do braço dele, ajudando a puxar a "
            "gola para baixo.",
            "Tori puxa a lapela para baixo e a gola para a lateral, girando um pouco o "
            "tronco.",
        ]},
    "Sode-guruma-jime": {
        "traducao": "estrangulamento roda de manga",
        "familia": "shime", "serie": "Forma oficial do Kodokan",
        "resumo": "Tori envolve o pescoço com os dois braços e segura as próprias "
                  "mangas: a pressão vem de um movimento de roda.",
        "passos": [
            "Tori se aproxima pelas costas, podendo estar sentado.",
            "Um braço passa por cima do ombro do oponente e o outro por baixo do queixo, "
            "cruzados, envolvendo o pescoço.",
            "Cada mão segura a própria manga, com os punhos cruzados à frente do pescoço.",
            "Tori fecha os cotovelos num giro interno dos braços, trazendo os antebraços "
            "para dentro.",
        ]},
    "Sankaku-jime": {
        "traducao": "estrangulamento triangular",
        "familia": "shime", "serie": "Forma oficial do Kodokan",
        "resumo": "As pernas formam um triângulo em volta do pescoço e de um braço: um "
                  "lado do pescoço é comprimido pela perna, o outro pelo próprio braço.",
        "passos": [
            "Com o oponente em três apoios, tori se aproxima pela frente e faz a "
            "kumi-kata, segurando a gola com quatro dedos por dentro.",
            "Desequilibra-o para a frente passando a perna por cima da nuca dele e "
            "lateralizando o quadril.",
            "Cruza a outra perna, prendendo o pé na articulação do joelho — o braço do "
            "oponente fica preso entre as pernas.",
            "Empurra a manga dele na diagonal e eleva o quadril, apertando as pernas.",
        ]},
    "Koshi-jime": {
        "traducao": "estrangulamento com o quadril",
        "familia": "shime", "serie": "Variação clássica",
        "resumo": "O que diferencia este dos outros é o quadril: é o movimento dele, e "
                  "não o dos braços, que traciona a gola.",
        "passos": [
            "Tori passa um braço ao redor do pescoço, por cima do ombro, com a mão fundo "
            "na gola oposta.",
            "Com a outra mão, faz um giro interno e segura a manga pela parte interna do "
            "antebraço.",
            "Puxa o oponente para trás e em seguida o desliza para a frente.",
            "Senta na altura da omoplata dele, em postura de kesa, e gira levemente o "
            "tronco para efetuar o estrangulamento.",
        ]},
    "Jigoku-jime": {
        "traducao": "estrangulamento do inferno",
        "familia": "shime", "serie": "Variação clássica",
        "resumo": "Combina o estrangulamento das mãos com o controle das pernas — as "
                  "pernas viram um laço que tira qualquer defesa.",
        "passos": [
            "Com o oponente em seis apoios, tori se aproxima pela esquerda e segura a "
            "gola direita dele com a mão esquerda.",
            "Usa a perna esquerda para travar o braço esquerdo do oponente.",
            "Com a mão direita, giro interno para segurar a manga pela parte interna do "
            "antebraço.",
            "Rola por cima das costas dele, terminando de costas no tatame com o "
            "oponente por cima.",
            "Prende a perna e o braço dele, passa a mão direita por trás da nuca e eleva "
            "o quadril para aplicar a pressão.",
        ]},

    # ------------------------------------------------------- kansetsu-waza
    "Ude-garami": {
        "traducao": "chave de braço enrolado",
        "familia": "kansetsu", "serie": "Forma oficial do Kodokan",
        "resumo": "O braço do oponente fica dobrado em 90° e tori o torce enrolando os "
                  "próprios braços nele, pressionando cotovelo e ombro.",
        "passos": [
            "Tori está ao lado do oponente, em posição de domínio, como no "
            "yoko-shiho-gatame.",
            "Segura o punho dele com uma das mãos e passa o outro braço por baixo do "
            "braço dele, mantendo-o dobrado a 90°.",
            "Passa o próprio braço por sobre o antebraço do oponente e segura o próprio "
            "punho.",
            "Mantém o cotovelo dele fixo e eleva lentamente o punho, gerando a torção.",
        ]},
    "Ude-gatame": {
        "traducao": "chave de braço no cotovelo estendido",
        "familia": "kansetsu", "serie": "Forma oficial do Kodokan",
        "resumo": "Tori estende o braço do oponente e pressiona o cotovelo com as duas "
                  "mãos, usando o próprio tronco ou ombro como apoio.",
        "passos": [
            "Com a kumi-kata feita, tori prende com a cabeça a mão que o oponente tem na "
            "sua gola.",
            "Posiciona uma das mãos sobre a articulação do cotovelo dele.",
            "Coloca a outra mão sobre a primeira.",
            "Gira e pressiona a articulação do cotovelo, finalizando a chave.",
        ]},
    "Ude-hishigi-juji-gatame": {
        "traducao": "chave de braço em cruz",
        "familia": "kansetsu", "serie": "Forma oficial do Kodokan",
        "resumo": "A chave mais conhecida do judô: tori prende o braço entre as coxas e "
                  "usa o quadril para estender o cotovelo.",
        "passos": [
            "O gatilho é o oponente esticar o braço para empurrar tori.",
            "Tori segura o punho dele firme com as duas mãos, trazendo o braço para o "
            "centro do próprio peito.",
            "Lança uma perna por cima da cabeça do oponente, com a parte de trás da coxa "
            "sobre o rosto dele, e a outra sob o tronco; os joelhos ficam unidos.",
            "Deita-se de costas com o braço preso entre as coxas, o polegar do oponente "
            "virado para cima e o cotovelo dele no centro da linha do quadril.",
        ]},
    "Hiza-gatame": {
        "traducao": "chave com auxílio do joelho",
        "familia": "kansetsu", "serie": "Forma oficial do Kodokan",
        "resumo": "O joelho de tori é o ponto de apoio sobre o qual o cotovelo do "
                  "oponente é estendido.",
        "passos": [
            "Tori ajoelhado ou com um joelho no solo, em controle superior.",
            "Envolve o braço do oponente, encaixando a mão dele na própria axila.",
            "Apoia o pé no joelho dele e puxa para a frente; o outro pé vai sobre a "
            "faixa, de modo que o joelho fique sobre o cotovelo dele.",
            "Pressiona o joelho para baixo enquanto puxa o punho, estendendo a "
            "articulação.",
        ]},
    "Waki-gatame": {
        "traducao": "chave de braço pela axila",
        "familia": "kansetsu", "serie": "Forma oficial do Kodokan",
        "resumo": "A axila de tori é o apoio. Funciona em pé e no solo, e é das mais "
                  "perigosas: só se aplica com controle total.",
        "passos": [
            "Com o braço do oponente estendido, tori segura firme o punho dele, polegar "
            "voltado para baixo.",
            "Encaixa o cotovelo dele na própria axila e fecha o braço sobre a "
            "articulação.",
            "Empurra o punho para baixo e para trás, pressionando com o tronco à frente "
            "ou girando o corpo.",
            "Mantém pés ou joelhos firmes no solo para o oponente não girar.",
        ]},
    "Hara-gatame": {
        "traducao": "chave de braço com o abdômen",
        "familia": "kansetsu", "serie": "Forma oficial do Kodokan",
        "resumo": "O abdômen de tori é a base fixa sobre a qual o cotovelo do oponente "
                  "é hiperestendido.",
        "passos": [
            "Tori em posição superior, os dois em pé.",
            "Segura o braço do oponente estendido, com o cotovelo centralizado em "
            "relação ao próprio abdômen e o polegar dele para cima.",
            "Posiciona o abdômen logo abaixo da articulação do cotovelo, sem folga.",
            "Puxa o punho para trás e projeta o tronco à frente.",
        ]},
})


# ---------------------------------------------------------------- consulta
def _norm(txt):
    """Mesma normalização do exame_faixa: sem acento, sem hífen, sem caixa."""
    s = unicodedata.normalize("NFD", str(txt or "")).encode("ascii", "ignore").decode()
    return "".join(ch for ch in s.lower() if ch.isalnum())


_INDICE = {_norm(k): dict(v, nome=k) for k, v in TECNICAS.items()}
_INDICE_UKEMI = {_norm(u["nome"]): u for u in UKEMI}


def ficha(nome):
    """Ficha de estudo de uma técnica, ou None se o programa trouxer um nome
    que ainda não tem material. A tela trata None mostrando só o nome."""
    return _INDICE.get(_norm(nome))


def ficha_ukemi(nome):
    return _INDICE_UKEMI.get(_norm(nome))


def familia(chave):
    return FAMILIAS.get(chave or "")
