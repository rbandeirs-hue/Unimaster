import math
import random
from collections import Counter
from itertools import combinations
from app.models.base import db
from app.models.luta import Luta
from app.models.categoria import Categoria
from app.models.atleta import Atleta
from app.models.inscricao import Inscricao
from app.models.competicao import Competicao
from datetime import date


# ─── helpers ────────────────────────────────────────────────────────────────

def _proxima_potencia_2(n):
    return 2 ** math.ceil(math.log2(n)) if n > 1 else 2


def _fases_por_slots(total_slots):
    """Retorna fases em ordem crescente (round 1 → final)."""
    mapa = {
        2:  ["final"],
        4:  ["semifinal", "final"],
        8:  ["quartas", "semifinal", "final"],
        16: ["oitavas", "quartas", "semifinal", "final"],
    }
    return mapa.get(total_slots, [f"round_{i}" for i in range(1, int(math.log2(total_slots)) + 1)])


def _atleta_encaixa_categoria(atleta, categoria, hoje=None):
    """True se o atleta cumpre sexo, idade e faixa de peso da categoria."""
    if hoje is None:
        hoje = date.today()
    if atleta.sexo != categoria.sexo:
        return False
    if not atleta.data_nascimento:
        return False
    idade = (hoje - atleta.data_nascimento).days // 365
    if categoria.idade_min is not None and idade < categoria.idade_min:
        return False
    if categoria.idade_max is not None and idade > categoria.idade_max:
        return False
    if categoria.peso_min is not None and atleta.peso is not None:
        if float(atleta.peso) < float(categoria.peso_min):
            return False
    if categoria.peso_max is not None and atleta.peso is not None:
        if float(atleta.peso) >= float(categoria.peso_max):
            return False
    return True


def categorias_com_inscritos(competicao_id):
    """
    Categorias da competição com pelo menos um inscrito (PENDENTE ou CONFIRMADO)
    elegível por sexo, idade e peso.

    Se a competição estiver em ``festival_aproximacao``, ignoramos ``inscricao.categoria_id``:
    qualquer inscrito confirmado pode cair em todas as categorias em que encaixa.

    Caso contrário, ``categoria_id`` na inscrição (quando preenchido) restringe àquela categoria.
    """
    comp = Competicao.query.get(competicao_id)
    ign = bool(comp and comp.festival_aproximacao)

    cats = (
        Categoria.query.filter_by(competicao_id=competicao_id).order_by(Categoria.nome).all()
    )
    return [
        cat
        for cat in cats
        if len(
            _atletas_da_categoria(
                cat,
                statuses=("PENDENTE", "CONFIRMADO"),
                ignorar_vinculo_inscricao=ign,
            )
        )
        > 0
    ]


def _atletas_da_categoria(
    categoria, statuses=("CONFIRMADO",), *, ignorar_vinculo_inscricao=None
):
    """
    Atletas inscritos com status em `statuses` que podem lutar nesta categoria.
    Inscrição com categoria_id definido restringe o atleta àquela categoria apenas,
    exceto em competições ``festival_aproximacao`` (matching só por faixa).
    """
    hoje = date.today()

    if ignorar_vinculo_inscricao is None:
        comp = Competicao.query.get(categoria.competicao_id)
        ignorar_vinculo_inscricao = bool(
            comp and getattr(comp, "festival_aproximacao", False)
        )

    pairs = (
        db.session.query(Atleta, Inscricao)
        .join(Inscricao, Inscricao.atleta_id == Atleta.id)
        .filter(
            Inscricao.competicao_id == categoria.competicao_id,
            Inscricao.status.in_(statuses),
            Atleta.sexo == categoria.sexo,
        )
        .all()
    )

    out = []
    seen = set()
    for atleta, insc in pairs:
        if (
            not ignorar_vinculo_inscricao
            and insc.categoria_id is not None
            and insc.categoria_id != categoria.id
        ):
            continue
        if not _atleta_encaixa_categoria(atleta, categoria, hoje):
            continue
        if atleta.id not in seen:
            seen.add(atleta.id)
            out.append(atleta)
    return out


# ─── geração automática de categorias ───────────────────────────────────────

def gerar_categorias(competicao_id):
    """Cria categorias a partir do catálogo oficial (`categorias_catalogo.templates_oficiais`)."""
    from app.utils.categorias_catalogo import templates_oficiais
    from app.models.categoria import Categoria

    Competicao.query.get_or_404(competicao_id)

    existentes = Categoria.query.filter_by(competicao_id=competicao_id).count()
    if existentes:
        raise ValueError("Competição já possui categorias cadastradas.")

    criadas = []
    for tpl in templates_oficiais():
        cat = Categoria(competicao_id=competicao_id, **tpl)
        db.session.add(cat)
        criadas.append(cat)

    db.session.commit()
    return criadas


# ─── chaveamento ─────────────────────────────────────────────────────────────

def _montar_slots_apos_r1(atletas_bye, num_pares_r1):
    """
    Monta a lista de slots da rodada seguinte à primeira (bye real + None por luta de R1).
    Deve ser consistente com o mapeamento em luta_service._preencher_proximo_slot.
    """
    slots = []
    for i in range(num_pares_r1):
        if i < len(atletas_bye):
            slots.append(atletas_bye[i])
        slots.append(None)
    for j in range(num_pares_r1, len(atletas_bye)):
        slots.append(atletas_bye[j])
    return slots


def _modo_terceiro_cbj(n, num_pares_r1, fase_r1):
    """Define disputas de 3º lugar + repescagem (CBJ) para eliminatória n >= 6."""
    if n < 6:
        return None
    if fase_r1 == "oitavas" and num_pares_r1 == 8:
        return "rep_dezesseis"  # 8 oitavas: rep1(4) → rep2(2) → 2 bronzes
    if num_pares_r1 == 4:
        return "rep_oito"  # 4 quartas: rep1(2) perdedores QF → 2 disputas de bronze
    if num_pares_r1 == 2:
        return "dois_lados_seis"  # 2 quartas: rep1 perdedores QF → 2 bronzes vs perdedores SF
    if num_pares_r1 == 3:
        return "sete_com_rep"  # 3 quartas: rep1 + 2 bronzes
    return "unico_legacy"


def gerar_chave(categoria_id, atleta_ids=None):
    """
    Gera as lutas para a categoria (padrão CBJ).
    - 2 atletas   → melhor de 3 (até 2 vitórias; 3ª luta só se 1–1)
    - 3–5 atletas → rodízio (todos contra todos, sem repetir par)
    - 6+ atletas  → eliminatória com repescagem e dois 3ºs (quando aplicável)
    """
    categoria = Categoria.query.get_or_404(categoria_id)

    if Luta.query.filter_by(categoria_id=categoria_id).first():
        raise ValueError("Chave já gerada para esta categoria.")

    if atleta_ids is None:
        atletas = _atletas_da_categoria(categoria)
        atleta_ids = [a.id for a in atletas]

    n = len(atleta_ids)
    if n < 2:
        raise ValueError("Mínimo de 2 atletas para gerar chave.")

    random.shuffle(atleta_ids)

    if n == 2:
        return _gerar_melhor_de_3(categoria_id, atleta_ids[0], atleta_ids[1])

    if 3 <= n <= 5:
        return _gerar_rodizio(categoria_id, atleta_ids)

    total_slots = _proxima_potencia_2(n)
    fases = _fases_por_slots(total_slots)
    byes = total_slots - n

    lutas_criadas = []
    numero = 1

    # ── Round 1 ──────────────────────────────────────────────
    # Atletas com bye avançam direto; os demais lutam no round 1
    atletas_round1 = atleta_ids[byes:]   # lutam
    atletas_bye    = atleta_ids[:byes]   # avançam direto

    fase_r1 = fases[0] if len(fases) > 1 else fases[0]

    pares_r1 = []
    for i in range(0, len(atletas_round1), 2):
        azul   = atletas_round1[i]
        branco = atletas_round1[i + 1]
        luta = Luta(
            categoria_id=categoria_id,
            atleta_azul_id=azul,
            atleta_branco_id=branco,
            fase=fase_r1,
            numero_luta=numero,
        )
        db.session.add(luta)
        lutas_criadas.append(luta)
        pares_r1.append(luta)
        numero += 1

    db.session.flush()  # gera IDs antes de criar rounds seguintes

    modo_terceiro = _modo_terceiro_cbj(n, len(pares_r1), fase_r1)

    # ── Rounds subsequentes ───────────────────────────────────
    # slots_proxima: intercala cada bye com a vaga do vencedor da luta de R1
    # (evita [bye,bye,∅,∅] → dois byes na mesma semifinal)
    slots_proxima = _montar_slots_apos_r1(atletas_bye, len(pares_r1))

    for fase in fases[1:]:
        proxima_slots = []
        for i in range(0, len(slots_proxima), 2):
            s_azul   = slots_proxima[i]
            s_branco = slots_proxima[i + 1] if i + 1 < len(slots_proxima) else None
            luta = Luta(
                categoria_id=categoria_id,
                # pré-preenche se for atleta com bye; None caso contrário
                atleta_azul_id=   s_azul   if isinstance(s_azul,   int) else None,
                atleta_branco_id= s_branco if isinstance(s_branco, int) else None,
                fase=fase,
                numero_luta=numero,
            )
            db.session.add(luta)
            lutas_criadas.append(luta)
            proxima_slots.append(None)  # slot do vencedor desta luta
            numero += 1

        # 3º lugar / repescagem (CBJ), criado após as semifinais
        if fase == "semifinal":
            if modo_terceiro == "rep_dezesseis":
                for _ in range(4):
                    db.session.add(
                        Luta(
                            categoria_id=categoria_id,
                            atleta_azul_id=None,
                            atleta_branco_id=None,
                            fase="repescagem_1",
                            numero_luta=numero,
                        )
                    )
                    numero += 1
                for _ in range(2):
                    db.session.add(
                        Luta(
                            categoria_id=categoria_id,
                            atleta_azul_id=None,
                            atleta_branco_id=None,
                            fase="repescagem_2",
                            numero_luta=numero,
                        )
                    )
                    numero += 1
                for f3 in ("disputa_3lugar_a", "disputa_3lugar_b"):
                    db.session.add(
                        Luta(
                            categoria_id=categoria_id,
                            atleta_azul_id=None,
                            atleta_branco_id=None,
                            fase=f3,
                            numero_luta=numero,
                        )
                    )
                    numero += 1
            elif modo_terceiro == "rep_oito":
                for _ in range(2):
                    db.session.add(
                        Luta(
                            categoria_id=categoria_id,
                            atleta_azul_id=None,
                            atleta_branco_id=None,
                            fase="repescagem_1",
                            numero_luta=numero,
                        )
                    )
                    numero += 1
                for f3 in ("disputa_3lugar_a", "disputa_3lugar_b"):
                    db.session.add(
                        Luta(
                            categoria_id=categoria_id,
                            atleta_azul_id=None,
                            atleta_branco_id=None,
                            fase=f3,
                            numero_luta=numero,
                        )
                    )
                    numero += 1
            elif modo_terceiro == "sete_com_rep":
                db.session.add(
                    Luta(
                        categoria_id=categoria_id,
                        atleta_azul_id=None,
                        atleta_branco_id=None,
                        fase="repescagem_1",
                        numero_luta=numero,
                    )
                )
                numero += 1
                for f3 in ("disputa_3lugar_a", "disputa_3lugar_b"):
                    db.session.add(
                        Luta(
                            categoria_id=categoria_id,
                            atleta_azul_id=None,
                            atleta_branco_id=None,
                            fase=f3,
                            numero_luta=numero,
                        )
                    )
                    numero += 1
            elif modo_terceiro == "dois_lados_seis":
                db.session.add(
                    Luta(
                        categoria_id=categoria_id,
                        atleta_azul_id=None,
                        atleta_branco_id=None,
                        fase="repescagem_1",
                        numero_luta=numero,
                    )
                )
                numero += 1
                for f3 in ("disputa_3lugar_a", "disputa_3lugar_b"):
                    db.session.add(
                        Luta(
                            categoria_id=categoria_id,
                            atleta_azul_id=None,
                            atleta_branco_id=None,
                            fase=f3,
                            numero_luta=numero,
                        )
                    )
                    numero += 1
            else:
                db.session.add(
                    Luta(
                        categoria_id=categoria_id,
                        atleta_azul_id=None,
                        atleta_branco_id=None,
                        fase="disputa_3lugar",
                        numero_luta=numero,
                    )
                )
                numero += 1

        slots_proxima = proxima_slots

    db.session.commit()
    return lutas_criadas


def _gerar_melhor_de_3(categoria_id, atleta_a, atleta_b):
    """
    Melhor de 3: no máximo 3 confrontos; encerra ao chegar a 2 vitórias.
    Só a 1ª luta é criada com atletas; a 2ª é preenchida após a 1ª; a 3ª só se 1–1.
    """
    l1 = Luta(
        categoria_id=categoria_id,
        atleta_azul_id=atleta_a,
        atleta_branco_id=atleta_b,
        fase="final_bo3",
        numero_luta=1,
    )
    l2 = Luta(
        categoria_id=categoria_id,
        atleta_azul_id=None,
        atleta_branco_id=None,
        fase="final_bo3",
        numero_luta=2,
    )
    db.session.add(l1)
    db.session.add(l2)
    db.session.commit()
    return [l1, l2]


# ─── rodízio ────────────────────────────────────────────────────────────────

def _ordenar_pares_rodizio(atleta_ids):
    """
    Ordem das lutas: prioriza não repetir atleta na luta seguinte quando existir
    par disponível; entre pares válidos, favorece quem lutou menos até agora.
    """
    pairs = list(combinations(atleta_ids, 2))
    remaining = pairs.copy()
    ordered = []
    last = frozenset()
    fight_count = Counter()

    while remaining:
        def sort_key(p):
            disj = 0 if (not last or not (set(p) & last)) else 1
            carga = sum(fight_count[x] for x in p)
            return (disj, carga, p)

        chosen = min(remaining, key=sort_key)
        ordered.append(chosen)
        remaining.remove(chosen)
        for x in chosen:
            fight_count[x] += 1
        last = frozenset(chosen)

    return ordered


def _gerar_rodizio(categoria_id, atleta_ids):
    """Gera C(n,2) lutas — todos contra todos, sem repetir par (3 a 5 atletas)."""
    pares = _ordenar_pares_rodizio(atleta_ids)
    lutas_criadas = []
    numero = 1
    for azul_id, branco_id in pares:
        luta = Luta(
            categoria_id=categoria_id,
            atleta_azul_id=azul_id,
            atleta_branco_id=branco_id,
            fase="rodizio",
            numero_luta=numero,
        )
        db.session.add(luta)
        lutas_criadas.append(luta)
        numero += 1
    db.session.commit()
    return lutas_criadas


def resetar_chave(categoria_id):
    """
    Remove todas as lutas e resultados da categoria (categoria e inscrições permanecem).
    Permite gerar a chave novamente.
    """
    Categoria.query.get_or_404(categoria_id)
    lutas = Luta.query.filter_by(categoria_id=categoria_id).all()
    n = len(lutas)
    for luta in lutas:
        if luta.resultado:
            db.session.delete(luta.resultado)
        db.session.delete(luta)
    db.session.commit()
    return n
