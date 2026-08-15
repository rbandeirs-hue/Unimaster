/* =============================================================
   Bracket — Sistema de Judô
   Renderiza chave de eliminação simples com conectores SVG
   ============================================================= */

const POLL_INTERVAL = 10_000; // ms
let _pollingTimer = null;
let _lastData = null;

// mapa lutaId → { azul_id, branco_id } — detecta novos atletas
const _estadoAnterior = {};

// ── Entry point ───────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  carregarBracket();
  _pollingTimer = setInterval(carregarBracket, POLL_INTERVAL);
});

async function carregarBracket() {
  try {
    const resp = await fetch(`/bracket/api/${CATEGORIA_ID}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    _lastData = data;
    renderBracket(data);
    setDotStatus('live');
  } catch (e) {
    console.error('[bracket] Falha ao carregar:', e);
    setDotStatus('off');
  }
}

function setDotStatus(state) {
  const dot = document.getElementById('status-dot');
  dot.className = state === 'live' ? 'dot dot--live' : 'dot';
}

// ── Render ────────────────────────────────────────────────────

function renderBracket(data) {
  document.getElementById('cat-nome').textContent  = data.categoria.nome;
  document.getElementById('comp-nome').textContent = data.categoria.competicao || '';

  const bracketEl = document.getElementById('bracket');
  bracketEl.innerHTML = '';

  const sec = document.getElementById('secao-3lugar');
  sec.innerHTML = '';

  if (!data.rounds || data.rounds.length === 0) {
    bracketEl.innerHTML = '<div class="state-msg">⚔️ Chave ainda não gerada para esta categoria.</div>';
    document.getElementById('secao-colocacoes').innerHTML = '';
    return;
  }

  if (data.tipo === 'rodizio') {
    renderRodizio(data);
    renderColocacoes(data);
    return;
  }

  if (data.tipo === 'melhor3') {
    const ctxBo3 = contextoMelhorDe3(data.rounds[0]?.lutas || []);
    const opts = { lutaDecisivaBo3Id: ctxBo3.lutaDecisivaId };
    data.rounds.forEach(round => bracketEl.appendChild(criarRoundCol(round, opts)));
    requestAnimationFrame(() => requestAnimationFrame(() => desenharConectores(data.rounds)));
    renderColocacoes(data);
    return;
  }

  // ── Eliminação: chave principal + trilha inferior (rep / pódio) ──
  data.rounds.forEach(round => bracketEl.appendChild(criarRoundCol(round)));
  renderRoundsInferiores(data);
  requestAnimationFrame(() => requestAnimationFrame(() => desenharConectores(data.rounds)));
  renderColocacoes(data);
}

/** Série melhor de 3: id da luta em que um atleta fechou 2 vitórias (destaque verde). */
function contextoMelhorDe3(lutas) {
  const sorted = [...lutas].sort((a, b) => (a.numero || 0) - (b.numero || 0));
  const base = sorted.find(l => l.azul?.id && l.branco?.id);
  if (!base) return { lutaDecisivaId: null };
  const a = base.azul.id;
  const b = base.branco.id;
  const w = {};
  for (const l of sorted) {
    if (!l.resultado || !l.vencedor_id) continue;
    const vid = l.vencedor_id;
    if (vid !== a && vid !== b) continue;
    w[vid] = (w[vid] || 0) + 1;
    if (w[vid] >= 2) return { lutaDecisivaId: l.id };
  }
  return { lutaDecisivaId: null };
}

function renderRoundsInferiores(data) {
  const sec = document.getElementById('secao-3lugar');
  const ri = data.rounds_inferiores;
  if (!ri || ri.length === 0) return;

  const wrap = document.createElement('div');
  wrap.className = 'bracket-inferior-wrap';

  const titulo = document.createElement('div');
  titulo.className = 'bracket-inferior-titulo';
  titulo.textContent = 'Repescagem e disputas de pódio';
  wrap.appendChild(titulo);

  const scroll = document.createElement('div');
  scroll.className = 'bracket-inferior-scroll';

  const row = document.createElement('div');
  row.className = 'bracket-inferior-trilha';
  ri.forEach(round => row.appendChild(criarRoundCol(round)));

  scroll.appendChild(row);
  wrap.appendChild(scroll);
  sec.appendChild(wrap);
}

function iconeMedalhaColocacao(lugar) {
  if (lugar === 1) return '🥇';
  if (lugar === 2) return '🥈';
  if (lugar === 3) return '🥉';
  return '🏅';
}

function renderColocacoes(data) {
  const sec = document.getElementById('secao-colocacoes');
  sec.innerHTML = '';
  const items = data.colocacoes;
  if (!items || items.length === 0) return;

  const wrap = document.createElement('div');
  wrap.className = 'colocacoes-wrap';

  const titulo = document.createElement('div');
  titulo.className = 'colocacoes-titulo';
  titulo.innerHTML = '<span class="colocacoes-titulo-ico" aria-hidden="true">🏆</span> Colocações';
  wrap.appendChild(titulo);

  const ul = document.createElement('ul');
  ul.className = 'colocacoes-lista';

  items.forEach(row => {
    const medal = iconeMedalhaColocacao(row.lugar);
    const li = document.createElement('li');
    li.className = `coloc-item coloc-lugar-${row.lugar}`;
    const labelTxt = escapeHtml(row.label);
    li.innerHTML = `
      <span class="coloc-medal" aria-hidden="true">${medal}</span>
      <div class="coloc-corpo">
        <span class="coloc-label">${labelTxt}</span>
        <div class="coloc-main">
          <span class="coloc-nome">${escapeHtml(row.atleta.nome)}</span>
          <span class="coloc-acad">${escapeHtml(row.atleta.academia || '—')}</span>
        </div>
      </div>`;
    ul.appendChild(li);
  });

  wrap.appendChild(ul);
  sec.appendChild(wrap);
}

// ── Rodízio ───────────────────────────────────────────────────

function renderRodizio(data) {
  const bracketEl = document.getElementById('bracket');
  const sec       = document.getElementById('secao-3lugar');

  // Título + lutas
  const wrap = document.createElement('div');
  wrap.className = 'rodizio-wrap';

  const titulo = document.createElement('div');
  titulo.className = 'rodizio-titulo';
  titulo.textContent = 'Rodízio — Todos contra Todos';
  wrap.appendChild(titulo);

  const lutas = document.createElement('div');
  lutas.className = 'rodizio-lutas';

  const round = data.rounds[0];
  round.lutas.forEach((luta, idx) => {
    const row = document.createElement('div');
    row.className = 'rodizio-row';

    const num = document.createElement('span');
    num.className = 'rodizio-num';
    num.textContent = `Luta ${idx + 1}`;
    row.appendChild(num);

    row.appendChild(criarMatchCard(luta));

    // link para mesa se luta ainda não encerrada
    if (!luta.resultado && luta.azul && luta.branco) {
      const link = document.createElement('a');
      link.href = `/mesa/${luta.id}`;
      link.className = 'rodizio-mesa-btn';
      link.textContent = '⚔️ Chamar';
      row.appendChild(link);
    } else if (luta.resultado) {
      const done = document.createElement('span');
      done.className = 'rodizio-encerrada';
      done.textContent = '✓ Encerrada';
      row.appendChild(done);
    }

    lutas.appendChild(row);
  });

  wrap.appendChild(lutas);
  bracketEl.appendChild(wrap);

  // Classificação (medalhas / destaque só quando rodízio 100% encerrado)
  if (data.classificacao?.length) {
    sec.appendChild(criarTabelaClassificacao(data.classificacao, !!data.rodizio_completo));
  }
}

function criarTabelaClassificacao(classificacao, exibirMedalhas = true) {
  const wrap = document.createElement('div');
  wrap.className = 'classif-wrap';

  const subt = exibirMedalhas
    ? ''
    : '<div class="classif-sub">Ordem provisória — pódio após todas as lutas encerradas</div>';

  wrap.innerHTML = `
    <div class="classif-titulo">Classificação</div>
    ${subt}
    <table class="classif-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Atleta</th>
          <th>Academia</th>
          <th>V</th>
          <th>D</th>
          <th>Pts</th>
        </tr>
      </thead>
      <tbody>
        ${classificacao.map(s => {
    const rowClass = exibirMedalhas
      ? (s.posicao === 1 ? 'classif-1' : s.posicao === 2 ? 'classif-2' : s.posicao === 3 ? 'classif-3' : '')
      : '';
    const colHash = exibirMedalhas ? medalha(s.posicao) : String(s.posicao);
    return `
          <tr class="${rowClass}">
            <td class="classif-pos">${colHash}</td>
            <td class="classif-nome">${escapeHtml(s.atleta.nome)}</td>
            <td class="classif-team">${escapeHtml(s.atleta.academia || '—')}</td>
            <td class="classif-v">${s.vitorias}</td>
            <td class="classif-d">${s.derrotas}</td>
            <td class="classif-pts">${s.pontos}</td>
          </tr>`;
  }).join('')}
      </tbody>
    </table>`;

  return wrap;
}

function medalha(pos) {
  return pos === 1 ? '🥇' : pos === 2 ? '🥈' : pos === 3 ? '🥉' : pos;
}

// ── Round column ──────────────────────────────────────────────

function criarRoundCol(round, matchCardOpts = {}) {
  const col = document.createElement('div');
  col.className = 'round-col';
  col.dataset.fase = round.fase;

  const label = document.createElement('div');
  label.className = 'round-label';
  label.textContent = round.label;
  col.appendChild(label);

  const matches = document.createElement('div');
  matches.className = 'round-matches';

  round.lutas.forEach(luta => {
    const slot = document.createElement('div');
    slot.className = 'match-slot';
    slot.appendChild(criarMatchCard(luta, matchCardOpts));
    anexarBotaoMesa(slot, luta);
    matches.appendChild(slot);
  });

  col.appendChild(matches);
  return col;
}

// ── Link Mesa (chave / 3º lugar) ──────────────────────────────

function anexarBotaoMesa(container, luta) {
  if (!luta.azul || !luta.branco) return;
  if (!luta.resultado) {
    const link = document.createElement('a');
    link.href = `/mesa/${luta.id}`;
    link.className = 'bracket-mesa-btn';
    link.textContent = '⚔️ Mesa';
    container.appendChild(link);
  } else {
    const ok = document.createElement('span');
    ok.className = 'bracket-luta-encerrada';
    ok.textContent = '✓';
    ok.title = 'Encerrada';
    container.appendChild(ok);
  }
}

// ── Match card ────────────────────────────────────────────────

function criarMatchCard(luta, opts = {}) {
  const { lutaDecisivaBo3Id = null } = opts;
  const fase = luta.fase;
  const isFinalElim = fase === 'final';
  const isDecisivaBo3 =
    fase === 'final_bo3' && lutaDecisivaBo3Id != null && luta.id === lutaDecisivaBo3Id;
  const campeaoHighlight = isFinalElim || isDecisivaBo3;
  const usarLayoutCampeao = campeaoHighlight && luta.vencedor_id;

  const card = document.createElement('div');
  card.className = 'match-card';
  card.dataset.lutaId = luta.id;

  const placar   = calcularPlacar(luta);
  const anterior = _estadoAnterior[luta.id] || {};

  const animaAzul   = luta.azul   && anterior.azul_id   == null && luta.azul?.id   != null;
  const animaBranco = luta.branco && anterior.branco_id == null && luta.branco?.id != null;

  const azulEl = criarAtleta(
    luta.azul, 'azul', luta.vencedor_id, placar.azul, animaAzul, campeaoHighlight
  );
  const brancoEl = criarAtleta(
    luta.branco, 'branco', luta.vencedor_id, placar.branco, animaBranco, campeaoHighlight
  );

  const vs = document.createElement('div');
  vs.className = 'vs-divider';
  vs.textContent = 'vs';

  if (usarLayoutCampeao && luta.azul && luta.branco) {
    card.classList.add('match-card--campeao');
    const wonAzul = luta.vencedor_id === luta.azul.id;
    const winnerEl = wonAzul ? azulEl : brancoEl;
    const loserEl = wonAzul ? brancoEl : azulEl;
    card.appendChild(winnerEl);
    const bottom = document.createElement('div');
    bottom.className = 'match-card-campeao-bottom';
    bottom.appendChild(vs);
    bottom.appendChild(loserEl);
    card.appendChild(bottom);
  } else {
    card.appendChild(azulEl);
    card.appendChild(vs);
    card.appendChild(brancoEl);
  }

  _estadoAnterior[luta.id] = {
    azul_id:   luta.azul?.id   ?? null,
    branco_id: luta.branco?.id ?? null,
  };

  return card;
}

function criarAtleta(atleta, lado, vencedorId, pontos, isNovo = false, campeaoHighlight = false) {
  const div = document.createElement('div');
  div.className = `athlete ${lado}`;

  if (!atleta) {
    div.classList.add('vago');
    div.innerHTML = `
      <div class="ac-foto"><div class="ac-iniciais">?</div></div>
      <div class="ac-info">
        <div class="ac-nome">A definir</div>
        <div class="ac-team"></div>
      </div>`;
    return div;
  }

  if (isNovo) div.classList.add('novo');

  if (vencedorId != null) {
    const venceu = atleta.id === vencedorId;
    if (venceu && campeaoHighlight) div.classList.add('winner-campeao');
    else if (venceu) div.classList.add('winner');
    else div.classList.add('loser');
  }

  const fotoHtml = atleta.foto_url
    ? `<img src="${escapeHtml(atleta.foto_url)}" alt="${escapeHtml(atleta.nome)}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`
    : '';
  const avatarFallback = atleta.foto_url
    ? `<div class="ac-iniciais" style="display:none">${escapeHtml(atleta.iniciais)}</div>`
    : `<div class="ac-iniciais">${escapeHtml(atleta.iniciais)}</div>`;

  const scoreHtml = pontos != null
    ? `<div class="ac-score">${pontos}</div>`
    : '';

  div.innerHTML = `
    <div class="ac-foto">${fotoHtml}${avatarFallback}</div>
    <div class="ac-info">
      <div class="ac-nome">${escapeHtml(atleta.nome)}</div>
      <div class="ac-team">${escapeHtml(atleta.academia || '')}</div>
      ${scoreHtml}
    </div>`;

  return div;
}

function calcularPlacar(luta) {
  if (!luta.resultado) return { azul: null, branco: null };
  const r = luta.resultado;
  const linha = (i, w, y, sh) =>
    `I${i} W${w} Y${y}` + (sh ? ` S${sh}` : '');
  return {
    azul: linha(
      r.ippon_azul || 0,
      r.wazari_azul || 0,
      r.yuko_azul || 0,
      r.shido_azul || 0
    ),
    branco: linha(
      r.ippon_branco || 0,
      r.wazari_branco || 0,
      r.yuko_branco || 0,
      r.shido_branco || 0
    ),
  };
}

// ── SVG Connectors ────────────────────────────────────────────
//
//   Cada par de lutas (r[i].m0, r[i].m1) conecta à luta r[i+1].m0:
//
//   match0 ────┐
//              │          (right-angle elbow)
//              ├────────► match_next
//              │
//   match1 ────┘

function desenharConectores(rounds) {
  const svg   = document.getElementById('connectors');
  const scroll = document.getElementById('bracket-scroll');

  svg.innerHTML = '';
  svg.style.width  = scroll.scrollWidth  + 'px';
  svg.style.height = scroll.scrollHeight + 'px';

  const cRect = scroll.getBoundingClientRect();

  for (let r = 0; r < rounds.length - 1; r++) {
    const faseAtual = rounds[r].fase;
    const faseSeg   = rounds[r + 1].fase;

    const slotsAtuais = [...document.querySelectorAll(`[data-fase="${faseAtual}"] .match-slot`)];
    const slotsProx   = [...document.querySelectorAll(`[data-fase="${faseSeg}"]   .match-slot`)];

    slotsProx.forEach((slotDst, m) => {
      const slot1 = slotsAtuais[m * 2];
      const slot2 = slotsAtuais[m * 2 + 1];
      if (!slot1 || !slot2) return;

      const card1   = slot1.querySelector('.match-card');
      const card2   = slot2.querySelector('.match-card');
      const cardDst = slotDst.querySelector('.match-card');
      if (!card1 || !card2 || !cardDst) return;

      desenharElbow(svg, card1, card2, cardDst, cRect, scroll);
    });
  }
}

function desenharElbow(svg, src1, src2, dst, cRect, scroll) {
  // posições relativas ao conteúdo do scroll (não ao viewport)
  const pos = el => {
    const r = el.getBoundingClientRect();
    return {
      left:  r.left  - cRect.left + scroll.scrollLeft,
      right: r.right - cRect.left + scroll.scrollLeft,
      midY:  r.top   - cRect.top  + scroll.scrollTop + r.height / 2,
    };
  };

  const p1 = pos(src1);
  const p2 = pos(src2);
  const pd = pos(dst);

  const xSaida = p1.right;          // ponto de saída dos cards fonte
  const xChegada = pd.left;         // ponto de chegada no card destino
  const xCotovelo = xSaida + (xChegada - xSaida) / 2;  // ponto de dobra
  const yJuncao   = (p1.midY + p2.midY) / 2;            // altura de junção

  // Linha de saída do card 1  →  cotovelo  →  junção
  path(svg, `M ${xSaida} ${p1.midY} H ${xCotovelo} V ${yJuncao}`);
  // Linha de saída do card 2  →  cotovelo  →  junção
  path(svg, `M ${xSaida} ${p2.midY} H ${xCotovelo} V ${yJuncao}`);
  // Junção  →  card destino
  path(svg, `M ${xCotovelo} ${yJuncao} H ${xChegada}`);
}

function path(svg, d) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  el.setAttribute('d', d);
  el.setAttribute('fill', 'none');
  el.setAttribute('stroke', '#2d3748');
  el.setAttribute('stroke-width', '2');
  el.setAttribute('stroke-linecap', 'round');
  el.setAttribute('stroke-linejoin', 'round');
  svg.appendChild(el);
}

// ── Util ──────────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Redesenha conectores ao redimensionar a janela
window.addEventListener('resize', () => {
  if (_lastData?.rounds) {
    const rc = _lastData.rounds.filter(
      r => !String(r.fase).startsWith('repescagem') && !String(r.fase).startsWith('disputa_3lugar')
    );
    desenharConectores(rc);
  }
});
