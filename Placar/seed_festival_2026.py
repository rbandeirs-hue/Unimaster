#!/usr/bin/env python
# seed_festival_2026.py — Importa dados do Festival Judô ArteFísica 2026 (lista do PDF)
import os
import re
import sys

from datetime import date

from app.models.base import db
from app.models.competicao import Competicao
from app.models.academia import Academia
from app.models.atleta import Atleta
from app.models.categoria import Categoria
from app.models.inscricao import Inscricao

COMPETICAO_NOME = "Festival Judô ArteFísica - Circuito ArteFísica de Judô 2026"
COMPETICAO_DATA = date(2026, 4, 10)
COMPETICAO_LOCAL = "Recife - PE"


def _idade_min_sub_do_nome(nome_categoria):
    m = re.search(r"SUB\s*(\d+)", nome_categoria or "", re.I)
    if not m:
        return None
    return max(0, int(m.group(1)) - 2)

# ── normalização de academia ──────────────────────────────────────────────────
_ACAD = {
    'mesquita': 'Mesquita', 'kaizen': 'Kaizen', 'sede': 'Sede',
    'blue school': 'Blue School', 'ccr': 'CCR',
    'colégio triunfo': 'Colégio Triunfo', 'colegio triunfo': 'Colégio Triunfo',
    'jadson judô': 'Jadson Judô', 'jadson judo': 'Jadson Judô',
    'saber viver': 'Saber Viver', 'rise': 'RISE',
    'rise madalena': 'Rise Madalena', 'rise casa forte': 'Rise Casa Forte',
    'completude': 'Completude', 'amma': 'Amma', 'il': 'IL', 'eea': 'EEA',
    'vila bambino': 'Vila Bambino', 'talentinho': 'Talentinho',
    'talen': 'Talentinho', 'taletinho': 'Talentinho',
    'acpl': 'ACPL', 'decisão': 'Decisão', 'decisao': 'Decisão',
    'fps': 'FPS', 'fps projeto': 'FPS', 'anglo': 'Anglo', 'cas': 'CAS',
    'itapissuma': 'Itapissuma', 'caf': 'CAF', 'hoyo': 'Hoyo',
    'jdi': 'JDI', 'unibaby': 'Unibaby', 'anita': 'Anita',
    'eab': 'EAB', 'ctmp': 'CTMP', 'esm': 'ESM', 'mcmg': 'MCMG',
    'waza': 'Waza Escola Luta', 'waza escola luta': 'Waza Escola Luta',
    'escola luta': 'Waza Escola Luta', 'rox': 'Rox',
    'arcos aurora': 'Arcos Aurora', 'dourado': 'Dourado', 'es': 'ES',
}

def norm_acad(raw):
    return _ACAD.get(raw.strip().lower(), raw.strip())

def parse_date(s):
    d, m, y = s.split('/')
    return date(int(y), int(m), int(d))

# ── áreas: (nome_cat, sexo, peso_min, peso_max, idade_max, atletas) ───────────
# atletas: (nome, sexo, dob_str, peso_float, faixa, academia_raw)

AREAS = [

    # ── SUB 5 ─────────────────────────────────────────────────────────────────
    {
        'nome': 'SUB 5 F Área 1', 'sexo': 'F',
        'peso_min': 9.0, 'peso_max': 18.0, 'idade_max': 5,
        'atletas': [
            ('Maria Clara Cardoso de Souza e Silva', 'F', '10/08/2022', 17.0,   '12 Kiu',    'Colégio Triunfo'),
            ('Marinna Campelo Santos',               'F', '04/06/2023', 13.0,   '12 Kiu',    'Kaizen'),
            ('Dandara da Cunha Moura',               'F', '10/03/2023', 15.0,   '12 Kiu',    'Hoyo'),
            ('Valentina Manioba Ayres Torres',       'F', '05/04/2023', 14.0,   'Branca',    'Blue School'),
            ('Beatriz Koon',                         'F', '06/08/2023',  9.5,   '12 Kiu',    'EEA'),
        ],
    },
    {
        'nome': 'SUB 5 M Área 1', 'sexo': 'M',
        'peso_min': 11.0, 'peso_max': 15.0, 'idade_max': 5,
        'atletas': [
            ('Nicolas Joaquim da Silva Medeiros',            'M', '08/10/2022', 12.0,  '12 Kiu', 'Vila Bambino'),
            ('Jose Miguel de Azevedo Alencar Barros',        'M', '01/02/2022', 14.0,  '12 Kiu', 'FPS'),
            ('João Francisco Ferreira dos Santos Figueira',  'M', '24/08/2023', 14.5,  '12 Kiu', 'JDI'),
        ],
    },
    {
        'nome': 'SUB 5 M Área 2', 'sexo': 'M',
        'peso_min': 15.0, 'peso_max': 25.0, 'idade_max': 5,
        'atletas': [
            # Théo Lima dos Santos (born 2021) → SUB 7 Á4, NOT here
            ('Miguel Vitor Santos de Andrade',          'M', '07/12/2022', 15.0,  '12 Kiu',  'Amma'),
            ('Lucas Andrade de Castro',                  'M', '28/03/2022', 15.0,  '11 Kiu',  'Vila Bambino'),
            ('Caíque Souza Guedes de Oliveira',          'M', '26/04/2022', 15.7,  '11 Kiu',  'EEA'),
            ('João Miguel Coelho Saboia de Sousa',       'M', '06/12/2022', 16.0,  '12 Kiu',  'Vila Bambino'),
            ('Leonardo Cordeiro Lemos de Oliveira',      'M', '11/11/2022', 16.0,  'Branca',  'Sede'),
            ('Davi Bazante Souza',                       'M', '12/02/2022', 16.0,  'Branca',  'Blue School'),
            ('José Pedro de Oliveira Mascarenhas',       'M', '15/06/2022', 18.4,  '12 Kiu',  'RISE'),
            ('João Paulo Leite de Freitas Filho',        'M', '16/06/2022', 19.5,  '12 Kiu',  'JDI'),
            ('Pedro Antônio Barbosa Dias',               'M', '14/05/2022', 24.0,  '12 Kiu',  'Talentinho'),  # Casar Luta
        ],
    },

    # ── SUB 7 ─────────────────────────────────────────────────────────────────
    {
        'nome': 'SUB 7 F Área 3', 'sexo': 'F',
        'peso_min': 12.0, 'peso_max': 27.0, 'idade_max': 7,
        'atletas': [
            ('Elis Almeida de Santana',                 'F', '09/01/2020', 21.0,  '11 Kiu',  'Talentinho'),
            ('Laura Beatriz Correia Nunes',             'F', '12/03/2020', 20.0,  '11 Kiu',  'ACPL'),
            ('Heloísa Maria do Nascimento Carneiro',    'F', '24/03/2020', 21.6,  '10 Kiu',  'Sede'),
            ('Clara Souza de Lira Borba',               'F', '16/09/2020', 20.0,  '11 Kiu',  'Blue School'),
            ('Cecília Gomes Gouveia',                   'F', '09/10/2020', 15.0,  '12 Kiu',  'Blue School'),  # born 2020 → SUB 7
            ('Lily Cavalcanti Alves',                   'F', '13/04/2020', 15.0,  '10 Kiu',  'IL'),
            ('Laura Farias Diritch',                    'F', '15/03/2021', 13.0,  '12 Kiu',  'Talentinho'),
            ('Laura Souza de Oliveira',                 'F', '15/01/2020', 15.0,  '10 Kiu',  'Sede'),
            ('Iris Gallindo Dantas Frensch',            'F', '09/02/2021', 16.0,  '12 Kiu',  'Saber Viver'),
            ('Maria Clara da Silva Valença',            'F', '18/12/2021', 15.0,  '12 Kiu',  'Blue School'),
            ('Beatriz Aragão Costa',                    'F', '23/03/2021', 15.0,  '12 Kiu',  'Blue School'),  # born 2021 → SUB 7
            ('Kayllane Eloa Neves dos Santos',          'F', '08/07/2021', 17.0,  '12 Kiu',  'ACPL'),
            ('Maria Valentina Santos do Nascimento',    'F', '20/09/2021', 22.5,  '12 Kiu',  'Colégio Triunfo'),  # Atenção na Luta
            ('Tiara Maria Luísa Bomfim Regis',          'F', '21/01/2021', 26.0,  '12 Kiu',  'Sede'),
        ],
    },
    {
        'nome': 'SUB 7 M Área 4', 'sexo': 'M',
        'peso_min': 13.0, 'peso_max': 17.5, 'idade_max': 7,
        'atletas': [
            ('Théo Lima dos Santos',                        'M', '12/10/2021', 15.0,  'Branca',  'Blue School'),  # born 2021 → SUB 7
            ('Arthur Samuel Barros Medeiros',               'M', '02/08/2021', 14.0,  '11 Kiu',  'Colégio Triunfo'),
            ('Ravi Renart de Souza Lima Pereira da Silva',  'M', '12/08/2021', 14.0,  '12 Kiu',  'Blue School'),
            ('Benício de Castro Almeida',                   'M', '03/10/2021', 14.0,  '11 Kiu',  'Vila Bambino'),
            ('Ravi Estanislau Lira Santana',                'M', '16/12/2021', 14.5,  '12 Kiu',  'Vila Bambino'),
            ('João Lucas Mesquita',                         'M', '21/12/2021', 15.0,  '12 Kiu',  'Mesquita'),
            ('Lucas Gabriel Santos de Almeida',             'M', '14/05/2021', 16.0,  '12 Kiu',  'Unibaby'),
            ('João Rosendo',                                'M', '26/05/2019', 15.0,  '10 Kiu',  'Mesquita'),
            ('Davi Lucena Monteiro',                        'M', '18/09/2020', 15.0,  '11 Kiu',  'Talentinho'),
            ('Alves Miguel Cavalcanti Tenório',             'M', '04/11/2020', 15.0,  '11 Kiu',  'Saber Viver'),
            ('Clara Dias Marinho',                          'M', '25/09/2020', 16.0,  '12 Kiu',  'Mesquita'),
            ('Rafael Muniz Ribeiro',                        'M', '04/11/2021', 16.0,  '11 Kiu',  'Vila Bambino'),
            ('Théo Fagundes de Sansores França',            'M', '12/11/2021', 16.5,  '12 Kiu',  'Vila Bambino'),
            ('Otto Siqueira Pimentel',                      'M', '23/02/2021', 17.0,  '11 Kiu',  'Rise Madalena'),
            # Lucas Feitosa e Joaquim Ferreira → Área 5
        ],
    },
    {
        'nome': 'SUB 7 M Área 5', 'sexo': 'M',
        'peso_min': 16.0, 'peso_max': 23.0, 'idade_max': 7,
        'atletas': [
            ('Tiago Esposito Couceiro Melo Filho',      'M', '18/04/2020', 16.0,  '10 Kiu',  'Hoyo'),
            ('Lucas Feitosa Gonçalves de Carvalho',     'M', '01/08/2021', 17.0,  '11 Kiu',  'Arcos Aurora'),
            ('Joaquim Ferreira de Abreu Pinto',         'M', '17/12/2021', 17.0,  '12 Kiu',  'Vila Bambino'),
            ('Davi Accioly dos Reis',                   'M', '22/04/2021', 18.9,  '11 Kiu',  'EEA'),
            ('Guilherme Marinheiro Santiago',           'M', '15/12/2021', 19.0,  '12 Kiu',  'Mesquita'),
            ('Henrique Santos Leal',                    'M', '13/10/2021', 18.0,  '12 Kiu',  'Blue School'),
            ('Edrremulos Sales dos Santos Filho',       'M', '19/03/2021', 19.0,  '10 Kiu',  'Blue School'),
            ('Lorenzo Holanda',                         'M', '07/05/2021', 20.0,  '12 Kiu',  'CCR'),
            ('Anthony de Brito Dias',                   'M', '21/06/2021', 20.0,  '12 Kiu',  'Anglo'),
            ('Mateus Siqueira Silvestre',               'M', '14/02/2021', 21.0,  '12 Kiu',  'Rise Madalena'),
            ('Bento Avelar Ribeiro Gonçalves',          'M', '27/07/2021', 22.0,  '12 Kiu',  'Blue School'),
            ('Heitor Luiz da Silva Campos',             'M', '28/06/2021', 19.0,  '11 Kiu',  'Unibaby'),
            ('Arthur Geovane Coutinho Costa',           'M', '30/07/2020', 18.0,  '11 Kiu',  'Anita'),
            ('João Bernardo Fonseca do Nascimento',     'M', '12/09/2020', 18.0,  '11 Kiu',  'Anita'),
            ('Lucas de Valois Guimarães',               'M', '12/05/2020', 19.0,  '10 Kiu',  'Mesquita'),
            ('Kayo Richard',                            'M', '13/04/2020', 20.0,  '11 Kiu',  'Mesquita'),
        ],
    },
    {
        'nome': 'SUB 7 M Área 6', 'sexo': 'M',
        'peso_min': 20.0, 'peso_max': 22.0, 'idade_max': 7,
        'atletas': [
            ('Noah Lucas',                          'M', '30/05/2020', 20.0,  '11 Kiu',  'Blue School'),
            ('Rui Freire Peixoto Ribeiro de Souza', 'M', '10/10/2020', 20.0,  '11 Kiu',  'Sede'),
            ('Matheus Augusto Ferreira',            'M', '09/12/2020', 20.0,  '10 Kiu',  'Mesquita'),
            ('Pedro Henrique Cavalcanti Vilar',     'M', '18/12/2020', 20.0,  '11 Kiu',  'Saber Viver'),
            ('Bruno Victor da Silva Cruz',          'M', '22/05/2020', 20.0,  '12 Kiu',  'ACPL'),
            ('Edinaldo Tenório Lopes',              'M', '19/01/2020', 20.9,  '12 Kiu',  'Itapissuma'),
            ('Samuel Uchôa',                        'M', '19/07/2021', 20.0,  '10 Kiu',  'JDI'),
            ('João Gonçalves Bivar',                'M', '15/07/2020', 20.0,  '11 Kiu',  'JDI'),
            ('Pedro Rios',                          'M', '31/12/2020', 21.0,  '11 Kiu',  'Mesquita'),
            ('Rafael Bernardo Brito de Paiva',      'M', '02/03/2020', 21.0,  '12 Kiu',  'IL'),
            ('Henrique Francisco Sobral de Lima',   'M', '23/07/2020', 21.0,  '12 Kiu',  'Talentinho'),
            ('Eduardo Ventura',                     'M', '05/09/2020', 21.0,  '11 Kiu',  'Saber Viver'),
            ('Bernardo Cavalcante Veras',           'M', '16/09/2020', 21.0,  '11 Kiu',  'Mesquita'),
        ],
    },
    {
        'nome': 'SUB 7 M Área 7', 'sexo': 'M',
        'peso_min': 21.5, 'peso_max': 27.0, 'idade_max': 7,
        'atletas': [
            ('Gael Valongo de Arruda',                      'M', '17/06/2020', 22.5,  '9 Kiu',   'Blue School'),
            ('Gabriel Farias Maia e Silva',                 'M', '04/06/2020', 23.0,  '10 Kiu',  'Saber Viver'),
            ('Francisco Teixeira Gomes Aires Lins',         'M', '19/07/2020', 23.0,  '12 Kiu',  'Sede'),
            ('Benício Ariel Campos Lira',                   'M', '23/09/2020', 22.0,  '12 Kiu',  'Itapissuma'),
            ('João Miguel Martins de Barros',               'M', '27/11/2020', 22.0,  '9 Kiu',   'Saber Viver'),
            ('João Arthur Félix da Silva',                  'M', '10/12/2020', 22.0,  '11 Kiu',  'Kaizen'),
            ('Hermano Sol Silva Ramos',                     'M', '21/03/2021', 22.5,  '12 Kiu',  'Unibaby'),
            ('Lucas de Azevedo Campos',                     'M', '31/12/2026', 26.0,  '9 Kiu',   'Mesquita'),  # DOB erro, incluído as-is
            ('Romeu Medeiros de Oliveira Gibson',           'M', '27/07/2020', 24.8,  '11 Kiu',  'ESM'),
            ('Gustavo de Melo Siqueira',                    'M', '04/02/2020', 25.0,  '11 Kiu',  'Rise Madalena'),
            ('Vinicius Luna Andrade',                       'M', '06/02/2020', 25.0,  '9 Kiu',   'Mesquita'),
            ('Miguel Magalhães Macedo Mariano Caminha',     'M', '19/01/2020', 26.0,  '10 Kiu',  'Rise Madalena'),
        ],
    },
    {
        'nome': 'SUB 7 M Área 8', 'sexo': 'M',
        'peso_min': 29.0, 'peso_max': 36.0, 'idade_max': 7,
        'atletas': [
            ('Kleyton Vicente de Lima Filho',   'M', '22/10/2018', 30.0,  '12 Kiu',  'Sede'),
            ('Thomaz Costa Ferreira Xavier',    'M', '05/06/2020', 30.0,  '10 Kiu',  'CAS'),
            ('Ramiro Duarte Souza Dantas',      'M', '22/06/2020', 30.0,  '12 Kiu',  'Blue School'),
            ('João Pedro Barbosa Manoel',       'M', '24/01/2020', 30.9,  '11 Kiu',  'CTMP'),
            ('Rodrigo Damasceno Silva Araújo',  'M', '24/03/2020', 35.0,  '12 Kiu',  'Mesquita'),  # Casar Luta
        ],
    },

    # ── SUB 9 ─────────────────────────────────────────────────────────────────
    {
        'nome': 'SUB 9 F Área 1', 'sexo': 'F',
        'peso_min': 18.0, 'peso_max': 27.0, 'idade_max': 9,
        'atletas': [
            ('Giovanna Luiza Ferreira',             'F', '26/03/2019', 19.0,  '8 Kiu',   'Mesquita'),
            ('Luísa Guedes de Araújo',              'F', '14/09/2019', 20.0,  '12 Kiu',  'Sede'),
            ('Evelyn Pereira dos Santos Cavalcante','F', '21/11/2019', 20.0,  '12 Kiu',  'Amma'),
            ('Nina Arns de Sá',                     'F', '02/12/2019', 20.0,  '9 Kiu',   'Sede'),
            ('Aurora Gallindo Dantas Frensch',      'F', '20/06/2018', 21.0,  '12 Kiu',  'Saber Viver'),
            ('Joyce Valentina de Souza Barbosa',    'F', '23/09/2019', 21.0,  '11 Kiu',  'Itapissuma'),
            ('Maria Lavínia Sales Paes Barreto',    'F', '07/08/2019', 21.5,  '9 Kiu',   'Amma'),
            ('Malu Miranda Ferreira',               'F', '14/08/2018', 22.0,  '8 Kiu',   'RISE'),
            ('Maria Júlia Cordeiro Paes Barreto',   'F', '22/04/2019', 23.0,  '8 Kiu',   'Arcos Aurora'),
            ('Maria Luísa Gomes de Brito',          'F', '13/11/2019', 26.0,  '9 Kiu',   'Rise Casa Forte'),  # Á1 only
        ],
    },
    {
        'nome': 'SUB 9 F Área 2', 'sexo': 'F',
        'peso_min': 24.0, 'peso_max': 35.0, 'idade_max': 9,
        'atletas': [
            ('Joana Maria Dias Lima',                   'F', '17/09/2018', 24.0,  '10 Kiu',  'Talentinho'),
            ('Maria Luiza Barros de Lima',              'F', '26/11/2018', 25.0,  '11 Kiu',  'Saber Viver'),
            ('Melissa Luna Gomes',                      'F', '28/11/2018', 25.0,  '9 Kiu',   'Sede'),
            ('Ana Júlia Sotero Sena',                   'F', '12/06/2019', 25.0,  '10 Kiu',  'Talentinho'),
            ('Heloísa Alves Costa',                     'F', '31/08/2019', 25.0,  '12 Kiu',  'ACPL'),
            ('Manuela Henrique Lacerda Borba',          'F', '17/01/2019', 26.0,  '9 Kiu',   'Sede'),
            ('Adélia Fernandes de Melo',                'F', '09/02/2018', 26.6,  '9 Kiu',   'RISE'),
            ('Maria Luísa de Morais',                   'F', '17/10/2019', 28.0,  '9 Kiu',   'Sede'),
            # Maria Luísa Gomes de Brito → Á1 apenas
            ('Maria Clara Paula Rodrigues da Silva',    'F', '21/10/2019', 30.7,  '11 Kiu',  'CAS'),
            ('Luísa Abramof Barros Leite',              'F', '25/01/2019', 32.0,  '10 Kiu',  'Blue School'),
            ('Júlia Gabriele de Paula Paiva',           'F', '29/04/2019', 34.0,  '12 Kiu',  'ACPL'),
        ],
    },
    {
        'nome': 'SUB 9 M Área 3', 'sexo': 'M',
        'peso_min': 15.0, 'peso_max': 24.0, 'idade_max': 9,
        'atletas': [
            ('Felipe Souto Maior de Magalhães Carneiro Leão', 'M', '23/11/2019', 16.0, '11 Kiu', 'Saber Viver'),  # Casar Luta
            ('Bernardo de Souza Morais',              'F', '17/05/2019', 20.0,  '11 Kiu',  'Saber Viver'),  # sexo F conforme PDF
            ('Victor Heitor da Silva Carvalho',       'M', '31/07/2019', 20.0,  '11 Kiu',  'Itapissuma'),
            ('Joaquim Rodrigues Barboza',             'M', '11/09/2019', 20.0,  '11 Kiu',  'Rise Madalena'),
            ('Dante Ribas Sagatio',                   'M', '07/11/2019', 20.0,  '9 Kiu',   'Sede'),
            ('Caio Leal Dias de Araujo',              'M', '16/04/2019', 21.0,  '9 Kiu',   'Rise Madalena'),
            ('Arthur Ferreira Graça',                 'M', '05/08/2019', 21.0,  '10 Kiu',  'Mesquita'),
            ('Tomás Figueiredo Lima',                 'M', '01/12/2019', 21.0,  '10 Kiu',  'Mesquita'),
            ('Miguel da Silva Vasconcelos',           'M', '19/02/2019', 22.0,  '10 Kiu',  'Blue School'),
            ('Nicolas Bernardo de Melo Andrade',      'M', '23/11/2019', 22.0,  '10 Kiu',  'Rise Madalena'),
            ('Joaquim Adylles Fonceca de Lima',       'M', '14/02/2019', 23.0,  '9 Kiu',   'Blue School'),
            ('Aian Ricardo',                          'M', '10/06/2019', 23.0,  '9 Kiu',   'Completude'),
            ('Vicente Lima Tiede',                    'M', '05/11/2019', 23.0,  '10 Kiu',  'Anita'),
        ],
    },
    {
        'nome': 'SUB 9 M Área 4', 'sexo': 'M',
        'peso_min': 23.0, 'peso_max': 31.0, 'idade_max': 9,
        'atletas': [
            ('Francisco Machado Leitão',            'M', '01/10/2019', 23.5,  '11 Kiu',  'FPS'),
            ('Lucas Yusuke Fujiwara',               'M', '10/11/2019', 24.0,  '12 Kiu',  'Talentinho'),
            ('Diego Passos Melo',                   'M', '07/02/2019', 25.0,  '12 Kiu',  'Talentinho'),
            ('Samuel Bezerra Bandeira da Silva',    'M', '03/09/2019', 25.0,  '8 Kiu',   'ACPL'),
            ('Manoel Valdemar Carneiro Larré',      'M', '01/10/2019', 25.0,  '11 Kiu',  'Rise Madalena'),
            ('Felipe Neves da Silva',               'M', '28/05/2019', 26.0,  '12 Kiu',  'ACPL'),
            ('Heitor Firmo',                        'M', '26/04/2019', 28.0,  '10 Kiu',  'Mesquita'),
            ('Vinícius Alves de Carvalho Monteiro', 'M', '19/08/2019', 29.0,  '12 Kiu',  'Talentinho'),
            ('José Augusto Alcantara de Lima',      'M', '02/02/2019', 30.0,  '9 Kiu',   'Waza Escola Luta'),
        ],
    },
    {
        'nome': 'SUB 9 M Área 5', 'sexo': 'M',
        'peso_min': 20.5, 'peso_max': 23.5, 'idade_max': 9,
        'atletas': [
            ('Rafael Siqueira Couto',               'M', '31/07/2018', 21.0,  '8 Kiu',   'Dourado'),
            ('Davi Gonçalves Lima',                 'M', '05/08/2018', 21.0,  '8 Kiu',   'Mesquita'),
            ('Gabriel Viriato de Medeiros Vieira',  'M', '17/08/2018', 21.0,  '8 Kiu',   'Waza Escola Luta'),
            ('Yuri Alexandrino',                    'M', '06/09/2018', 21.0,  '10 Kiu',  'Completude'),
            ('Miguel Beltrão Brandão dos Santos',   'M', '14/03/2018', 22.0,  '10 Kiu',  'Mesquita'),
            ('Davi Machado Dantas',                 'M', '16/04/2018', 22.0,  '7 Kiu',   'IL'),
            ('Lucas Souza Nascimento',              'M', '04/12/2018', 22.0,  '8 Kiu',   'Mesquita'),
            ('Mateus Araujo Tavares Fernandes',     'M', '12/12/2018', 22.0,  '9 Kiu',   'Mesquita'),
            ('Henrique Castro Veras Tenório Uchôa', 'M', '28/12/2018', 22.0,  '12 Kiu',  'FPS'),
            ('Henrique Campos Nóbrega',             'M', '24/12/2018', 23.0,  '11 Kiu',  'Rise Madalena'),
        ],
    },
    {
        'nome': 'SUB 9 M Área 6', 'sexo': 'M',
        'peso_min': 23.5, 'peso_max': 28.0, 'idade_max': 9,
        'atletas': [
            ('Miguel Antônio Bernardino Lôdo de Araújo', 'M', '20/04/2018', 24.0, '8 Kiu',  'Arcos Aurora'),
            ('Bernardo Santos Arteiro',              'M', '04/09/2018', 24.0,  '8 Kiu',   'Mesquita'),
            ('João Augusto Silva Ferreira',          'M', '26/09/2018', 24.0,  '11 Kiu',  'Sede'),
            ('Maurício Rogério da Encarnação Filho', 'M', '05/09/2018', 25.0,  '12 Kiu',  'Itapissuma'),
            ('Rodrigo Ramos de Souza Santos',        'M', '18/10/2018', 25.0,  '12 Kiu',  'Talentinho'),
            ('Gabriel Akira Kuroki Rodrigues',       'M', '16/07/2018', 25.5,  '9 Kiu',   'Blue School'),
            ('Henry Phelipe Pacheco de Souza',       'M', '30/10/2018', 24.0,  '7 Kiu',   'Sede'),
            ('Davi Cavalcanti Veras',                'M', '10/09/2018', 26.0,  '8 Kiu',   'Mesquita'),
            ('Lucas Barreto Campello Silva',         'M', '10/12/2018', 26.0,  '10 Kiu',  'Blue School'),
            ('Edacyr Neto',                          'M', '11/12/2018', 26.0,  '8 Kiu',   'Completude'),
            ('Nathan Guimarães Souza',               'M', '21/05/2018', 27.0,  '12 Kiu',  'Itapissuma'),
            ('Issac da S. Vidal Neves',              'M', '11/09/2018', 27.0,  '10 Kiu',  'Sede'),
            ('Nicolas Eduardo Barbosa da Silva',     'M', '30/10/2018', 27.0,  '12 Kiu',  'Hoyo'),
        ],
    },
    {
        'nome': 'SUB 9 M Área 7', 'sexo': 'M',
        'peso_min': 28.0, 'peso_max': 33.0, 'idade_max': 9,
        'atletas': [
            ('Francisco Marques da Silva Neto',     'M', '10/07/2018', 28.0,  '11 Kiu',  'Talentinho'),
            ('Luca Marques',                        'M', '22/11/2018', 28.0,  '8 Kiu',   'Mesquita'),
            ('Antonioni Barbosa da Palma',          'M', '26/02/2018', 29.0,  '9 Kiu',   'Colégio Triunfo'),
            ('Lucas Jalfim Lumba Galindo',          'M', '04/07/2018', 29.0,  '12 Kiu',  'Rise Madalena'),
            ('Amaro Verissimo da Fonseca',          'M', '18/11/2018', 29.0,  '9 Kiu',   'ESM'),
            ('Matheus Andrade Almeida Barros',      'M', '11/02/2019', 32.0,  '10 Kiu',  'Mesquita'),
            ('Bernardo Batista de Araújo Santos',   'M', '14/03/2019', 32.0,  '7 Kiu',   'ACPL'),
            ('Miguel Tercio de Morais',             'M', '06/01/2018', 30.0,  '7 Kiu',   'Sede'),
            ('Arthur Levi do Nascimento Silva',     'M', '27/05/2018', 30.0,  '7 Kiu',   'RISE'),
            ('Edson Cavalcante de Queiroz Neto',    'M', '24/06/2018', 30.0,  '8 Kiu',   'MCMG'),
            ('Miguel Silva de Almeida',             'M', '21/10/2018', 30.0,  '7 Kiu',   'Colégio Triunfo'),
        ],
    },
    {
        'nome': 'SUB 9 M Área 8', 'sexo': 'M',
        'peso_min': 32.0, 'peso_max': 42.0, 'idade_max': 9,
        'atletas': [
            ('Isaac José de Andrade Rodrigues Pereira', 'M', '09/01/2018', 32.0,  '8 Kiu',   'ACPL'),
            ('Lucas de Carvalho Araujo',                'M', '21/03/2018', 32.0,  '8 Kiu',   'Sede'),
            ('Davi Filgueiras',                         'M', '10/04/2018', 32.0,  '7 Kiu',   'Mesquita'),
            ('Lucas Cassimiro de Souza Lucena',         'M', '20/06/2018', 32.0,  '12 Kiu',  'EAB'),
            ('Miguel Montezuma Harrop',                 'M', '28/05/2019', 36.0,  '9 Kiu',   'Mesquita'),
            ('Guilherme Rocha Lima',                    'M', '04/02/2018', 33.9,  '12 Kiu',  'FPS'),
            ('Liam Vega Esteves',                       'M', '30/01/2018', 39.0,  '7 Kiu',   'Mesquita'),
            ('Kevin Pedro Santiago da Silva',           'M', '13/01/2018', 40.0,  '10 Kiu',  'Sede'),
            ('Arthur Cezar Manes Florentino',           'M', '06/01/2019', 41.0,  '9 Kiu',   'Mesquita'),
            ('Victor Hugo Vasconcelos Feitosa',         'M', '23/05/2019', 40.0,  '9 Kiu',   'CAS'),
            ('Bernardo Portela de Souza Melo',          'M', '27/05/2018', 40.0,  '12 Kiu',  'Waza Escola Luta'),
        ],
    },

    # ── SUB 11 ────────────────────────────────────────────────────────────────
    {
        'nome': 'SUB 11 F Área 1', 'sexo': 'F',
        'peso_min': 17.0, 'peso_max': 32.0, 'idade_max': 11,
        'atletas': [
            ('Isabel Ribeiro',                      'F', '24/11/2017', 18.0,  '7 Kiu',      'Mesquita'),
            ('Maria Elena da Nobrega Sales',        'F', '24/03/2017', 21.0,  '8 Kiu',      'Mesquita'),
            ('Amanda Valentina Travassos',          'F', '25/11/2016', 25.0,  '7 Kiu',      'Colégio Triunfo'),
            ('Ana Cecília Soares Gonçalves',        'F', '24/08/2017', 26.0,  'Cinza/Azul', 'Blue School'),
            ('Kaylane Ferreira dos Santos',         'F', '09/11/2016', 27.0,  '12 Kiu',     'Jadson Judô'),
            ('Luna Gallindo Dantas de Oliveira',    'F', '23/04/2016', 27.0,  'Branca',     'Saber Viver'),
            ('Carolina Chuaib Baalbaki',            'F', '06/07/2017', 27.0,  '7 Kiu',      'RISE'),
            ('Ayla Lima de Oliveira Barros',        'F', '29/07/2017', 27.9,  '12 Kiu',     'FPS'),
            ('Beatriz Souza Brito',                 'F', '29/12/2017', 29.0,  'Cinza',      'Sede'),
            ('Sophie Cabral Martins',               'F', '22/05/2017', 30.0,  'Branca',     'Saber Viver'),
            ('Melissa de Azevedo Campos',           'F', '10/05/2017', 31.0,  '9 Kiu',      'Mesquita'),
        ],
    },
    {
        'nome': 'SUB 11 F Área 2', 'sexo': 'F',
        'peso_min': 32.0, 'peso_max': 48.0, 'idade_max': 11,
        'atletas': [
            ('Sofia Rios',                              'F', '01/03/2017', 32.0,  '9 Kiu',   'Mesquita'),
            ('Sara Vitoria Albuquerque Valença',        'F', '07/06/2016', 34.0,  '12 Kiu',  'Decisão'),
            ('Ágatha Albuquerque da Silva',             'F', '04/04/2017', 35.0,  '9 Kiu',   'ACPL'),
            ('Júlia Maaze Loiola',                     'F', '25/12/2017', 36.0,  '12 Kiu',  'Mesquita'),
            ('Maria Izabel Ferreira da Silva',          'F', '12/05/2016', 37.5,  '7 Kiu',   'CAS'),
            ('Maria Cecília Lima de Oliveira',          'F', '10/11/2017', 39.0,  '9 Kiu',   'Colégio Triunfo'),
            ('Maria Luísa Cunha Campelo',               'F', '29/11/2016', 42.0,  '10 Kiu',  'Sede'),
            ('Maria Cecília',                           'F', '24/03/2016', 43.0,  '12 Kiu',  'Completude'),
            ('Jully Gabrielly das Graças Matias dos Santos', 'F', '13/12/2016', 45.0, 'Branca', 'Sede'),
            ('Joyce Vitória Ferreira Silva',            'F', '29/02/2016', 45.0,  '7 Kiu',   'FPS'),
            ('Maria Eduarda Barros de Lima',            'F', '12/06/2017', 47.0,  'Branca',  'Saber Viver'),
        ],
    },
    {
        'nome': 'SUB 11 M Área 3', 'sexo': 'M',
        'peso_min': 18.0, 'peso_max': 30.0, 'idade_max': 11,
        'atletas': [
            ('Lucca Monteiro Tavares',              'M', '06/05/2017', 19.0,  '7 Kiu',      'Anglo'),
            ('Benjamim Alves Farias',               'M', '07/03/2017', 19.0,  '11 Kiu',     'ES'),
            ('Benjamin Peixoto Freitas',            'M', '26/04/2017', 22.0,  '10 Kiu',     'IL'),
            ('Marcos Gabriel da Silva',             'M', '16/05/2016', 22.0,  '10 Kiu',     'Itapissuma'),
            ('Luan Henrique Tenório Lopes',         'M', '01/06/2017', 23.4,  '12 Kiu',     'Itapissuma'),
            ('Reydisson Emanuel Justino da Silva',  'M', '07/03/2017', 25.0,  '8 Kiu',      'Kaizen'),
            ('José Bernardo Viana dos Santos',      'M', '10/02/2016', 25.0,  '8 Kiu',      'Mesquita'),
            ('William Marinho Maia Santiago',       'M', '06/11/2017', 25.0,  '6 Kiu',      'Sede'),
            ('Samuel Porfírio Bernardes',           'M', '20/04/2016', 27.0,  '+de 5 Kiu',  'EAB'),
            ('Miguel Cavalcante Veras',             'M', '28/10/2016', 27.0,  '8 Kiu',      'Mesquita'),
            ('Gabriel de Andrade Gurgel',           'M', '09/08/2017', 27.0,  '10 Kiu',     'Mesquita'),
            ('Daniel Farias de Azevedo Filho',      'M', '06/05/2016', 28.0,  '6 Kiu',      'Mesquita'),
            ('João Guilherme Leônidas de Oliveira', 'M', '04/03/2017', 28.0,  '7 Kiu',      'Kaizen'),
            ('Leonardo Veloso Dubeux',              'M', '19/02/2017', 28.0,  '7 Kiu',      'MCMG'),
            ('Arthur Alves Ribeiro de Andrade Monteiro', 'M', '26/07/2016', 29.0, '7 Kiu',  'CAS'),
        ],
    },
    {
        'nome': 'SUB 11 M Área 4', 'sexo': 'M',
        'peso_min': 30.0, 'peso_max': 35.2, 'idade_max': 11,
        'atletas': [
            ('Arthur Joaquim Ferreira de Santana',          'M', '10/04/2017', 30.0,  '10 Kiu',  'CAS'),
            ('Deivid Lucas de Oliveira Batista',            'M', '07/07/2016', 30.0,  '10 Kiu',  'Amma'),
            ('José Adalberto M Cordeiro Neto',              'M', '06/02/2017', 30.0,  '7 Kiu',   'Arcos Aurora'),
            ('Danilo Henrique Cardoso Vasconcelos',         'M', '15/03/2017', 30.0,  '8 Kiu',   'Sede'),
            ('Isaac Benicio Martins de Santana',            'M', '01/11/2017', 31.2,  '12 Kiu',  'CAS'),
            ('Markus Ribas Sagatio',                        'M', '30/11/2016', 31.2,  '8 Kiu',   'Sede'),
            ('Pedro Miguel Ângelo da Silva',                'M', '03/11/2016', 31.5,  '9 Kiu',   'Colégio Triunfo'),
            ('João Marcelo Cavalcante Muniz dos Santos Carvalho', 'M', '28/10/2016', 31.8, '10 Kiu', 'CAS'),
            ('Matheus Henrique',                            'M', '07/08/2017', 33.0,  '9 Kiu',   'Completude'),
            ('Benjamin Henrique Rocha Gusmão',              'M', '26/05/2017', 33.0,  '10 Kiu',  'FPS'),
            ('Joaquim Galvão de Melo',                      'M', '14/07/2017', 34.0,  '7 Kiu',   'Colégio Triunfo'),
            ('Igor Gabriel dos Santos',                     'M', '12/10/2016', 34.0,  '9 Kiu',   'Itapissuma'),
            ('Enzo Prado de Araujo',                        'M', '04/08/2016', 34.0,  '6 Kiu',   'CAF'),
            ('Caio Arruda',                                 'M', '27/09/2016', 35.0,  '9 Kiu',   'Completude'),
            ('Davi Luan de Castro Maciel',                  'M', '23/09/2017', 35.0,  '12 Kiu',  'Sede'),
        ],
    },
    {
        'nome': 'SUB 11 M Área 5', 'sexo': 'M',
        'peso_min': 35.3, 'peso_max': 70.0, 'idade_max': 11,
        'atletas': [
            ('Nicolas Batista da Silva',                'M', '31/07/2017', 36.7,  '8 Kiu',   'CAS'),
            ('Pedro Lucas Tavares dos Santos',          'M', '03/03/2017', 35.3,  '7 Kiu',   'Colégio Triunfo'),
            ('Guilherme Belchior Silva de Moura',       'M', '11/11/2016', 37.0,  '8 Kiu',   'FPS'),
            ('Willian Gabriel dos Santos Monteiro',     'M', '24/06/2016', 36.1,  '7 Kiu',   'Colégio Triunfo'),
            ('Pedro Sobral Bizarria Silva',             'M', '10/02/2016', 38.0,  '11 Kiu',  'Kaizen'),
            ('Rodrigo Vieira do Amaral',                'M', '25/10/2016', 36.0,  '6 Kiu',   'Colégio Triunfo'),
            ('Pedro Henrique dos Santos Albuquerque',   'M', '17/08/2017', 39.0,  '8 Kiu',   'Talentinho'),
            ('Martim Pessoa Henrique',                  'M', '05/01/2017', 39.8,  '10 Kiu',  'CAS'),
            ('Antonio Alvino',                          'M', '27/12/2016', 40.0,  '9 Kiu',   'Sede'),
            ('Adriano Gomes de Moura Filho',            'M', '09/11/2017', 43.0,  '12 Kiu',  'Sede'),
            ('Bernardo Julio Moura da Silva',           'M', '21/05/2017', 43.9,  '10 Kiu',  'CAS'),
            ('Bernardo Menelau Silva Coelho',           'M', '04/12/2017', 45.0,  '11 Kiu',  'Talentinho'),
            ('Isaac Horácio Santiago',                  'M', '31/07/2014', 51.0,  '6 Kiu',   'Mesquita'),
            ('Emmanoel de Jesus Rodrigues da Silva',    'M', '18/07/2017', 56.0,  '7 Kiu',   'CAS'),
            ('Pedro Henrique Duarte Maia Barbosa',      'M', '12/07/2017', 58.0,  '8 Kiu',   'CAS'),
            ('José Bernardo Alves de Souza',            'M', '14/03/2016', 68.0,  '10 Kiu',  'CCR'),  # Casar Luta
        ],
    },

    # ── SUB 13 ────────────────────────────────────────────────────────────────
    {
        'nome': 'SUB 13 F Área 1', 'sexo': 'F',
        'peso_min': 25.0, 'peso_max': 54.0, 'idade_max': 13,
        'atletas': [
            ('Marina Helena Dias Pereira',          'F', '27/12/2015', 26.0,  '10 Kiu',     'CCR'),
            ('Lara Sofia Gonçalves',                'F', '05/09/2015', 29.0,  '10 Kiu',     'Mesquita'),
            ('Maria Eduarda Cardoso Vasconcelos',   'F', '27/08/2014', 31.0,  '6 Kiu',      'Sede'),
            ('Yasmin Vitória do Nascimento Ferreira','F','19/12/2015', 33.0,  '12 Kiu',     'Sede'),
            ('Elisa Teixeira Gomes Aires Lins',     'F', '03/07/2015', 34.0,  '6 Kiu',      'Sede'),
            ('Isabella Grize Leal',                 'F', '28/07/2015', 42.0,  '12 Kiu',     'CAF'),
            ('Maria Alice Teixeira Pascoal Soares', 'F', '08/06/2015', 44.0,  '8 Kiu',      'Jadson Judô'),
            ('Geovanna Ketlyn de Assis Santos',     'F', '08/08/2014', 44.0,  '+de 5 Kiu',  'Kaizen'),  # SUB 13 apenas
            ('Mariah Carvalho Cavalcante',          'F', '04/12/2014', 44.0,  '12 Kiu',     'Anita'),
            ('Clarice Santos Barreto Sales',        'F', '26/03/2015', 45.0,  '8 Kiu',      'Hoyo'),
            ('Maya Demétrio',                       'F', '24/12/2014', 46.0,  '12 Kiu',     'Completude'),
            ('Julya Sofia Onofre de Azevedo',       'F', '29/04/2014', 48.0,  '8 Kiu',      'Kaizen'),
            ('Amarillys Giovanna Gomes Moraes',     'F', '24/02/2015', 53.0,  '9 Kiu',      'Kaizen'),  # Casar Luta
        ],
    },
    {
        'nome': 'SUB 13 M Área 2', 'sexo': 'M',
        'peso_min': 28.0, 'peso_max': 33.0, 'idade_max': 13,
        'atletas': [
            ('Victor Miguel Orlando de Andrade',        'M', '23/12/2014', 30.0,  '10 Kiu',     'Itapissuma'),
            ('Artur Furtado de Mendonça Dubeux Flores', 'M', '22/09/2015', 31.0,  '+de 5 Kiu',  'Waza Escola Luta'),
            ('Bernardo Figueira Lima da Silva',         'M', '15/09/2015', 29.0,  '8 Kiu',      'CCR'),
            ('Davi Rangel Pombo',                       'M', '07/12/2014', 31.0,  '7 Kiu',      'Mesquita'),
            ('Guilherme Barros Salgado',                'M', '01/09/2015', 32.0,  '+de 5 Kiu',  'Mesquita'),
        ],
    },
    {
        'nome': 'SUB 13 M Área 3', 'sexo': 'M',
        'peso_min': 19.0, 'peso_max': 41.0, 'idade_max': 13,
        'atletas': [
            ('João Miguel Monteiro Aguiar',             'M', '03/02/2015', 20.0,  '10 Kiu',     'RISE'),  # Casar Luta
            ('Miguel dos Anjos Silva Araújo',           'M', '20/10/2014', 34.5,  '10 Kiu',     'ACPL'),
            ('José Reynan da Silva',                    'M', '25/02/2015', 33.0,  '7 Kiu',      'Kaizen'),
            ('Everson Tavares',                         'M', '07/02/2015', 33.0,  '9 Kiu',      'Amma'),
            ('Benjamim Simmons Santos Silva',           'M', '03/12/2015', 35.0,  '12 Kiu',     'Kaizen'),
            ('Guilherme Maaze Loiola',                  'M', '08/09/2014', 35.0,  '10 Kiu',     'Mesquita'),
            ('Arthur Nuno',                             'M', '25/03/2015', 35.0,  'Azul',        'Sede'),
            ('Lucas Souza de Lira Borba',               'M', '21/12/2015', 35.0,  'Azul/Amarela','Blue School'),
            ('Enzo Gabriel dos Santos Silva',           'M', '11/06/2015', 37.0,  '9 Kiu',      'Amma'),
            ('Davi Pereira Maia',                       'M', '29/03/2014', 39.0,  '8 Kiu',      'RISE'),
            ('Bernardo Vinicius Araújo de Souza',       'M', '31/12/2015', 40.0,  '12 Kiu',     'Jadson Judô'),
            ('Lourenzo Raul Soares',                    'M', '01/09/2015', 40.0,  '9 Kiu',      'Talentinho'),
            ('João Arthur Sotero Sena',                 'M', '04/09/2015', 40.0,  '9 Kiu',      'Talentinho'),
            ('Fred Leopoldino Pessôa',                  'M', '09/07/2014', 40.0,  '+de 5 Kiu',  'Waza Escola Luta'),
        ],
    },
    {
        'nome': 'SUB 13 M Área 4', 'sexo': 'M',
        'peso_min': 42.0, 'peso_max': 66.0, 'idade_max': 13,
        'atletas': [
            ('Benjamim Enzo Silva Gomes',           'M', '06/11/2014', 43.0,  '10 Kiu',     'Mesquita'),
            ('Danilo de Oliveira Silva',             'M', '24/11/2014', 44.0,  '6 Kiu',      'Sede'),
            ('Ícaro Miguel Gomes Alves',             'M', '06/10/2015', 44.0,  '9 Kiu',      'Itapissuma'),
            ('Vinicius Belchior Silva de Moura',    'M', '11/11/2014', 45.0,  '8 Kiu',      'FPS'),
            ('Rafael Noberto Ferreira Andrade',     'M', '15/06/2014', 46.0,  '6 Kiu',      'Waza Escola Luta'),
            ('Éverton Bernardo da Silva Lopes',     'M', '16/06/2014', 48.0,  '7 Kiu',      'RISE'),
            ('Matheus Gabriel da Silva',            'M', '05/10/2014', 50.0,  '9 Kiu',      'CTMP'),
            ('André Lucas de Souza Espinhara',      'M', '13/11/2015', 52.0,  '+de 5 Kiu',  'EAB'),
            ('Davi Bezerra Bandeira da Silva',      'M', '22/10/2015', 53.0,  '7 Kiu',      'ACPL'),
            ('Guilherme Federico de Melo Calado',   'M', '14/07/2014', 55.0,  '7 Kiu',      'Decisão'),
            ('Davi Lucas Gomes Vieira de Melo',     'M', '17/09/2015', 56.0,  '9 Kiu',      'Itapissuma'),
            ('João Rodrigo Adelino de Souza',       'M', '11/06/2014', 58.0,  '+de 5 Kiu',  'Colégio Triunfo'),
            ('Guilherme Souza Albuquerque de Araújo','M','13/07/2014', 60.0,  '8 Kiu',      'Hoyo'),
            ('Salomão Rodrigues Ferreira',          'M', '27/05/2015', 65.0,  '12 Kiu',     'Rox'),  # Casar Luta
        ],
    },

    # ── SUB 15 ────────────────────────────────────────────────────────────────
    {
        'nome': 'SUB 15 F Área 2', 'sexo': 'F',
        'peso_min': 35.0, 'peso_max': 93.0, 'idade_max': 15,
        'atletas': [
            ('Ana Beatriz Santos Nascimento',       'F', '27/07/2012', 52.0,  '8 Kiu',      'Kaizen'),
            ('Ana Alice do Nascimento Carneiro',    'F', '01/08/2013', 53.8,  'Azul/Amarela','Sede'),
            ('Emilly Caroline Quitéria da Silva',   'F', '28/09/2012', 55.0,  '9 Kiu',      'CTMP'),
            ('Leticia Alves',                       'F', '09/07/2013', 36.0,  '7 Kiu',      'Completude'),  # Casar Luta
            # Geovanna Ketlyn → SUB 13 F Á1 apenas
            ('Maria Geovana Moraes da Silva',       'F', '16/03/2013', 63.0,  '8 Kiu',      'Kaizen'),  # Casar Luta
            ('Lavénia Lourenço Freire Souza',       'F', '14/11/2013', 92.0,  '8 Kiu',      'Anita'),  # Casar Luta
        ],
    },
    {
        'nome': 'SUB 15 M Área 5', 'sexo': 'M',
        'peso_min': 32.0, 'peso_max': 82.0, 'idade_max': 15,
        'atletas': [
            ('Miguel Atanásio Silva de Lima',           'M', '06/08/2013', 33.0,  '12 Kiu',  'Rox'),
            ('Fernando Atanásio de Lima Neto',          'M', '06/08/2013', 35.0,  '12 Kiu',  'Rox'),
            ('Giuseppe Lisboa Santos Souza Rodrigues',  'M', '12/03/2013', 40.5,  '9 Kiu',   'JDI'),
            ('Samuel Ferreira Nery de Souza',           'M', '21/07/2013', 45.0,  '10 Kiu',  'Itapissuma'),
            ('Arthur Leandro Viana de Lima',            'M', '07/08/2012', 50.0,  '7 Kiu',   'Amma'),
            ('Kaique Guilherme Fernandes',              'M', '27/07/2013', 57.0,  '12 Kiu',  'Jadson Judô'),
            ('David Gabriel Marques de Santana',        'M', '08/07/2013', 81.0,  '9 Kiu',   'Amma'),
        ],
    },
]

# ── importação (use dentro de app.app_context()) ─────────────────────────────
def import_festival_arte_fisica_2026(skip_if_exists=True):
    """
    Cria competição, categorias por área do PDF, atletas e inscrições com categoria_id
    (cada atleta fica só na área listada, mesmo com faixas de peso sobrepostas).
    """
    from sqlalchemy import inspect

    insp = inspect(db.engine)
    if insp.has_table("inscricoes"):
        cols = {c["name"] for c in insp.get_columns("inscricoes")}
        if "categoria_id" not in cols:
            raise RuntimeError(
                "Falta a coluna inscricoes.categoria_id. Execute: flask upgrade-db-inscricoes-categoria"
            )

    if skip_if_exists and Competicao.query.filter_by(nome=COMPETICAO_NOME).first():
        print("Competição já existe. Abortando (skip_if_exists=True).")
        return

    comp = Competicao(
        nome=COMPETICAO_NOME,
        data=COMPETICAO_DATA,
        local=COMPETICAO_LOCAL,
        tipo="FESTIVAL",
    )
    db.session.add(comp)
    db.session.flush()

    acad_cache = {}
    atleta_cache = {}

    def get_acad(raw):
        nome = norm_acad(raw)
        if nome not in acad_cache:
            a = Academia(nome=nome, cidade="Recife")
            db.session.add(a)
            db.session.flush()
            acad_cache[nome] = a
        return acad_cache[nome]

    def get_atleta(nome, sexo, dob_str, peso, faixa, academia_raw):
        key = (nome.strip().lower(), dob_str)
        if key in atleta_cache:
            return atleta_cache[key]
        acad = get_acad(academia_raw)
        a = Atleta(
            nome=nome.strip(),
            sexo=sexo,
            data_nascimento=parse_date(dob_str),
            peso=peso,
            faixa=faixa,
            academia_id=acad.id,
        )
        db.session.add(a)
        db.session.flush()
        atleta_cache[key] = a
        return a

    total_cats = 0
    total_linhas = 0
    total_inscricoes = 0

    for area in AREAS:
        idade_min = _idade_min_sub_do_nome(area["nome"])
        cat = Categoria(
            nome=area["nome"],
            sexo=area["sexo"],
            peso_min=area["peso_min"],
            peso_max=area["peso_max"],
            idade_min=idade_min,
            idade_max=area["idade_max"],
            competicao_id=comp.id,
            ativo=True,
        )
        db.session.add(cat)
        db.session.flush()
        total_cats += 1

        for dados in area["atletas"]:
            nome, sexo, dob_str, peso, faixa, academia_raw = dados
            atleta = get_atleta(nome, sexo, dob_str, peso, faixa, academia_raw)

            insc = Inscricao(
                atleta_id=atleta.id,
                competicao_id=comp.id,
                categoria_id=cat.id,
                status="CONFIRMADO",
            )
            db.session.add(insc)
            total_inscricoes += 1
            total_linhas += 1

    db.session.commit()

    print(f"[OK] Competição criada: {comp.nome} (id={comp.id})")
    print(f"[OK] Academias:  {len(acad_cache)}")
    print(f"[OK] Atletas:    {len(atleta_cache)}")
    print(f"[OK] Categorias: {total_cats}")
    print(f"[OK] Inscrições: {total_inscricoes} (uma por atleta por área)")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
    from app import create_app

    app = create_app()
    with app.app_context():
        import_festival_arte_fisica_2026(skip_if_exists=True)
