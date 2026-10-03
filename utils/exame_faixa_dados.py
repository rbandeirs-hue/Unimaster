# -*- coding: utf-8 -*-
"""Conteúdo do programa de exame de faixa — Judô ArteFísica, edição 2026.1.

Fonte: "Departamento Técnico — exame de faixa 2026.1" (PDF da associação),
uma tabela por promoção. As respostas das perguntas de conhecimento histórico
e o glossário vêm do CFPGs (/var/www/CFPGs/sistema/public/faixas.js e kyu.js),
que já tinha cruzado o material com o Regulamento de Exame e Outorga da CBJ.

A grafia dos termos segue a revisão do CFPGs onde o PDF tem erro de digitação
evidente (GATEME → gatame, KAETEM → kaiten, HANDORI → Hantai, GO-KIO → Go-kyo,
UTSUSHI-GOSHI → Utsuri-goshi). Todo o resto — itens, quantidade de itens,
idades, carências e valores — é o do PDF.

Este módulo só é lido pela migração (para semear `exame_faixa_programa`) e
pelo modo estudo (glossário). Depois de semeado, o que vale é o banco: preço,
idade e carência se editam pela tela "Tabela de preços".

Cada promoção:
  de / para       nome da faixa como está em `graduacao.faixa` (judô)
  idade_minima    anos completos na data do exame
  idade_maxima    só a primeira promoção tem ("4 a 6 anos")
  carencia_meses  tempo mínimo na faixa atual; None = sem carência
  valor           taxa do exame em reais
  conteudo        o que se cobra, por grupo:
    historico     [{q, a}]   perguntas com a resposta para estudo
    terminologia  [termo]
    reiho         [termo]    saudações
    gestos        [termo]    gestos de arbitragem
    arbitragem    [texto]
    ukemi         texto ("Dois tipos") ou [termo]
    kumikata      texto
    nage, katame  [técnica]
    kaeshi        [{a, b}]   golpe × contragolpe
    renraku       [{a, b}]   1ª técnica + 2ª técnica (renraku-henka-waza)
"""

EDICAO = "2026.1"

PROGRAMA_2026_1 = [
    {
        "de": "BRANCA", "para": "BRANCA/CINZA",
        "idade_minima": 4, "idade_maxima": 6, "carencia_meses": None, "valor": 160,
        "conteudo": {
            "historico": [{"q": "Quem fundou o judô?", "a": "Jigoro Kano, em 1882."}],
            "terminologia": ["Hajime", "Mate"],
            "ukemi": "Um tipo",
            "kumikata": "Um tipo",
            "nage": ["O-soto-gari", "O-uchi-gari"],
            "katame": ["Hon-kesa-gatame"],
        },
    },
    {
        "de": "BRANCA/CINZA", "para": "CINZA",
        "idade_minima": 5, "idade_maxima": None, "carencia_meses": 6, "valor": 200,
        "conteudo": {
            "historico": [{"q": "Ano de nascimento do fundador",
                           "a": "1860 — Jigoro Kano nasceu em 28/10/1860, em Mikage (Kobe)."}],
            "terminologia": ["Sensei", "Sore-made"],
            "ukemi": "Dois tipos",
            "kumikata": "Dois tipos",
            "nage": ["Koshi-guruma"],
            "katame": ["Yoko-shiho-gatame"],
        },
    },
    {
        "de": "CINZA", "para": "CINZA/AZUL",
        "idade_minima": 6, "idade_maxima": None, "carencia_meses": 6, "valor": 200,
        "conteudo": {
            "terminologia": ["Shihan", "Ukemi"],
            "ukemi": "Dois tipos",
            "kumikata": "Dois tipos",
            "nage": ["O-goshi"],
            "katame": ["Kata-gatame"],
        },
    },
    {
        "de": "CINZA/AZUL", "para": "AZUL",
        "idade_minima": 7, "idade_maxima": None, "carencia_meses": 6, "valor": 200,
        "conteudo": {
            "historico": [{"q": "Qual foi a primeira escola de judô?",
                           "a": "O Kodokan, fundado em 1882 no templo Eishoji, em Tóquio."}],
            "terminologia": ["Shintai", "Uchikomi"],
            "reiho": ["Za-rei", "Ritsu-rei"],
            "ukemi": "Três tipos",
            "kumikata": "Três tipos",
            "nage": ["Seoi-nage", "Ippon-seoi-nage"],
            "katame": ["Kami-shiho-gatame"],
        },
    },
    {
        "de": "AZUL", "para": "AZUL/AMARELA",
        "idade_minima": 8, "idade_maxima": None, "carencia_meses": 6, "valor": 200,
        "conteudo": {
            "historico": [{"q": "Cite um princípio do judô",
                           "a": "Seiryoku Zen'yo — máxima eficiência, mínimo esforço."}],
            "terminologia": ["Judô", "Dojo", "Osae-komi", "Toketa"],
            "ukemi": "Quatro tipos",
            "nage": ["De-ashi-harai", "Uki-goshi", "Tai-otoshi"],
            "katame": ["Tate-shiho-gatame"],
        },
    },
    {
        "de": "AZUL/AMARELA", "para": "AMARELA",
        "idade_minima": 9, "idade_maxima": None, "carencia_meses": 6, "valor": 250,
        "conteudo": {
            "historico": [
                {"q": "Cite dois princípios do judô",
                 "a": "Seiryoku Zen'yo (máxima eficiência) e Jita Kyoei (prosperidade e benefício mútuos)."},
                {"q": "Ano de fundação do judô", "a": "1882."},
            ],
            "terminologia": ["Tokui-waza", "Judogui", "Zubon", "Wagui", "Obi", "Migi",
                             "Hidari", "Hantai", "Yoko", "Shiai", "Shiai-jo"],
            "ukemi": ["Zempo-kaiten-ukemi", "Mae-ukemi", "Yoko-ukemi", "Ushiro-ukemi"],
            "nage": ["Ko-uchi-gari", "Ko-soto-gari", "Hiza-guruma", "Sasae-tsuri-komi-ashi"],
            "katame": ["Ushiro-kesa-gatame", "Kuzure-kesa-gatame"],
            "kaeshi": [
                {"a": "Seoi-nage", "b": "Ko-soto-gari"},
                {"a": "Tai-otoshi", "b": "O-soto-gari"},
                {"a": "Sasae-tsuri-komi-ashi", "b": "O-uchi-gari"},
                {"a": "O-soto-gari", "b": "O-soto-gari"},
            ],
            "renraku": [
                {"a": "De-ashi-harai", "b": "Seoi-nage"},
                {"a": "Hiza-guruma", "b": "Ko-soto-gari"},
                {"a": "O-uchi-gari", "b": "Ko-uchi-gari"},
                {"a": "De-ashi-harai", "b": "O-soto-gari"},
                {"a": "Koshi-guruma", "b": "O-uchi-gari"},
            ],
        },
    },
    {
        "de": "AMARELA", "para": "AMARELA/LARANJA",
        "idade_minima": 10, "idade_maxima": None, "carencia_meses": 6, "valor": 250,
        "conteudo": {
            "historico": [{"q": "Cite três princípios do judô",
                           "a": "Seiryoku Zen'yo (máxima eficiência), Jita Kyoei (benefício mútuo) "
                                "e Ju yoku go o seisu (a suavidade vence a força)."}],
            "terminologia": ["Waza-ari", "Ippon", "Waza-ari-awasete-ippon", "Sonomama", "Yoshi",
                             "Shido", "Hansoku-make", "Tori", "Uke"],
            "nage": ["Uchi-mata", "Harai-goshi", "Hane-goshi"],
            "katame": ["Kuzure-kami-shiho-gatame", "Makura-kesa-gatame"],
            "kaeshi": [
                {"a": "Tai-otoshi", "b": "Harai-goshi"},
                {"a": "Hane-goshi", "b": "Ko-soto-gari"},
                {"a": "Uchi-mata", "b": "Harai-goshi"},
                {"a": "Hane-goshi", "b": "Hane-goshi-gaeshi"},
            ],
            "renraku": [
                {"a": "Harai-goshi", "b": "O-soto-gari"},
                {"a": "Koshi-guruma", "b": "Harai-goshi"},
                {"a": "Uchi-mata", "b": "O-uchi-gari"},
            ],
        },
    },
    {
        "de": "AMARELA/LARANJA", "para": "LARANJA",
        "idade_minima": 11, "idade_maxima": None, "carencia_meses": 6, "valor": 270,
        "conteudo": {
            "historico": [{"q": "Pesquisa sobre a história de Jigoro Kano",
                           "a": "Nasceu em 1860 e morreu em 1938; educador, criou o judô e o Kodokan "
                                "(1882) a partir do jujutsu (escolas Tenshin Shinyo Ryu e Kito Ryu)."}],
            "gestos": ["Waza-ari", "Ippon", "Waza-ari-awasete-ippon", "Sonomama", "Yoshi"],
            "nage": ["Tsuri-goshi", "Tsuri-komi-goshi"],
            "katame": ["Kuzure-yoko-shiho-gatame", "Kuzure-tate-shiho-gatame"],
            "kaeshi": [
                {"a": "Tsuri-goshi", "b": "Harai-goshi"},
                {"a": "Tsuri-komi-goshi", "b": "Ko-soto-gari"},
                {"a": "Koshi-guruma", "b": "Tsuri-goshi"},
                {"a": "O-goshi", "b": "Tsuri-komi-goshi"},
            ],
            "renraku": [
                {"a": "Tsuri-goshi", "b": "Hane-goshi"},
                {"a": "Tsuri-komi-goshi", "b": "Tai-otoshi"},
                {"a": "Hane-goshi", "b": "O-uchi-gari"},
                {"a": "De-ashi-harai", "b": "Harai-goshi"},
            ],
        },
    },
    {
        "de": "LARANJA", "para": "VERDE",
        "idade_minima": 12, "idade_maxima": None, "carencia_meses": 12, "valor": 300,
        "conteudo": {
            "historico": [
                {"q": "Pesquisa sobre a origem do judô",
                 "a": "Surgiu do jujutsu japonês; Kano selecionou e sistematizou as técnicas com base "
                      "na eficiência e na segurança."},
                {"q": "Pesquisa sobre o nascimento do judô",
                 "a": "O Kodokan nasceu em fevereiro de 1882, no templo Eishoji, com 9 alunos."},
            ],
            "terminologia": ["Tai-sabaki", "Kuzushi", "Tsukuri", "Kake", "Jigotai",
                             "Shizen-hontai", "Go-kyo", "Kyu"],
            "nage": ["Ko-soto-gake", "Yoko-otoshi", "Ashi-guruma", "Harai-tsuri-komi-ashi",
                     "Tomoe-nage", "Kata-guruma", "Sumi-gaeshi"],
            "katame": ["Nami-juji-jime", "Kata-juji-jime", "Gyaku-juji-jime",
                       "Ude-hishigi-juji-gatame", "Ude-garami"],
            "kaeshi": [
                {"a": "Ko-soto-gake", "b": "Uchi-mata"},
                {"a": "O-uchi-gari", "b": "Tomoe-nage"},
                {"a": "Tai-otoshi", "b": "Ko-soto-gake"},
                {"a": "Ko-soto-gake", "b": "O-uchi-gari"},
                {"a": "Tomoe-nage", "b": "Ko-soto-gari"},
                {"a": "O-soto-gari", "b": "O-soto-sukashi"},
                {"a": "Harai-goshi", "b": "Harai-goshi-gaeshi"},
                {"a": "Uchi-mata", "b": "Uchi-mata-sukashi"},
            ],
            "renraku": [
                {"a": "Uki-goshi", "b": "Hane-goshi"},
                {"a": "O-uchi-gari", "b": "Tai-otoshi"},
                {"a": "Hiza-guruma", "b": "O-soto-gari"},
                {"a": "Uchi-mata", "b": "Tai-otoshi"},
                {"a": "Uki-goshi", "b": "Tomoe-nage"},
                {"a": "O-soto-gari", "b": "Nidan-ko-soto-gari"},
                {"a": "Tsuri-komi-goshi", "b": "Ko-uchi-gari"},
                {"a": "Ko-soto-gari", "b": "Ashi-guruma"},
            ],
        },
    },
    {
        "de": "VERDE", "para": "ROXA",
        "idade_minima": 13, "idade_maxima": None, "carencia_meses": 12, "valor": 360,
        "conteudo": {
            "historico": [
                {"q": "Pesquisa sobre a evolução do judô Kodokan",
                 "a": "Do Eishoji (1882), o Kodokan cresceu e difundiu o judô pelo mundo; tornou-se "
                      "esporte olímpico em Tóquio 1964."},
                {"q": "Pesquisa sobre o espírito do judô",
                 "a": "Formar o caráter pela prática — respeito, disciplina e o princípio Jita Kyoei "
                      "(prosperidade mútua)."},
            ],
            "arbitragem": ["Manusear o placar com confiança", "Pesquisa sobre as regras da arbitragem"],
            "terminologia": ["Hantei", "Hikiwake", "Fusen-gachi", "Kiken-gachi", "Yusei-gachi",
                             "Maitta", "Kodansha", "Yudansha", "Dan"],
            "nage": ["Tani-otoshi", "Hane-makikomi", "Sukui-nage", "Utsuri-goshi", "O-guruma",
                     "Soto-makikomi", "Uki-otoshi"],
            "katame": ["Hadaka-jime", "Okuri-eri-jime", "Kata-ha-jime", "Tsukkomi-jime",
                       "Hiza-gatame", "Ude-gatame"],
            "kaeshi": [
                {"a": "Morote-gari", "b": "Tawara-gaeshi"},
                {"a": "Tomoe-nage", "b": "Katame-waza"},
                {"a": "Hane-goshi", "b": "Utsuri-goshi"},
                {"a": "Hane-goshi", "b": "Tani-otoshi"},
                {"a": "Uchi-mata", "b": "Sukui-nage"},
                {"a": "Harai-goshi", "b": "Tani-otoshi"},
                {"a": "Harai-goshi", "b": "Sukui-nage"},
                {"a": "Seoi-nage", "b": "Okuri-eri-jime"},
                {"a": "O-soto-gari", "b": "Sukui-nage"},
                {"a": "Ippon-seoi-nage", "b": "Kata-ha-jime"},
                {"a": "Hiza-guruma", "b": "Kuchiki-taoshi"},
            ],
            "renraku": [
                {"a": "Ko-soto-gari", "b": "Sukui-nage"},
                {"a": "Ko-soto-gari", "b": "Nidan-ko-soto-gari"},
                {"a": "Tsuri-komi-goshi", "b": "Tani-otoshi"},
                {"a": "Yoko-otoshi", "b": "Katame-waza"},
                {"a": "Hane-goshi", "b": "Harai-goshi"},
                {"a": "O-soto-gari", "b": "Harai-goshi"},
                {"a": "Hane-goshi", "b": "Hane-makikomi"},
                {"a": "Tsuri-komi-goshi", "b": "Ko-soto-gari"},
                {"a": "Tsuri-goshi", "b": "Harai-goshi"},
            ],
        },
    },
    {
        "de": "ROXA", "para": "MARROM",
        "idade_minima": 14, "idade_maxima": None, "carencia_meses": 12, "valor": 400,
        "conteudo": {
            "historico": [
                {"q": "Pesquisa sobre a evolução do judô no Brasil",
                 "a": "Chegou com os imigrantes japoneses; Mitsuyo Maeda (Conde Koma) desembarcou em "
                      "1914; a CBJ organiza o judô nacional."},
                {"q": "Pesquisa sobre o significado filosófico do judô",
                 "a": "'Caminho suave' (Ju + Do): usar a eficiência e a adaptação — ceder para vencer "
                      "— como filosofia de vida."},
                {"q": "Quais técnicas foram excluídas das competições e por quê",
                 "a": "Ex.: kani-basami, kawazu-gake, do-jime e ashi-garami — retiradas por risco de lesão."},
            ],
            "arbitragem": ["Aprofundamento das regras",
                           "Aprofundamento dos gestos avaliativos e punitivos",
                           "Prática de arbitragem no dojo"],
            "terminologia": ["Revisar a terminologia das promoções anteriores"],
            "nage": ["O-soto-guruma", "Uki-waza", "Yoko-wakare", "Yoko-guruma", "Ushiro-goshi",
                     "Ura-nage", "Sumi-otoshi", "Yoko-gake"],
            "katame": ["Koshi-jime", "Sode-guruma-jime", "Sankaku-jime", "Jigoku-jime",
                       "Ryo-te-jime", "Hara-gatame", "Waki-gatame"],
            "kaeshi": [
                {"a": "O-uchi-gari", "b": "Uki-waza"},
                {"a": "Seoi-nage", "b": "Yoko-guruma"},
                {"a": "Koshi-guruma", "b": "Ushiro-goshi"},
                {"a": "Koshi-guruma", "b": "Yoko-guruma"},
                {"a": "Tai-otoshi", "b": "Yoko-guruma"},
                {"a": "Hane-goshi", "b": "Ushiro-goshi"},
                {"a": "Soto-makikomi", "b": "Okuri-eri-jime"},
                {"a": "Koshi-guruma", "b": "Tani-otoshi"},
                {"a": "Koshi-guruma", "b": "Utsuri-goshi"},
                {"a": "Ippon-seoi-nage", "b": "Okuri-eri-jime"},
                {"a": "Sasae-tsuri-komi-ashi", "b": "Kuchiki-taoshi"},
            ],
            "renraku": [
                {"a": "Ippon-seoi-nage", "b": "Ko-uchi-gake"},
                {"a": "Ippon-seoi-nage", "b": "Uchi-makikomi"},
                {"a": "Ippon-seoi-nage", "b": "Sukui-nage"},
                {"a": "Ko-uchi-gari", "b": "Kibisu-gaeshi"},
                {"a": "Ko-uchi-gari", "b": "Kuchiki-taoshi"},
                {"a": "Harai-goshi", "b": "Harai-makikomi"},
                {"a": "O-soto-gari", "b": "O-soto-otoshi"},
                {"a": "O-soto-gari", "b": "O-soto-guruma"},
                {"a": "Koshi-guruma", "b": "Soto-makikomi"},
                {"a": "Kata-guruma", "b": "Kibisu-gaeshi"},
            ],
        },
    },
]


# Termo -> significado, para o modo estudo mostrar a resposta ao lado do termo.
# Mesmo glossário do kyu.js do CFPGs.
GLOSSARIO = {
    "Hajime": "começar — início do combate",
    "Mate": "espere / pare",
    "Sensei": "professor / mestre",
    "Sore-made": "fim de luta / acabou",
    "Shihan": "título de grande mestre (usado só para Jigoro Kano)",
    "Ukemi": "técnica de amortecer a queda",
    "Shintai": "movimentação / deslocamento",
    "Uchikomi": "repetição do encaixe da técnica, sem projetar",
    "Judô": "“caminho suave” (Ju = suavidade, Do = caminho)",
    "Dojo": "local de treino",
    "Osae-komi": "imobilização válida",
    "Toketa": "imobilização desfeita",
    "Tokui-waza": "técnica preferida (favorita)",
    "Judogui": "uniforme (kimono) do judô",
    "Zubon": "calça do judogui",
    "Wagui": "paletó/jaqueta do judogui",
    "Obi": "faixa",
    "Migi": "direita",
    "Hidari": "esquerda",
    "Hantai": "contrário / lado oposto",
    "Yoko": "lado / lateral",
    "Shiai": "competição / combate",
    "Shiai-jo": "área de competição",
    "Waza-ari": "quase-ippon; dois waza-ari somam ippon",
    "Ippon": "ponto máximo — encerra a luta",
    "Waza-ari-awasete-ippon": "soma de dois waza-ari = ippon",
    "Sonomama": "“não se mexam” (mantenham a posição)",
    "Yoshi": "“continuem” (retoma após sonomama)",
    "Shido": "penalidade / advertência",
    "Hansoku-make": "desclassificação",
    "Tori": "quem aplica a técnica",
    "Uke": "quem recebe a técnica",
    "Tai-sabaki": "esquiva / giro do corpo",
    "Kuzushi": "quebra do equilíbrio",
    "Tsukuri": "preparação / encaixe",
    "Kake": "execução / aplicação da técnica",
    "Jigotai": "postura defensiva",
    "Shizen-hontai": "postura natural",
    "Go-kyo": "as cinco séries de projeções do Kodokan",
    "Kyu": "graduação abaixo da faixa preta",
    "Hantei": "decisão dos árbitros",
    "Hikiwake": "empate",
    "Fusen-gachi": "vitória por ausência do adversário",
    "Kiken-gachi": "vitória por desistência/abandono do adversário",
    "Yusei-gachi": "vitória por superioridade (decisão)",
    "Maitta": "“eu desisto”",
    "Kodansha": "faixa-preta de grau alto (a partir do 6º dan)",
    "Yudansha": "portador de faixa preta (dan)",
    "Dan": "graduação da faixa preta",
    "Za-rei": "saudação ajoelhada",
    "Ritsu-rei": "saudação em pé",
    "Zempo-kaiten-ukemi": "rolamento amortecido para a frente",
    "Mae-ukemi": "queda para a frente",
    "Yoko-ukemi": "queda lateral",
    "Ushiro-ukemi": "queda para trás",
}
