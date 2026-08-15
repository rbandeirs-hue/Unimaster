/* =============================================================
   Bracket — estilo Placar/bracket.html integrado ao Unimaster
   API: competicoes.chave_visual_api (montar_payload_chave_visual)
   Config: window.BRACKET_CONFIG = { apiUrl, mesaUrlTpl, pollMs,
            categoriaNome, competicaoNome }
   ============================================================= */

const POLL_INTERVAL = (window.BRACKET_CONFIG && window.BRACKET_CONFIG.pollMs) || 10_000;
let _pollingTimer = null;
let _lastData = null;
const _estadoAnterior = {};

function mesaHref(lutaId) {
  const tpl = (window.BRACKET_CONFIG && window.BRACKET_CONFIG.mesaUrlTpl) || "";
  if (!tpl) return "#";
  return tpl.replace("__LID__", String(lutaId));
}

function iniciaisDe(nome) {
  const p = String(nome || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (p.length === 0) return "?";
  if (p.length === 1) return p[0].substring(0, 2).toUpperCase();
  return (p[0][0] + p[p.length - 1][0]).toUpperCase();
}

/** Converte payload de utils.judo_bracket_visual para o formato esperado pelo render. */
function adaptPayloadUnimaster(raw) {
  if (raw && (raw.tipo === "rodizio" || raw.tipo === "melhor3")) {
    if (!raw.categoria) {
      raw.categoria = {
        nome: (window.BRACKET_CONFIG && window.BRACKET_CONFIG.categoriaNome) || "",
        competicao: (window.BRACKET_CONFIG && window.BRACKET_CONFIG.competicaoNome) || "",
      };
    }
    return raw;
  }
  if (!raw || !raw.rounds || !raw.rounds.length) {
    return {
      tipo: raw?.tipo || "vazio",
      mensagem: raw?.mensagem || "",
      rounds: [],
      categoria: {
        nome: (window.BRACKET_CONFIG && window.BRACKET_CONFIG.categoriaNome) || "",
        competicao: (window.BRACKET_CONFIG && window.BRACKET_CONFIG.competicaoNome) || "",
      },
      rounds_inferiores: [],
      colocacoes: [],
    };
  }
  const first = raw.rounds[0].lutas && raw.rounds[0].lutas[0];
  if (!first || !Object.prototype.hasOwnProperty.call(first, "vencedor")) {
    if (!raw.categoria) {
      raw.categoria = {
        nome: (window.BRACKET_CONFIG && window.BRACKET_CONFIG.categoriaNome) || "",
        competicao: (window.BRACKET_CONFIG && window.BRACKET_CONFIG.competicaoNome) || "",
      };
    }
    return raw;
  }

  const nr = raw.rounds.length;
  const rounds = raw.rounds.map((round, ri) => ({
    label: round.label,
    fase: round.fase,
    lutas: round.lutas.map((l) => {
      const mk = (side) => {
        const a = side === "azul" ? l.azul : l.branco;
        if (!a || a.placeholder || !a.nome || a.nome === "BYE") return null;
        return {
          id: `${l.id}-${side}`,
          nome: a.nome,
          academia: a.academia || "",
          iniciais: iniciaisDe(a.nome),
          foto_url: null,
        };
      };
      const azul = mk("azul");
      const branco = mk("branco");
      let vencedor_id = null;
      if (l.vencedor === "azul" && azul) vencedor_id = azul.id;
      if (l.vencedor === "branco" && branco) vencedor_id = branco.id;
      const isFinal = ri === nr - 1;
      const fin = !!l.resultado;
      return {
        id: l.id,
        fase: isFinal ? "final" : "principal",
        azul,
        branco,
        vencedor_id,
        resultado: null,
        _encerrada: fin,
      };
    }),
  }));

  return {
    tipo: "eliminacao",
    mensagem: raw.mensagem || "",
    rounds,
    categoria: {
      nome: (window.BRACKET_CONFIG && window.BRACKET_CONFIG.categoriaNome) || "",
      competicao: (window.BRACKET_CONFIG && window.BRACKET_CONFIG.competicaoNome) || "",
    },
    rounds_inferiores: [],
    colocacoes: [],
  };
}

document.addEventListener("DOMContentLoaded", () => {
  carregarBracket();
  _pollingTimer = setInterval(carregarBracket, POLL_INTERVAL);
});

async function carregarBracket() {
  const apiUrl = window.BRACKET_CONFIG && window.BRACKET_CONFIG.apiUrl;
  if (!apiUrl) {
    console.warn("[bracket] BRACKET_CONFIG.apiUrl ausente");
    setDotStatus("off");
    return;
  }
  try {
    const resp = await fetch(apiUrl, { credentials: "same-origin" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const raw = await resp.json();
    const data = adaptPayloadUnimaster(raw);
    _lastData = data;
    renderBracket(data);
    setDotStatus("live");
  } catch (e) {
    console.error("[bracket] Falha ao carregar:", e);
    setDotStatus("off");
  }
}

function setDotStatus(state) {
  const dot = document.getElementById("status-dot");
  if (!dot) return;
  dot.className = state === "live" ? "dot dot--live" : "dot";
}

function renderBracket(data) {
  const catNome = document.getElementById("cat-nome");
  const compNome = document.getElementById("comp-nome");
  const cat = data.categoria || { nome: "", competicao: "" };
  if (catNome) catNome.textContent = cat.nome || (window.BRACKET_CONFIG && window.BRACKET_CONFIG.categoriaNome) || "…";
  if (compNome) compNome.textContent = cat.competicao || (window.BRACKET_CONFIG && window.BRACKET_CONFIG.competicaoNome) || "";

  const bracketEl = document.getElementById("bracket");
  if (!bracketEl) return;
  bracketEl.innerHTML = "";

  const sec = document.getElementById("secao-3lugar");
  if (sec) sec.innerHTML = "";

  if (data.tipo === "nao_eliminatoria" || data.tipo === "vazio") {
    const msg = data.mensagem || "Sem dados de chave para esta categoria.";
    bracketEl.innerHTML = `<div class="state-msg">${escapeHtml(msg)}</div>`;
    const sc = document.getElementById("secao-colocacoes");
    if (sc) sc.innerHTML = "";
    return;
  }

  if (!data.rounds || data.rounds.length === 0) {
    bracketEl.innerHTML =
      '<div class="state-msg">⚔️ Chave ainda não gerada para esta categoria.</div>';
    const sc = document.getElementById("secao-colocacoes");
    if (sc) sc.innerHTML = "";
    return;
  }

  if (data.tipo === "rodizio") {
    renderRodizio(data);
    renderColocacoes(data);
    return;
  }

  if (data.tipo === "melhor3") {
    const ctxBo3 = contextoMelhorDe3(data.rounds[0]?.lutas || []);
    const opts = { lutaDecisivaBo3Id: ctxBo3.lutaDecisivaId };
    data.rounds.forEach((round) => bracketEl.appendChild(criarRoundCol(round, opts)));
    requestAnimationFrame(() => requestAnimationFrame(() => desenharConectores(data.rounds)));
    renderColocacoes(data);
    return;
  }

  data.rounds.forEach((round) => bracketEl.appendChild(criarRoundCol(round)));
  renderRoundsInferiores(data);
  requestAnimationFrame(() => requestAnimationFrame(() => desenharConectores(data.rounds)));
  renderColocacoes(data);
}

function contextoMelhorDe3(lutas) {
  const sorted = [...lutas].sort((a, b) => (a.numero || 0) - (b.numero || 0));
  const base = sorted.find((l) => l.azul?.id && l.branco?.id);
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
  const sec = document.getElementById("secao-3lugar");
  const ri = data.rounds_inferiores;
  if (!sec || !ri || ri.length === 0) return;

  const wrap = document.createElement("div");
  wrap.className = "bracket-inferior-wrap";

  const titulo = document.createElement("div");
  titulo.className = "bracket-inferior-titulo";
  titulo.textContent = "Repescagem e disputas de pódio";
  wrap.appendChild(titulo);

  const scroll = document.createElement("div");
  scroll.className = "bracket-inferior-scroll";

  const row = document.createElement("div");
  row.className = "bracket-inferior-trilha";
  ri.forEach((round) => row.appendChild(criarRoundCol(round)));

  scroll.appendChild(row);
  wrap.appendChild(scroll);
  sec.appendChild(wrap);
}

function iconeMedalhaColocacao(lugar) {
  if (lugar === 1) return "🥇";
  if (lugar === 2) return "🥈";
  if (lugar === 3) return "🥉";
  return "🏅";
}

function renderColocacoes(data) {
  const sec = document.getElementById("secao-colocacoes");
  if (!sec) return;
  sec.innerHTML = "";
  const items = data.colocacoes;
  if (!items || items.length === 0) return;

  const wrap = document.createElement("div");
  wrap.className = "colocacoes-wrap";

  const titulo = document.createElement("div");
  titulo.className = "colocacoes-titulo";
  titulo.innerHTML = '<span class="colocacoes-titulo-ico" aria-hidden="true">🏆</span> Colocações';
  wrap.appendChild(titulo);

  const ul = document.createElement("ul");
  ul.className = "colocacoes-lista";

  items.forEach((row) => {
    const medal = iconeMedalhaColocacao(row.lugar);
    const li = document.createElement("li");
    li.className = `coloc-item coloc-lugar-${row.lugar}`;
    const labelTxt = escapeHtml(row.label);
    li.innerHTML = `
      <span class="coloc-medal" aria-hidden="true">${medal}</span>
      <div class="coloc-corpo">
        <span class="coloc-label">${labelTxt}</span>
        <div class="coloc-main">
          <span class="coloc-nome">${escapeHtml(row.atleta.nome)}</span>
          <span class="coloc-acad">${escapeHtml(row.atleta.academia || "—")}</span>
        </div>
      </div>`;
    ul.appendChild(li);
  });

  wrap.appendChild(ul);
  sec.appendChild(wrap);
}

function renderRodizio(data) {
  const bracketEl = document.getElementById("bracket");
  const sec = document.getElementById("secao-3lugar");
  if (!bracketEl) return;

  const wrap = document.createElement("div");
  wrap.className = "rodizio-wrap";

  const titulo = document.createElement("div");
  titulo.className = "rodizio-titulo";
  titulo.textContent = (data && data.rodizio_titulo) || "Rodízio — Todos contra todos";
  wrap.appendChild(titulo);

  const lutas = document.createElement("div");
  lutas.className = "rodizio-lutas";

  const round = data.rounds[0];
  if (!round || !round.lutas || !round.lutas.length) {
    bracketEl.innerHTML = '<div class="state-msg">Nenhum confronto nesta categoria.</div>';
    return;
  }
  round.lutas.forEach((luta, idx) => {
    const row = document.createElement("div");
    row.className = "rodizio-row";

    const num = document.createElement("span");
    num.className = "rodizio-num";
    num.textContent = `Luta ${idx + 1}`;
    row.appendChild(num);

    row.appendChild(criarMatchCard(luta));

    if (!luta._encerrada && !luta.resultado && luta.azul && luta.branco) {
      const link = document.createElement("a");
      link.href = mesaHref(luta.id);
      link.target = "_blank";
      link.rel = "noopener";
      link.className = "rodizio-mesa-btn";
      link.textContent = "⚔️ Chamar";
      row.appendChild(link);
    } else if (luta.resultado || luta._encerrada) {
      const done = document.createElement("span");
      done.className = "rodizio-encerrada";
      done.textContent = "✓ Encerrada";
      row.appendChild(done);
    }

    lutas.appendChild(row);
  });

  wrap.appendChild(lutas);
  bracketEl.appendChild(wrap);

  if (sec && data.classificacao?.length) {
    sec.appendChild(criarTabelaClassificacao(data.classificacao, !!data.rodizio_completo));
  }
}

function criarTabelaClassificacao(classificacao, exibirMedalhas = true) {
  const wrap = document.createElement("div");
  wrap.className = "classif-wrap";

  const subt = exibirMedalhas
    ? ""
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
        ${classificacao
          .map((s) => {
            const rowClass = exibirMedalhas
              ? s.posicao === 1
                ? "classif-1"
                : s.posicao === 2
                  ? "classif-2"
                  : s.posicao === 3
                    ? "classif-3"
                    : ""
              : "";
            const colHash = exibirMedalhas ? medalha(s.posicao) : String(s.posicao);
            return `
          <tr class="${rowClass}">
            <td class="classif-pos">${colHash}</td>
            <td class="classif-nome">${escapeHtml(s.atleta.nome)}</td>
            <td class="classif-team">${escapeHtml(s.atleta.academia || "—")}</td>
            <td class="classif-v">${s.vitorias}</td>
            <td class="classif-d">${s.derrotas}</td>
            <td class="classif-pts">${s.pontos}</td>
          </tr>`;
          })
          .join("")}
      </tbody>
    </table>`;

  return wrap;
}

function medalha(pos) {
  return pos === 1 ? "🥇" : pos === 2 ? "🥈" : pos === 3 ? "🥉" : pos;
}

function criarRoundCol(round, matchCardOpts = {}) {
  const col = document.createElement("div");
  col.className = "round-col";
  col.dataset.fase = round.fase;

  const label = document.createElement("div");
  label.className = "round-label";
  label.textContent = round.label;
  col.appendChild(label);

  const matches = document.createElement("div");
  matches.className = "round-matches";

  round.lutas.forEach((luta) => {
    const slot = document.createElement("div");
    slot.className = "match-slot";
    slot.appendChild(criarMatchCard(luta, matchCardOpts));
    anexarBotaoMesa(slot, luta);
    matches.appendChild(slot);
  });

  col.appendChild(matches);
  return col;
}

function anexarBotaoMesa(container, luta) {
  if (!luta.azul || !luta.branco) return;
  if (!luta._encerrada && !luta.resultado) {
    const link = document.createElement("a");
    link.href = mesaHref(luta.id);
    link.target = "_blank";
    link.rel = "noopener";
    link.className = "bracket-mesa-btn";
    link.textContent = "⚔️ Placar";
    container.appendChild(link);
  } else {
    const ok = document.createElement("span");
    ok.className = "bracket-luta-encerrada";
    ok.textContent = "✓";
    ok.title = "Encerrada";
    container.appendChild(ok);
  }
}

function criarMatchCard(luta, opts = {}) {
  const { lutaDecisivaBo3Id = null } = opts;
  const fase = luta.fase;
  const isFinalElim = fase === "final";
  const isDecisivaBo3 =
    fase === "final_bo3" && lutaDecisivaBo3Id != null && luta.id === lutaDecisivaBo3Id;
  const campeaoHighlight = isFinalElim || isDecisivaBo3;
  const usarLayoutCampeao = campeaoHighlight && luta.vencedor_id;

  const card = document.createElement("div");
  card.className = "match-card";
  card.dataset.lutaId = luta.id;

  const placar = calcularPlacar(luta);
  const anterior = _estadoAnterior[luta.id] || {};

  const animaAzul = luta.azul && anterior.azul_id == null && luta.azul?.id != null;
  const animaBranco = luta.branco && anterior.branco_id == null && luta.branco?.id != null;

  const azulEl = criarAtleta(
    luta.azul,
    "azul",
    luta.vencedor_id,
    placar.azul,
    animaAzul,
    campeaoHighlight
  );
  const brancoEl = criarAtleta(
    luta.branco,
    "branco",
    luta.vencedor_id,
    placar.branco,
    animaBranco,
    campeaoHighlight
  );

  const vs = document.createElement("div");
  vs.className = "vs-divider";
  vs.textContent = "vs";

  if (usarLayoutCampeao && luta.azul && luta.branco) {
    card.classList.add("match-card--campeao");
    const wonAzul = luta.vencedor_id === luta.azul.id;
    const winnerEl = wonAzul ? azulEl : brancoEl;
    const loserEl = wonAzul ? brancoEl : azulEl;
    card.appendChild(winnerEl);
    const bottom = document.createElement("div");
    bottom.className = "match-card-campeao-bottom";
    bottom.appendChild(vs);
    bottom.appendChild(loserEl);
    card.appendChild(bottom);
  } else {
    card.appendChild(azulEl);
    card.appendChild(vs);
    card.appendChild(brancoEl);
  }

  _estadoAnterior[luta.id] = {
    azul_id: luta.azul?.id ?? null,
    branco_id: luta.branco?.id ?? null,
  };

  return card;
}

function criarAtleta(atleta, lado, vencedorId, pontos, isNovo = false, campeaoHighlight = false) {
  const div = document.createElement("div");
  div.className = `athlete ${lado}`;

  if (!atleta) {
    div.classList.add("vago");
    div.innerHTML = `
      <div class="ac-foto"><div class="ac-iniciais">?</div></div>
      <div class="ac-info">
        <div class="ac-nome">A definir</div>
        <div class="ac-team"></div>
      </div>`;
    return div;
  }

  if (isNovo) div.classList.add("novo");

  if (vencedorId != null) {
    const venceu = atleta.id === vencedorId;
    if (venceu && campeaoHighlight) div.classList.add("winner-campeao");
    else if (venceu) div.classList.add("winner");
    else div.classList.add("loser");
  }

  const fotoHtml = atleta.foto_url
    ? `<img src="${escapeHtml(atleta.foto_url)}" alt="${escapeHtml(atleta.nome)}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`
    : "";
  const avatarFallback = atleta.foto_url
    ? `<div class="ac-iniciais" style="display:none">${escapeHtml(atleta.iniciais)}</div>`
    : `<div class="ac-iniciais">${escapeHtml(atleta.iniciais)}</div>`;

  const scoreHtml = pontos != null ? `<div class="ac-score">${pontos}</div>` : "";

  div.innerHTML = `
    <div class="ac-foto">${fotoHtml}${avatarFallback}</div>
    <div class="ac-info">
      <div class="ac-nome">${escapeHtml(atleta.nome)}</div>
      <div class="ac-team">${escapeHtml(atleta.academia || "")}</div>
      ${scoreHtml}
    </div>`;

  return div;
}

function calcularPlacar(luta) {
  if (!luta.resultado) return { azul: null, branco: null };
  const r = luta.resultado;
  if (typeof r !== "object" || r == null) return { azul: null, branco: null };
  const linha = (i, w, y, sh) => `I${i} W${w} Y${y}` + (sh ? ` S${sh}` : "");
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

function desenharConectores(rounds) {
  const svg = document.getElementById("connectors");
  const scroll = document.getElementById("bracket-scroll");
  if (!svg || !scroll || !rounds || rounds.length < 2) {
    if (svg) svg.innerHTML = "";
    return;
  }

  const cRect = scroll.getBoundingClientRect();
  svg.innerHTML = "";
  svg.style.width = scroll.scrollWidth + "px";
  svg.style.height = scroll.scrollHeight + "px";

  for (let r = 0; r < rounds.length - 1; r++) {
    const faseAtual = rounds[r].fase;
    const faseSeg = rounds[r + 1].fase;

    const slotsAtuais = [...document.querySelectorAll(`[data-fase="${faseAtual}"] .match-slot`)];
    const slotsProx = [...document.querySelectorAll(`[data-fase="${faseSeg}"]   .match-slot`)];

    slotsProx.forEach((slotDst, m) => {
      const slot1 = slotsAtuais[m * 2];
      const slot2 = slotsAtuais[m * 2 + 1];
      if (!slot1 || !slot2) return;

      const card1 = slot1.querySelector(".match-card");
      const card2 = slot2.querySelector(".match-card");
      const cardDst = slotDst.querySelector(".match-card");
      if (!card1 || !card2 || !cardDst) return;

      desenharElbow(svg, card1, card2, cardDst, cRect, scroll);
    });
  }
}

function desenharElbow(svg, src1, src2, dst, cRect, scroll) {
  const pos = (el) => {
    const r = el.getBoundingClientRect();
    return {
      left: r.left - cRect.left + scroll.scrollLeft,
      right: r.right - cRect.left + scroll.scrollLeft,
      midY: r.top - cRect.top + scroll.scrollTop + r.height / 2,
    };
  };

  const p1 = pos(src1);
  const p2 = pos(src2);
  const pd = pos(dst);

  const xSaida = p1.right;
  const xChegada = pd.left;
  const xCotovelo = xSaida + (xChegada - xSaida) / 2;
  const yJuncao = (p1.midY + p2.midY) / 2;

  path(svg, `M ${xSaida} ${p1.midY} H ${xCotovelo} V ${yJuncao}`);
  path(svg, `M ${xSaida} ${p2.midY} H ${xCotovelo} V ${yJuncao}`);
  path(svg, `M ${xCotovelo} ${yJuncao} H ${xChegada}`);
}

function connectorStroke() {
  return document.body.classList.contains("bracket-theme-light") ? "#94a3b8" : "#2d3748";
}

function path(svg, d) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", "path");
  el.setAttribute("d", d);
  el.setAttribute("fill", "none");
  el.setAttribute("stroke", connectorStroke());
  el.setAttribute("stroke-width", "2");
  el.setAttribute("stroke-linecap", "round");
  el.setAttribute("stroke-linejoin", "round");
  svg.appendChild(el);
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

window.addEventListener("resize", () => {
  if (_lastData?.rounds) {
    const rc = _lastData.rounds.filter(
      (r) =>
        !String(r.fase).startsWith("repescagem") && !String(r.fase).startsWith("disputa_3lugar")
    );
    desenharConectores(rc);
  }
});

window.carregarBracket = carregarBracket;
