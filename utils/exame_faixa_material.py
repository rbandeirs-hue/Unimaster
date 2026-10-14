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

Os passos de execução das técnicas de solo são resumos da apostila de
Katame-Waza, não a transcrição dela. Os das projeções não vêm de apostila
nenhuma: a de Nage-Waza da FPJU é só imagem (um cartaz com as listas) e a de
Nage-no-Kata descreve a coreografia do kata, não a execução da técnica — então
seguem a execução padrão do Kodokan, na ordem kuzushi → tsukuri → kake.

De toda forma a tela é um lembrete de estudo: quem vai ao exame estuda pelo
material da federação e com o professor no tatame.
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
            "A mão da manga pega por fora, na altura do cotovelo do uke.",
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
               "braço inteiro e prende o ombro do uke."},
    {"nome": "Mae-eri", "traducao": "gola, na parte inferior",
     "resumo": "Pegada baixa na gola, na altura do peito. Pegada de ataque: aproxima "
               "e puxa para a frente."},
    {"nome": "Naka-eri", "traducao": "gola, no meio",
     "resumo": "Pegada no meio da gola, na altura da clavícula. É a do kumi-kata "
               "fundamental."},
    {"nome": "Uwa-eri", "traducao": "gola, na parte alta",
     "resumo": "Pegada alta na gola, junto ao pescoço. Levanta a postura do uke "
               "e prepara as técnicas de quadril."},
    {"nome": "Ushiro-eri", "traducao": "gola, por trás",
     "resumo": "Pegada na parte de trás da gola, na nuca. Puxa a cabeça para baixo e "
               "quebra a postura."},
    {"nome": "Ushiro-obi", "traducao": "faixa, nas costas",
     "resumo": "Pegada na faixa, por trás do corpo. É a pegada do tsuri-goshi e das "
               "técnicas que levantam o uke."},
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
        "resumo": "Tori gira de costas, encaixa o uke sobre os dois ombros usando "
                  "as costas como alavanca e o projeta à frente."},
    "Ippon-seoi-nage": {
        "traducao": "arremesso sobre o ombro com um braço",
        "familia": "te", "serie": "Shinmeisho-no-waza",
        "resumo": "O seoi-nage feito com um braço só: tori passa o próprio braço por "
                  "dentro da axila do uke e carrega o braço dele no ombro."},
    "Tai-otoshi": {
        "traducao": "queda brusca do corpo",
        "familia": "te", "serie": "2ª série do Go-kyo",
        "resumo": "Tori gira, estende a perna à frente do tornozelo do uke e o "
                  "derruba pela ação das mãos — a perna é barreira, não varre."},
    "Kata-guruma": {
        "traducao": "giro pelos ombros",
        "familia": "te", "serie": "3ª série do Go-kyo",
        "resumo": "Tori abaixa o corpo, carrega o uke atravessado sobre os ombros "
                  "e o faz girar para a frente."},
    "Uki-otoshi": {
        "traducao": "queda brusca flutuante",
        "familia": "te", "serie": "4ª série do Go-kyo",
        "resumo": "Só com as mãos: tori recua levando um joelho ao tatame e derruba o "
                  "uke na diagonal da frente. É a primeira técnica do Nage-no-Kata."},
    "Sumi-otoshi": {
        "traducao": "queda brusca em ângulo",
        "familia": "te", "serie": "5ª série do Go-kyo",
        "resumo": "Também só de mãos, mas para o canto de trás: tori leva o uke "
                  "para fora da base e o derruba sem encostar perna nenhuma."},
    "Sukui-nage": {
        "traducao": "arremesso em forma de colher",
        "familia": "te", "serie": "4ª série do Go-kyo",
        "resumo": "Tori passa os braços por baixo do quadril ou das pernas do uke "
                  "e o levanta como quem recolhe com uma pá, girando-o para trás."},
    "Morote-gari": {
        "traducao": "ceifa com as duas mãos",
        "familia": "te", "serie": "Shinmeisho-no-waza",
        "resumo": "Tori abaixa, agarra as duas pernas do uke ao mesmo tempo e "
                  "empurra o tronco dele para trás."},
    "Kuchiki-taoshi": {
        "traducao": "derrubar a árvore podre",
        "familia": "te", "serie": "Shinmeisho-no-waza",
        "resumo": "Tori agarra uma perna do uke com a mão e puxa, enquanto empurra "
                  "o tronco no sentido contrário."},
    "Kibisu-gaeshi": {
        "traducao": "virada pelo calcanhar",
        "familia": "te", "serie": "Shinmeisho-no-waza",
        "resumo": "Tori pega o calcanhar do uke e puxa para cima, empurrando o "
                  "peito dele para trás."},
    "Uchi-mata-sukashi": {
        "traducao": "desvio na defesa do uchi-mata",
        "familia": "te", "serie": "Shinmeisho-no-waza · contragolpe",
        "resumo": "Quando o uke entra de uchi-mata, tori tira a perna atacada e "
                  "gira as mãos: o uke cai no vazio, pelo próprio impulso."},
    "O-soto-sukashi": {
        "traducao": "desvio na defesa do o-soto-gari",
        "familia": "te", "serie": "Contragolpe",
        "resumo": "Mesma ideia do uchi-mata-sukashi: tori recolhe a perna que seria "
                  "ceifada e deixa o uke cair no próprio movimento."},

    # ---------------------------------------------------------- koshi-waza
    "O-goshi": {
        "traducao": "grande golpe de quadril",
        "familia": "koshi", "serie": "1ª série do Go-kyo",
        "resumo": "Tori encaixa o quadril abaixo do quadril do uke, envolve a "
                  "cintura dele e o projeta por cima, girando."},
    "Uki-goshi": {
        "traducao": "arremesso de quadril em rotação flutuante",
        "familia": "koshi", "serie": "1ª série do Go-kyo",
        "resumo": "O quadril entra de lado e não levanta o uke: a projeção vem do "
                  "giro, não da elevação. Era a técnica preferida de Jigoro Kano."},
    "Koshi-guruma": {
        "traducao": "giro de quadril",
        "familia": "koshi", "serie": "2ª série do Go-kyo",
        "resumo": "Como o o-goshi, mas o braço de tori envolve o pescoço do uke, "
                  "que roda sobre o quadril como sobre um eixo."},
    "Tsuri-komi-goshi": {
        "traducao": "arremesso de quadril em suspensão",
        "familia": "koshi", "serie": "2ª série do Go-kyo",
        "resumo": "Tori puxa a gola para cima, abaixa o próprio quadril por baixo do "
                  "uke e o projeta à frente."},
    "Tsuri-goshi": {
        "traducao": "quadril com suspensão pela faixa",
        "familia": "koshi", "serie": "3ª série do Go-kyo",
        "resumo": "Tori segura a faixa do uke — por cima ou por baixo do braço — e "
                  "o levanta sobre o quadril."},
    "Harai-goshi": {
        "traducao": "varrida de perna com apoio de quadril",
        "familia": "koshi", "serie": "2ª série do Go-kyo",
        "resumo": "Tori encaixa o quadril, desequilibra o uke à frente e varre a "
                  "coxa e o lado do corpo dele com a perna estendida."},
    "Hane-goshi": {
        "traducao": "impulso do quadril",
        "familia": "koshi", "serie": "3ª série do Go-kyo",
        "resumo": "Com a perna semiflexionada, tori levanta o lado do corpo do uke "
                  "num impulso de mola, e não com uma varrida."},
    "Ushiro-goshi": {
        "traducao": "arremesso do uke de costas",
        "familia": "koshi", "serie": "5ª série do Go-kyo",
        "resumo": "Contragolpe de quadril: quando o uke entra, tori o levanta pela "
                  "cintura e o derruba de costas no tatame."},
    "Utsuri-goshi": {
        "traducao": "arremesso com troca de quadril",
        "familia": "koshi", "serie": "4ª série do Go-kyo",
        "resumo": "Tori levanta o uke que atacava e, com ele no ar, troca o quadril "
                  "de lado para projetá-lo no sentido contrário."},

    # ----------------------------------------------------------- ashi-waza
    "De-ashi-harai": {
        "traducao": "varrer o pé que avança",
        "familia": "ashi", "serie": "1ª série do Go-kyo",
        "resumo": "No instante em que o uke desloca o pé, tori varre a planta dele "
                  "com a sola, no sentido do passo. É tempo, não força."},
    "Hiza-guruma": {
        "traducao": "rodada com apoio no joelho",
        "familia": "ashi", "serie": "1ª série do Go-kyo",
        "resumo": "Tori apoia a sola do pé no joelho do uke e gira o corpo dele "
                  "sobre esse ponto fixo."},
    "Sasae-tsuri-komi-ashi": {
        "traducao": "bloqueio no pé com puxada",
        "familia": "ashi", "serie": "1ª série do Go-kyo",
        "resumo": "Tori bloqueia o tornozelo do uke com a sola e o puxa para cima "
                  "e para a frente, fazendo-o girar por cima do bloqueio."},
    "O-soto-gari": {
        "traducao": "grande ceifada externa",
        "familia": "ashi", "serie": "1ª série do Go-kyo",
        "resumo": "Tori desequilibra o uke para trás e ceifa por fora a perna de "
                  "apoio dele, com a parte de trás da própria coxa."},
    "O-uchi-gari": {
        "traducao": "grande ceifada interna",
        "familia": "ashi", "serie": "1ª série do Go-kyo",
        "resumo": "Tori ceifa por dentro a perna do uke, no sentido de trás, "
                  "derrubando-o de costas."},
    "Ko-soto-gari": {
        "traducao": "pequena varrida externa",
        "familia": "ashi", "serie": "2ª série do Go-kyo",
        "resumo": "Tori varre por fora o calcanhar do uke no sentido do passo dele, "
                  "derrubando-o para trás, na diagonal."},
    "Ko-uchi-gari": {
        "traducao": "pequena varredura interna",
        "familia": "ashi", "serie": "2ª série do Go-kyo",
        "resumo": "Tori varre por dentro o calcanhar do pé avançado do uke, no "
                  "mesmo sentido em que ele estava indo."},
    "Uchi-mata": {
        "traducao": "arremesso com a perna entre as coxas",
        "familia": "ashi", "serie": "2ª série do Go-kyo",
        "resumo": "Tori gira e levanta por dentro a coxa do uke com a parte de "
                  "trás da própria coxa."},
    "Ko-soto-gake": {
        "traducao": "pequena enganchada externa",
        "familia": "ashi", "serie": "3ª série do Go-kyo",
        "resumo": "Em vez de varrer, tori engancha o próprio pé por fora do calcanhar "
                  "do uke e empurra o tronco dele para trás."},
    "Ko-uchi-gake": {
        "traducao": "pequena enganchada interna",
        "familia": "ashi", "serie": "Variação do ko-uchi-gari",
        "resumo": "Como o ko-uchi-gari, mas o pé engancha a perna por dentro em vez de "
                  "varrê-la — serve quando o uke já apoiou o peso."},
    "Ashi-guruma": {
        "traducao": "rodada sobre a perna",
        "familia": "ashi", "serie": "3ª série do Go-kyo",
        "resumo": "Tori põe a perna estendida à frente das do uke, na altura do "
                  "joelho, e o faz girar por cima dela como sobre um eixo."},
    "Harai-tsuri-komi-ashi": {
        "traducao": "varrida com levantamento de perna",
        "familia": "ashi", "serie": "3ª série do Go-kyo",
        "resumo": "Tori puxa o uke para cima e para a frente e varre o pé avançado "
                  "no alto do movimento, quando ele está mais leve."},
    "O-guruma": {
        "traducao": "grande roda",
        "familia": "ashi", "serie": "4ª série do Go-kyo",
        "resumo": "A perna estendida de tori passa na altura do ventre do uke, que "
                  "gira por cima dela. Diferente do harai-goshi, o quadril não encosta."},
    "O-soto-guruma": {
        "traducao": "grande giro externo",
        "familia": "ashi", "serie": "5ª série do Go-kyo",
        "resumo": "Como o o-soto-gari, mas a perna de tori ceifa as duas pernas do "
                  "uke de uma vez."},
    "O-soto-otoshi": {
        "traducao": "grande queda brusca externa",
        "familia": "ashi", "serie": "Habukareta-waza",
        "resumo": "Tori planta a perna atrás da do uke e o derruba para trás sem "
                  "ceifar — a perna é apoio, não varrida."},
    "Nidan-ko-soto-gari": {
        "traducao": "pequena varredura externa em dois tempos",
        "familia": "ashi", "serie": "Variação do ko-soto-gari",
        "resumo": "Tori salta duas vezes no mesmo sentido e varre o calcanhar do "
                  "uke na segunda batida, quando ele já está em desequilíbrio."},
    "Hane-goshi-gaeshi": {
        "traducao": "contragolpe do hane-goshi",
        "familia": "ashi", "serie": "Shinmeisho-no-waza · contragolpe",
        "resumo": "Quando o uke entra de hane-goshi, tori bloqueia a perna de "
                  "impulso dele e devolve a projeção no sentido do giro."},
    "Harai-goshi-gaeshi": {
        "traducao": "contragolpe do harai-goshi",
        "familia": "ashi", "serie": "Shinmeisho-no-waza · contragolpe",
        "resumo": "Tori segura a perna que varre e derruba o uke para o mesmo lado "
                  "em que ele estava girando."},

    # -------------------------------------------------------- sutemi-waza
    "Tomoe-nage": {
        "traducao": "arremesso circular",
        "familia": "ma", "serie": "3ª série do Go-kyo",
        "resumo": "Tori senta sob o uke, apoia o pé no ventre dele e o lança por "
                  "cima da própria cabeça."},
    "Sumi-gaeshi": {
        "traducao": "arremesso encaixado em ângulo para trás",
        "familia": "ma", "serie": "4ª série do Go-kyo",
        "resumo": "Tori senta, apoia o pé na parte interna da coxa do uke e o "
                  "lança na diagonal por cima da própria cabeça."},
    "Ura-nage": {
        "traducao": "arremesso invertido para trás",
        "familia": "ma", "serie": "5ª série do Go-kyo",
        "resumo": "Tori envolve o uke pela cintura e se joga para trás, lançando-o "
                  "por cima do próprio ombro."},
    "Tawara-gaeshi": {
        "traducao": "arremesso do saco de arroz",
        "familia": "ma", "serie": "Habukareta-waza",
        "resumo": "Quando o uke se abaixa para atacar, tori o abraça pelo tronco e "
                  "o joga por cima da cabeça, como quem vira um fardo."},
    "Yoko-otoshi": {
        "traducao": "queda brusca lateral",
        "familia": "yoko", "serie": "3ª série do Go-kyo",
        "resumo": "Tori se joga de lado estendendo a perna junto ao pé do uke, que "
                  "cai para o lado."},
    "Tani-otoshi": {
        "traducao": "queda no vale",
        "familia": "yoko", "serie": "4ª série do Go-kyo",
        "resumo": "Tori se joga de lado e estende a perna por trás das duas pernas do "
                  "uke, derrubando-o para trás."},
    "Hane-makikomi": {
        "traducao": "projeção com enrolamento e elevação do quadril",
        "familia": "yoko", "serie": "4ª série do Go-kyo",
        "resumo": "É o hane-goshi em que tori enrola o braço do uke e cai junto, "
                  "de lado, por cima dele."},
    "Soto-makikomi": {
        "traducao": "projeção de enrolamento externo",
        "familia": "yoko", "serie": "4ª série do Go-kyo",
        "resumo": "Tori enrola o braço do uke por fora, gira e se joga de lado, "
                  "levando-o junto."},
    "Harai-makikomi": {
        "traducao": "enrolamento com varrida de quadril",
        "familia": "yoko", "serie": "Shinmeisho-no-waza",
        "resumo": "O harai-goshi terminado em enrolamento: tori prende o braço do "
                  "uke e cai junto com ele."},
    "Uchi-makikomi": {
        "traducao": "projeção de enrolamento interior",
        "familia": "yoko", "serie": "Habukareta-waza",
        "resumo": "Tori entra por dentro, enrola o braço do uke e se joga de lado."},
    "Uki-waza": {
        "traducao": "arremesso flutuante",
        "familia": "yoko", "serie": "5ª série do Go-kyo",
        "resumo": "Tori se joga de lado estendendo a perna à frente do pé do uke, "
                  "que cai no próprio avanço."},
    "Yoko-wakare": {
        "traducao": "separação lateral",
        "familia": "yoko", "serie": "5ª série do Go-kyo",
        "resumo": "Tori se joga à frente dos pés do uke, deslizando de lado e "
                  "puxando-o por cima de si."},
    "Yoko-guruma": {
        "traducao": "roda lateral",
        "familia": "yoko", "serie": "5ª série do Go-kyo",
        "resumo": "Quando o uke se abaixa, tori passa por baixo, joga-se de lado e "
                  "o faz girar por cima. É o contragolpe clássico do ura-nage defendido."},
    "Yoko-gake": {
        "traducao": "enganchada lateral",
        "familia": "yoko", "serie": "5ª série do Go-kyo",
        "resumo": "Tori engancha o pé do uke por fora e se joga de lado no mesmo "
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
        "resumo": "A imobilização lateral clássica: tori controla o uke de lado, "
                  "usando o peso do próprio corpo sobre o peito dele.",
        "passos": [
            "Tori fica de lado ao uke, em taka-kyoshi, bem próximo.",
            "Um braço segura o braço do uke junto ao corpo, prendendo o pulso dele "
            "sob a própria axila.",
            "O outro braço envolve o pescoço por baixo da cabeça e segura a lapela.",
            "A perna do lado da cabeça fica estendida e a outra dobrada, com o pé firme "
            "no solo.",
            "O peso do corpo fica distribuído sobre o peito do uke.",
        ]},
    "Kuzure-kesa-gatame": {
        "traducao": "variação do kesa-gatame",
        "familia": "osaekomi", "serie": "Forma oficial do Kodokan",
        "resumo": "Em vez de envolver a cabeça, tori passa o braço por baixo da axila do "
                  "uke — dá mais estabilidade e menos risco de ser girado.",
        "passos": [
            "Tori fica de lado, em taka-kyoshi, com o tronco voltado para o tórax do "
            "uke.",
            "Um braço envolve e prende o braço do uke contra o próprio corpo.",
            "O outro braço passa por baixo da axila dele, com o antebraço e a mão "
            "espalmados no tatame.",
            "A perna do lado da cabeça estendida, a outra dobrada com o pé no solo.",
            "O tronco fica ereto e o peso projetado sobre o tórax e o abdômen.",
        ]},
    "Kata-gatame": {
        "traducao": "imobilização pelo ombro",
        "familia": "osaekomi", "serie": "Forma oficial do Kodokan",
        "resumo": "Tori prende o próprio braço do uke contra o rosto dele e fecha "
                  "as mãos do outro lado da cabeça.",
        "passos": [
            "Tori fica de lado ao uke, em taka-kyoshi.",
            "Com as duas mãos, posiciona o braço do uke à frente do rosto dele.",
            "A cabeça de tori desce para perto do tatame, com o ombro pressionando o "
            "lado do rosto do uke.",
            "Os braços abraçam o pescoço até as mãos se encontrarem, formando um cadeado.",
            "Um joelho fica na altura da faixa do uke e a outra perna estendida.",
        ]},
    "Makura-kesa-gatame": {
        "traducao": "imobilização em echarpe com travesseiro",
        "familia": "osaekomi", "serie": "Variação do kesa-gatame",
        "resumo": "Makura é travesseiro: o braço do uke — ou a coxa de tori — vira "
                  "apoio da cabeça dele, o que trava o pescoço e impede o giro.",
        "passos": [
            "Tori fica de lado, com o peito voltado para o tronco do uke.",
            "Segura o interior da manga dele, prendendo o cotovelo sob o próprio braço e "
            "o pulso na axila.",
            "Abraça a cabeça do uke e segura a parte interna da própria perna — é "
            "isso que dá o efeito makura.",
            "As pernas seguem a base do kesa: uma estendida, a outra dobrada com o pé "
            "firme no solo.",
        ]},
    "Ushiro-kesa-gatame": {
        "traducao": "imobilização em diagonal de costas",
        "familia": "osaekomi", "serie": "Forma oficial do Kodokan",
        "resumo": "O kesa-gatame invertido: tori imobiliza de costas para a cabeça do "
                  "uke, o que muda a direção inteira do controle.",
        "passos": [
            "Tori fica ao lado e um pouco atrás, de costas para a cabeça do uke.",
            "Um braço envolve o braço dele, prendendo-o contra o próprio corpo.",
            "O outro passa por baixo do tronco, segurando o judogui ou a faixa.",
            "Uma perna estendida e a outra dobrada, com o pé firme, na base do kesa.",
            "A cabeça de tori fica baixa, perto do solo, para não ser contra-atacado.",
        ]},
    "Kami-shiho-gatame": {
        "traducao": "imobilização pelos quatro apoios, pela cabeça",
        "familia": "osaekomi", "serie": "Forma oficial do Kodokan",
        "resumo": "Tori controla por cima da cabeça, segurando a faixa dos dois lados, "
                  "com o peito sobre o tórax do uke.",
        "passos": [
            "Tori se posiciona à frente da cabeça do uke, ajoelhado e centralizado "
            "sobre o tórax dele.",
            "Os dois braços passam por baixo dos braços do uke e seguram a faixa.",
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
            "Tori à frente da cabeça do uke, ajoelhado e centralizado sobre o tórax.",
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
                  "uke, dominando tronco e quadril ao mesmo tempo.",
        "passos": [
            "Tori fica ao lado, deitado transversalmente em relação ao corpo do uke.",
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
                  "ou do tronco do uke — útil quando ele tenta escapar.",
        "passos": [
            "Tori lateral ao uke, deitado transversalmente, como no yoko-shiho.",
            "Um braço passa por cima do braço ou do tronco; o outro controla a parte "
            "superior pela faixa, pela gola ou apoiado no ombro.",
            "Peito e abdômen pressionando a lateral do tórax, centro de gravidade baixo.",
            "Cotovelos apoiados no solo e pernas abertas com os joelhos dobrados.",
        ]},
    "Tate-shiho-gatame": {
        "traducao": "imobilização pelos quatro apoios, montado",
        "familia": "osaekomi", "serie": "Forma oficial do Kodokan",
        "resumo": "Tori monta sobre o tronco do uke de frente, o que dá o controle "
                  "mais amplo de todas as imobilizações.",
        "passos": [
            "Tori se aproxima de frente, em taka-kyoshi.",
            "Segura o interior de uma das mangas, prendendo o cotovelo do lado contrário "
            "sob o próprio braço.",
            "Desliza o outro braço do uke até a altura do ombro dele e, ao mesmo "
            "tempo, passa a perna por cima, montando.",
            "Abraça o pescoço segurando fundo a parte de trás da lapela, baixando o "
            "tronco ao mesmo tempo.",
            "Os joelhos ficam bem abertos e firmes no chão, impedindo o giro.",
        ]},
    "Kuzure-tate-shiho-gatame": {
        "traducao": "variação do tate-shiho-gatame",
        "familia": "osaekomi", "serie": "Forma oficial do Kodokan",
        "resumo": "A montada com pegada adaptada: tori eleva os dois braços do uke "
                  "acima da cabeça dele e os prende por baixo, nas próprias mangas.",
        "passos": [
            "Tori se aproxima de frente, em taka-kyoshi.",
            "Com as duas mãos, eleva um braço do uke acima da cabeça dele e em "
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
            "Tori fica de frente para o uke, em geral com ele de costas no tatame.",
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
            "Tori de frente, com o uke de costas no tatame.",
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
            "Tori de frente para o uke, de costas no tatame ou na guarda.",
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
            "Tori de frente, com o uke sentado ou de costas no tatame.",
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
            "Tori de frente, com o uke sentado ou de costas.",
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
            "Tori fica atrás, com o joelho na linha da coluna do uke para "
            "estabilizar.",
            "Encosta o dorso de uma das mãos no ombro dele.",
            "Com a outra mão, desliza pela frente do pescoço, palma para baixo, e segura "
            "a própria mão.",
            "Fecha os braços e puxa para trás, abaixando a cabeça sobre as mãos.",
        ]},
    "Kata-ha-jime": {
        "traducao": "estrangulamento de uma asa",
        "familia": "shime", "serie": "Forma oficial do Kodokan",
        "resumo": "Uma mão na gola e a outra travando o braço do uke como uma asa: "
                  "ele perde o lado que usaria para se defender.",
        "passos": [
            "Tori por trás, com o uke sentado.",
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
            "Tori se posiciona atrás do uke.",
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
            "Um braço passa por cima do ombro do uke e o outro por baixo do queixo, "
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
            "Com o uke em três apoios, tori se aproxima pela frente e faz a "
            "kumi-kata, segurando a gola com quatro dedos por dentro.",
            "Desequilibra-o para a frente passando a perna por cima da nuca dele e "
            "lateralizando o quadril.",
            "Cruza a outra perna, prendendo o pé na articulação do joelho — o braço do "
            "uke fica preso entre as pernas.",
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
            "Puxa o uke para trás e em seguida o desliza para a frente.",
            "Senta na altura da omoplata dele, em postura de kesa, e gira levemente o "
            "tronco para efetuar o estrangulamento.",
        ]},
    "Jigoku-jime": {
        "traducao": "estrangulamento do inferno",
        "familia": "shime", "serie": "Variação clássica",
        "resumo": "Combina o estrangulamento das mãos com o controle das pernas — as "
                  "pernas viram um laço que tira qualquer defesa.",
        "passos": [
            "Com o uke em seis apoios, tori se aproxima pela esquerda e segura a "
            "gola direita dele com a mão esquerda.",
            "Usa a perna esquerda para travar o braço esquerdo do uke.",
            "Com a mão direita, giro interno para segurar a manga pela parte interna do "
            "antebraço.",
            "Rola por cima das costas dele, terminando de costas no tatame com o "
            "uke por cima.",
            "Prende a perna e o braço dele, passa a mão direita por trás da nuca e eleva "
            "o quadril para aplicar a pressão.",
        ]},

    # ------------------------------------------------------- kansetsu-waza
    "Ude-garami": {
        "traducao": "chave de braço enrolado",
        "familia": "kansetsu", "serie": "Forma oficial do Kodokan",
        "resumo": "O braço do uke fica dobrado em 90° e tori o torce enrolando os "
                  "próprios braços nele, pressionando cotovelo e ombro.",
        "passos": [
            "Tori está ao lado do uke, em posição de domínio, como no "
            "yoko-shiho-gatame.",
            "Segura o punho dele com uma das mãos e passa o outro braço por baixo do "
            "braço dele, mantendo-o dobrado a 90°.",
            "Passa o próprio braço por sobre o antebraço do uke e segura o próprio "
            "punho.",
            "Mantém o cotovelo dele fixo e eleva lentamente o punho, gerando a torção.",
        ]},
    "Ude-gatame": {
        "traducao": "chave de braço no cotovelo estendido",
        "familia": "kansetsu", "serie": "Forma oficial do Kodokan",
        "resumo": "Tori estende o braço do uke e pressiona o cotovelo com as duas "
                  "mãos, usando o próprio tronco ou ombro como apoio.",
        "passos": [
            "Com a kumi-kata feita, tori prende com a cabeça a mão que o uke tem na "
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
            "O gatilho é o uke esticar o braço para empurrar tori.",
            "Tori segura o punho dele firme com as duas mãos, trazendo o braço para o "
            "centro do próprio peito.",
            "Lança uma perna por cima da cabeça do uke, com a parte de trás da coxa "
            "sobre o rosto dele, e a outra sob o tronco; os joelhos ficam unidos.",
            "Deita-se de costas com o braço preso entre as coxas, o polegar do uke "
            "virado para cima e o cotovelo dele no centro da linha do quadril.",
        ]},
    "Hiza-gatame": {
        "traducao": "chave com auxílio do joelho",
        "familia": "kansetsu", "serie": "Forma oficial do Kodokan",
        "resumo": "O joelho de tori é o ponto de apoio sobre o qual o cotovelo do "
                  "uke é estendido.",
        "passos": [
            "Tori ajoelhado ou com um joelho no solo, em controle superior.",
            "Envolve o braço do uke, encaixando a mão dele na própria axila.",
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
            "Com o braço do uke estendido, tori segura firme o punho dele, polegar "
            "voltado para baixo.",
            "Encaixa o cotovelo dele na própria axila e fecha o braço sobre a "
            "articulação.",
            "Empurra o punho para baixo e para trás, pressionando com o tronco à frente "
            "ou girando o corpo.",
            "Mantém pés ou joelhos firmes no solo para o uke não girar.",
        ]},
    "Hara-gatame": {
        "traducao": "chave de braço com o abdômen",
        "familia": "kansetsu", "serie": "Forma oficial do Kodokan",
        "resumo": "O abdômen de tori é a base fixa sobre a qual o cotovelo do uke "
                  "é hiperestendido.",
        "passos": [
            "Tori em posição superior, os dois em pé.",
            "Segura o braço do uke estendido, com o cotovelo centralizado em "
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


# ---------------------------------------------- execução das projeções
# As técnicas de solo trazem os passos da apostila de Katame-Waza da FPJU.
# Para as projeções não existe material equivalente: a apostila de Nage-Waza
# da FPJU é só imagem (um cartaz com as listas, sem texto), e a de Nage-no-Kata
# descreve a coreografia do kata — passos, distâncias, tsugi-ashi — e não a
# execução da técnica em si. Os passos abaixo seguem a execução padrão do
# Kodokan, na ordem em que a aula ensina: kuzushi (quebra do equilíbrio),
# tsukuri (encaixe), kake (aplicação) e o ponto onde a técnica costuma falhar.
PASSOS_NAGE = {
    # ------------------------------------------------------------ te-waza
    "Seoi-nage": [
        "Kuzushi para a frente e para cima, levantando o uke na ponta dos pés.",
        "Gire de costas em dois tempos, joelhos flexionados, quadril abaixo do dele.",
        "Os dois braços carregam: o da gola passa por baixo da axila, o da manga puxa.",
        "Estenda as pernas e gire o tronco — a projeção vem das pernas, não dos braços.",
    ],
    "Ippon-seoi-nage": [
        "Kuzushi para a frente, puxando a manga para cima.",
        "Solte a gola e passe o próprio braço por dentro da axila do uke, "
        "encaixando o braço dele no ombro.",
        "Gire de costas com o quadril abaixo do dele e o cotovelo bem alto.",
        "Estenda as pernas projetando à frente; a mão da manga nunca larga.",
    ],
    "Tai-otoshi": [
        "Kuzushi para a frente, na diagonal do ombro do uke.",
        "Gire o corpo e estenda a perna à frente do tornozelo dele — a perna é "
        "barreira, não varre.",
        "As duas mãos giram como um volante, levando o tronco dele por cima da perna.",
        "O quadril não encosta: quem derruba são as mãos.",
    ],
    "Kata-guruma": [
        "Kuzushi para a frente, puxando a manga para baixo e para o lado.",
        "Abaixe entrando com a cabeça por baixo do braço, o ombro na altura da "
        "virilha dele.",
        "Carregue atravessado sobre os ombros, segurando a perna com a mão livre.",
        "Levante com as pernas e gire para a frente, soltando-o à sua frente.",
    ],
    "Uki-otoshi": [
        "Kuzushi para a frente, no canto da ponta do pé dele.",
        "Recue um pé e leve um joelho ao tatame, mantendo os braços estendidos.",
        "As mãos descrevem um arco para baixo, na diagonal, acompanhando a queda.",
        "Nenhuma perna toca o uke — só as mãos e o deslocamento.",
    ],
    "Sumi-otoshi": [
        "Kuzushi para o canto de trás, empurrando a gola e puxando a manga.",
        "Desloque-se para fora da base dele, abrindo o ângulo.",
        "As mãos levam o tronco para o canto onde ele não tem apoio.",
        "Também é só de mãos: nenhum contato de perna ou quadril.",
    ],
    "Sukui-nage": [
        "Entre por baixo, pelo lado ou por trás, com o centro de gravidade baixo.",
        "Passe os braços por baixo do quadril ou das pernas dele.",
        "Levante com as pernas, recolhendo como quem usa uma pá.",
        "Gire-o para trás e acompanhe a queda sem soltar.",
    ],
    "Morote-gari": [
        "Abaixe entrando com um passo profundo, a cabeça ao lado do tronco dele.",
        "Os dois braços envolvem as pernas na altura dos joelhos.",
        "Puxe as pernas para você e empurre o tronco dele para trás com o ombro.",
        "A cabeça nunca entra por baixo do braço do uke.",
    ],
    "Kuchiki-taoshi": [
        "Kuzushi para trás ou para o lado, quebrando a postura.",
        "Abaixe e agarre a perna por fora, na altura do joelho ou do tornozelo.",
        "Puxe a perna na sua direção e empurre o tronco no sentido contrário.",
        "O nome é 'derrubar a árvore podre': a perna sai, o tronco cai sozinho.",
    ],
    "Kibisu-gaeshi": [
        "Kuzushi puxando o uke para a frente, para ele carregar o peso.",
        "Abaixe e pegue o calcanhar por trás, com a palma para cima.",
        "Levante o calcanhar enquanto empurra o peito dele para trás.",
        "É uma ação só: se levantar sem empurrar, ele apenas recua o pé.",
    ],
    "Uchi-mata-sukashi": [
        "Reconheça a entrada: o uke gira para aplicar uchi-mata.",
        "Recolha a perna atacada, deixando a dele passar no vazio.",
        "Gire as mãos no sentido do giro dele, somando-se ao impulso.",
        "Não há força: ele cai no próprio movimento.",
    ],
    "O-soto-sukashi": [
        "Reconheça a entrada do o-soto-gari.",
        "Gire o quadril e recolha a perna que seria ceifada.",
        "Mantenha as mãos firmes, conduzindo o tronco dele no sentido do ataque.",
        "O tempo é tudo: cedo demais ele reequilibra, tarde demais a ceifa pega.",
    ],

    # --------------------------------------------------------- koshi-waza
    "O-goshi": [
        "Kuzushi para a frente e para cima.",
        "Gire de costas e solte a gola, envolvendo a cintura dele pelas costas.",
        "Encaixe o quadril abaixo do dele, pernas flexionadas e pés dentro da base.",
        "Estenda as pernas levantando e gire o tronco — ele passa por cima do quadril.",
    ],
    "Uki-goshi": [
        "Kuzushi para a frente, em rotação.",
        "Entre de lado, com o quadril pela lateral e sem abaixar as pernas.",
        "O braço envolve a cintura e o outro puxa a manga no sentido do giro.",
        "Não levanta: a projeção é de rotação, e por isso é a mais sutil do grupo.",
    ],
    "Koshi-guruma": [
        "Kuzushi para a frente e para cima.",
        "Gire de costas com o quadril passando além do dele.",
        "O braço envolve o pescoço, trazendo a cabeça dele junto ao seu ombro.",
        "Gire: ele roda sobre o quadril como sobre um eixo.",
    ],
    "Tsuri-komi-goshi": [
        "Kuzushi para cima pela gola, levantando a postura dele.",
        "Gire de costas abaixando bem o quadril, mais baixo do que no o-goshi.",
        "O cotovelo da gola fica alto, mantendo o uke suspenso.",
        "Estenda as pernas: ele passa por cima do quadril baixo.",
    ],
    "Tsuri-goshi": [
        "Kuzushi para cima, puxando a gola.",
        "Passe a mão na faixa dele — por cima do braço (o-tsuri) ou por baixo (ko-tsuri).",
        "Gire de costas e encaixe o quadril, usando a faixa para suspender.",
        "Levante com as pernas e gire; a faixa dá o controle que a cintura não daria.",
    ],
    "Harai-goshi": [
        "Kuzushi para a frente e na diagonal, desequilibrando sobre a ponta dos pés.",
        "Gire de costas com o quadril encostando no dele, apoiado numa perna só.",
        "A perna livre estende e varre a coxa e o lado do corpo dele.",
        "Quadril e perna agem juntos: só o quadril é o-goshi, só a perna é ashi-waza.",
    ],
    "Hane-goshi": [
        "Kuzushi para a frente e para cima.",
        "Gire de costas e encaixe o quadril, apoiado numa perna.",
        "A outra perna fica semiflexionada, com a coxa e a panturrilha sob a coxa dele.",
        "O impulso é de mola, para cima — não é varrida.",
    ],
    "Ushiro-goshi": [
        "Reconheça a entrada de quadril do uke e abaixe o centro de gravidade.",
        "Envolva a cintura dele pela frente, colando o peito nas costas dele.",
        "Levante com as pernas, tirando-o do chão enquanto o ataque dele passa no vazio.",
        "Recue o quadril e deixe-o cair de costas, acompanhando com os braços.",
    ],
    "Utsuri-goshi": [
        "Mesma defesa do ushiro-goshi: abaixe e levante o uke pela cintura.",
        "Com ele no ar, troque o quadril de lado, girando por baixo.",
        "Encaixe o quadril do outro lado, agora como quem ataca.",
        "Projete no sentido contrário ao do ataque dele.",
    ],

    # ---------------------------------------------------------- ashi-waza
    "De-ashi-harai": [
        "Acompanhe o deslocamento do uke, sem forçar o passo.",
        "No instante em que o pé sai do tatame e ainda não apoiou, varra a planta "
        "com a sola do seu pé.",
        "As mãos giram no sentido da varrida, levando o tronco dele junto.",
        "É tempo, não força: com o peso apoiado, a varrida não sai.",
    ],
    "Hiza-guruma": [
        "Kuzushi para a frente, na diagonal.",
        "Apoie a sola do pé na lateral do joelho dele, perna estendida.",
        "Gire as mãos como um volante em torno desse ponto de apoio.",
        "O pé bloqueia, não empurra: quem gira o corpo são as mãos.",
    ],
    "Sasae-tsuri-komi-ashi": [
        "Kuzushi para cima e para a frente, puxando a gola.",
        "Apoie a sola do pé no tornozelo ou na canela dele, perna estendida.",
        "Gire as mãos em arco, levando-o por cima do bloqueio.",
        "A perna de apoio fica flexionada: é dela que sai o equilíbrio.",
    ],
    "O-soto-gari": [
        "Kuzushi para trás, na diagonal do calcanhar dele.",
        "Dê um passo ao lado do pé dele, com a sua perna de apoio alinhada.",
        "A perna de ataque balança à frente e volta ceifando por fora, com a parte "
        "de trás da coxa.",
        "Peito colado e cabeça baixa: afastar o tronco é o erro clássico.",
    ],
    "O-uchi-gari": [
        "Kuzushi para trás, abrindo a base dele.",
        "Entre com a perna por dentro das pernas dele.",
        "Ceife a perna de dentro para fora, acompanhando com o peito e com as mãos.",
        "Não pare na ceifa: avance junto, senão ele recupera o apoio.",
    ],
    "Ko-soto-gari": [
        "Kuzushi na diagonal de trás, para o lado do calcanhar atacado.",
        "Saia da linha dele com um passo lateral.",
        "Varra o calcanhar por fora, no sentido do passo que ele já estava dando.",
        "As mãos puxam para baixo, no mesmo sentido da varrida.",
    ],
    "Ko-uchi-gari": [
        "Kuzushi para trás, no pé avançado.",
        "Avance o próprio pé em direção ao calcanhar dele, por dentro.",
        "Varre no sentido em que o pé dele já ia — não contra.",
        "Empurre o tronco na diagonal de trás enquanto varre.",
    ],
    "Uchi-mata": [
        "Kuzushi para a frente, trazendo o uke para as suas costas.",
        "Gire em dois ou três tempos, apoiado numa perna, quadril encaixado.",
        "A perna de ataque entra entre as coxas dele e sobe pela face interna.",
        "A cabeça baixa e o braço da manga puxam para baixo; o corpo todo gira.",
    ],
    "Ko-soto-gake": [
        "Kuzushi para trás, na diagonal.",
        "Engate o próprio pé por fora, no calcanhar ou na panturrilha dele.",
        "Empurre o tronco para trás enquanto o pé segura a perna no lugar.",
        "Diferente do gari, o pé não varre: prende.",
    ],
    "Ko-uchi-gake": [
        "Kuzushi para trás, no pé que recebeu o peso.",
        "Engate o pé por dentro, na panturrilha dele.",
        "Empurre o tronco na diagonal, mantendo o engate.",
        "Serve quando o peso já está apoiado e a varrida do ko-uchi-gari não sairia.",
    ],
    "Ashi-guruma": [
        "Kuzushi para a frente e na diagonal.",
        "Gire o corpo e ponha a perna estendida à frente das pernas dele, na altura "
        "do joelho.",
        "As mãos giram levando o tronco por cima da perna, como sobre um eixo.",
        "A perna não varre nem o quadril encosta: é só o eixo do giro.",
    ],
    "Harai-tsuri-komi-ashi": [
        "Kuzushi para cima e para a frente, puxando a gola alto.",
        "Espere o momento em que ele está mais leve, no alto do movimento.",
        "Varra o pé avançado com a sola, perna estendida.",
        "Mãos e perna agem juntas: sem a suspensão, a varrida não sai.",
    ],
    "O-guruma": [
        "Kuzushi para a frente e para cima.",
        "Gire o corpo e passe a perna estendida à frente, na altura do ventre dele.",
        "As mãos giram levando-o por cima da perna.",
        "O quadril não encosta — é o que separa o o-guruma do harai-goshi.",
    ],
    "O-soto-guruma": [
        "Kuzushi para trás, como no o-soto-gari.",
        "Entre com a perna estendida por fora, mas mais funda: passando as duas "
        "pernas dele.",
        "Ceife as duas de uma vez, girando o tronco dele para trás.",
        "Peito colado; a perna vai alta, na altura das coxas.",
    ],
    "O-soto-otoshi": [
        "Kuzushi para trás, na diagonal do calcanhar.",
        "Plante a perna atrás da dele, firme no tatame — não balança nem ceifa.",
        "Empurre o tronco para trás por cima da perna plantada.",
        "A perna é apoio: quem derruba é o deslocamento do peso.",
    ],
    "Nidan-ko-soto-gari": [
        "Comece o deslocamento lateral junto com o uke.",
        "Dê um primeiro salto no sentido do movimento, sem varrer.",
        "No segundo tempo, varra o calcanhar dele, já em desequilíbrio.",
        "O ritmo é o ataque: um tempo só não tira o apoio.",
    ],
    "Hane-goshi-gaeshi": [
        "Reconheça a entrada de hane-goshi do uke.",
        "Abaixe o centro de gravidade e bloqueie a perna de impulso dele.",
        "Levante a perna dele pelo lado de fora, somando-se ao giro.",
        "Projete no mesmo sentido em que ele girava.",
    ],
    "Harai-goshi-gaeshi": [
        "Reconheça a entrada de harai-goshi.",
        "Abaixe e segure a perna que varre, por fora.",
        "Gire o tronco no sentido do ataque dele, levantando essa perna.",
        "Ele cai para o mesmo lado para onde girava.",
    ],

    # ------------------------------------------------------ ma-sutemi-waza
    "Tomoe-nage": [
        "Kuzushi para a frente, puxando o uke sobre você.",
        "Apoie o pé no ventre, logo abaixo do nó da faixa.",
        "Sente e deite-se, mantendo as mãos puxando a gola.",
        "Estenda a perna lançando-o por cima da sua cabeça.",
    ],
    "Sumi-gaeshi": [
        "Pegada alta, por cima do ombro ou nas costas, com o uke curvado.",
        "Apoie o peito do pé na face interna da coxa dele.",
        "Sente e role para trás, na diagonal.",
        "Levante a perna no momento do rolamento, lançando-o para o canto.",
    ],
    "Ura-nage": [
        "Reconheça o ataque e entre por baixo, com o quadril à frente do dele.",
        "Envolva a cintura ou o tronco com os dois braços.",
        "Levante com as pernas e jogue-se para trás, em arco.",
        "Gire na queda para não cair embaixo dele.",
    ],
    "Tawara-gaeshi": [
        "O gatilho é o uke abaixar para atacar as pernas.",
        "Envolva o tronco dele por cima, com os dois braços travados.",
        "Jogue-se para trás levantando-o, como quem vira um fardo.",
        "Gire o corpo na queda para terminar por cima.",
    ],

    # ---------------------------------------------------- yoko-sutemi-waza
    "Yoko-otoshi": [
        "Kuzushi para o lado, puxando a manga.",
        "Estenda a perna junto ao pé dele, no sentido da queda.",
        "Deixe-se cair de lado, nunca de costas.",
        "As mãos puxam para baixo, acompanhando o corpo dele por cima da perna.",
    ],
    "Tani-otoshi": [
        "Entre pelo lado ou por trás, colando o quadril ao dele.",
        "Estenda a perna por trás das duas pernas dele.",
        "Jogue-se de lado, levando o peso dele para trás por cima da perna.",
        "Cuidado com a perna dele presa: o movimento é para trás, não torcendo.",
    ],
    "Hane-makikomi": [
        "Entre como no hane-goshi, com a perna de impulso encaixada.",
        "Solte a gola e enrole o braço dele, prendendo-o contra o seu peito.",
        "Continue o giro jogando-se de lado.",
        "Caia por cima, sem largar o braço enrolado.",
    ],
    "Soto-makikomi": [
        "Kuzushi para a frente, na diagonal.",
        "Gire de costas e enrole o braço do uke por fora, por baixo da axila.",
        "Siga o giro e jogue-se de lado, levando-o junto.",
        "O braço preso é o que garante que ele vá junto.",
    ],
    "Harai-makikomi": [
        "Entre como no harai-goshi, varrendo a coxa dele.",
        "Em vez de completar a varrida de pé, enrole o braço dele.",
        "Gire e caia de lado, levando-o por cima.",
        "É a saída de quando o harai-goshi não termina em pé.",
    ],
    "Uchi-makikomi": [
        "Entre por dentro, entre os braços do uke.",
        "Enrole o braço dele por dentro, prendendo-o no seu tronco.",
        "Gire e jogue-se de lado.",
        "A diferença para o soto-makikomi é só por onde o braço é enrolado.",
    ],
    "Uki-waza": [
        "Kuzushi para a frente, no sentido do avanço dele.",
        "Estenda a perna à frente do pé dele, como barreira baixa.",
        "Deixe-se cair de lado, puxando as mãos para baixo e para trás.",
        "Quem derruba é o próprio avanço dele somado à sua queda.",
    ],
    "Yoko-wakare": [
        "Kuzushi para a frente, puxando com as duas mãos.",
        "Jogue-se à frente dos pés dele, deslizando de lado sob o corpo dele.",
        "As mãos não soltam: puxam para baixo enquanto você desliza.",
        "Ele passa por cima, separado da própria base.",
    ],
    "Yoko-guruma": [
        "O gatilho é o uke se abaixar, defendendo um ura-nage.",
        "Passe por baixo do braço dele, entrando de lado.",
        "Jogue-se de lado estendendo a perna, com o braço envolvendo o tronco.",
        "Ele gira por cima de você, em roda.",
    ],
    "Yoko-gake": [
        "Kuzushi para o lado, no momento do passo dele.",
        "Engate ou varra o pé dele por fora com a sola.",
        "Jogue-se de lado ao mesmo tempo, sem soltar as mãos.",
        "A queda sua e a varrida são um movimento só.",
    ],
}

for _nome, _passos in PASSOS_NAGE.items():
    if _nome in TECNICAS:
        TECNICAS[_nome]["passos"] = _passos
    _INDICE[_norm(_nome)]["passos"] = _passos


# ------------------------------------------- termos usados nas descrições
# As fichas acima explicam o nome da técnica, mas as descrições em si usam
# vocabulário de tatame: "tori", "uke", "kuzushi". Esses termos só são cobrados
# em promoções adiantadas — quem está na branca lia "Tori desequilibra o uke"
# sem ter onde descobrir quem é quem. A legenda do material sai desta lista.
#
# Só entra termo que aparece mesmo nos textos; `termos_citados()` confere.
TERMOS_DO_TEXTO = [
    {"termo": "tori", "significado": "quem aplica a técnica"},
    {"termo": "uke", "significado": "quem recebe a técnica"},
    {"termo": "kuzushi", "significado": "a quebra do equilíbrio, que abre a técnica"},
    {"termo": "tsukuri", "significado": "o encaixe, a preparação do corpo"},
    {"termo": "kake", "significado": "a execução, o momento da projeção"},
    {"termo": "hikite", "significado": "a mão que puxa, na manga"},
    {"termo": "tsurite", "significado": "a mão que suspende, na gola"},
    {"termo": "taka-kyoshi", "significado": "postura de joelho alto, de aproximação no solo"},
    {"termo": "tatame", "significado": "o piso do dojô"},
]


def _textos_das_fichas():
    for v in TECNICAS.values():
        yield v.get("resumo") or ""
        for s in v.get("passos") or []:
            yield s
    for grupo in (UKEMI, KUMI_KATA):
        for it in grupo:
            yield it.get("resumo") or ""
            for s in it.get("passos") or []:
                yield s
    yield UKEMI_NOTA
    yield KUMI_KATA_NOTA


def termos_citados(textos=None):
    """Os termos que de fato aparecem nos textos dados.

    Explicar um termo que o texto não usa é ruído; deixar sem explicar um que
    ele usa é o problema que o glossário veio resolver. Por isso a lista é
    filtrada pelo próprio texto.

    `textos` é o material que vai à tela — assim o glossário de uma promoção
    fala só do vocabulário que ELA usa. Sem argumento, varre o módulo inteiro.
    """
    import re
    junto = " ".join(textos if textos is not None else _textos_das_fichas()).lower()
    return [t for t in TERMOS_DO_TEXTO
            if re.search(r"\b" + re.escape(t["termo"]) + r"\b", junto)]
