/**
 * Chave eliminatória — render + conectores SVG + polling.
 * Depende de: window.JV_CONFIG = { apiUrl, controleUrl, pollMs }
 */
(function () {
  const POLL_MS = (window.JV_CONFIG && window.JV_CONFIG.pollMs) || 5000;
  let _timer = null;
  let _lastPayload = null;

  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function controleUrl(lutaId) {
    const tpl = window.JV_CONFIG && window.JV_CONFIG.controleUrl;
    if (!tpl) return "#";
    return tpl.replace("__LID__", String(lutaId));
  }

  function setLive(on) {
    const dot = document.getElementById("jv-dot");
    if (dot) dot.className = "jv-dot" + (on ? " jv-dot--live" : "");
  }

  function renderAthlete(a, lado, vencedor, marcador) {
    const won = vencedor === lado;
    const lost = vencedor && vencedor !== lado;
    const cls = [
      "jv-ath",
      lado === "azul" ? "jv-ath--azul" : "",
      won ? "jv-ath--winner" : "",
      lost ? "jv-ath--loser" : "",
      a.placeholder ? "jv-ath--placeholder" : "",
    ]
      .filter(Boolean)
      .join(" ");
    const seed = lado === "branco" ? "1" : "2";
    const mar = marcador ? `<span class="jv-marc">${escapeHtml(marcador)}</span>` : "";
    return `<div class="${cls}">
      <span class="jv-seed">${seed}</span>
      <span class="jv-sigla">${escapeHtml(a.sigla)}</span>
      <span class="jv-nome">${escapeHtml(a.nome)}</span>${mar}
    </div>`;
  }

  function renderMatch(luta) {
    const canPlacar =
      !luta.branco.placeholder && !luta.azul.placeholder && luta.branco.nome !== "BYE" && luta.azul.nome !== "BYE";
    const href = controleUrl(luta.id);
    const mb = luta.vencedor === "branco" ? luta.marcador_branco : "";
    const ma = luta.vencedor === "azul" ? luta.marcador_azul : "";
    const inner = `
      ${renderAthlete(luta.branco, "branco", luta.vencedor, mb)}
      ${renderAthlete(luta.azul, "azul", luta.vencedor, ma)}
    `;
    const card = `<a class="jv-match-card" href="${escapeHtml(href)}" target="_blank" data-luta-id="${luta.id}">${inner}</a>`;

    const btnLabel = luta.resultado ? "Ver placar" : "Abrir placar";
    const btn = `<a class="jv-placar-btn" href="${escapeHtml(href)}" target="_blank">${btnLabel}</a>`;

    return `
      <div class="jv-match-slot">
        ${card}
        <div class="jv-match-num" title="ID da luta">${luta.numero_exibicao ?? luta.id}</div>
        ${canPlacar || luta.resultado ? btn : ""}
      </div>
    `;
  }

  function renderRound(round) {
    const lutasHtml = round.lutas.map(renderMatch).join("");
    return `
      <div class="jv-round-col" data-fase="${escapeHtml(round.fase)}">
        <div class="jv-round-label">${escapeHtml(round.label)}</div>
        <div class="jv-round-matches">${lutasHtml}</div>
      </div>
    `;
  }

  function render(data) {
    const bracket = document.getElementById("jv-bracket");
    const msg = document.getElementById("jv-message");
    if (!bracket) return;

    if (!data || data.tipo !== "eliminacao" || !data.rounds || data.rounds.length === 0) {
      bracket.innerHTML = "";
      if (msg) {
        msg.style.display = "block";
        msg.textContent = data && data.mensagem ? data.mensagem : "Sem dados de chave.";
      }
      document.getElementById("jv-connectors").innerHTML = "";
      return;
    }
    if (msg) msg.style.display = "none";
    bracket.innerHTML = data.rounds.map(renderRound).join("");
    requestAnimationFrame(() => requestAnimationFrame(() => desenharConectores(data.rounds)));
  }

  function path(svg, d, stroke) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", "path");
    el.setAttribute("d", d);
    el.setAttribute("fill", "none");
    el.setAttribute("stroke", stroke || "#fbc02d");
    el.setAttribute("stroke-width", "2.5");
    el.setAttribute("stroke-linecap", "round");
    el.setAttribute("stroke-linejoin", "round");
    svg.appendChild(el);
  }

  function desenharConectores(rounds) {
    const svg = document.getElementById("jv-connectors");
    const scroll = document.getElementById("jv-bracket-scroll");
    if (!svg || !scroll || !rounds || rounds.length < 2) {
      if (svg) svg.innerHTML = "";
      return;
    }

    const cRect = scroll.getBoundingClientRect();
    svg.innerHTML = "";
    svg.style.width = scroll.scrollWidth + "px";
    svg.style.height = scroll.scrollHeight + "px";

    function pos(el) {
      const r = el.getBoundingClientRect();
      return {
        left: r.left - cRect.left + scroll.scrollLeft,
        right: r.right - cRect.left + scroll.scrollLeft,
        midY: r.top - cRect.top + scroll.scrollTop + r.height / 2,
      };
    }

    for (let r = 0; r < rounds.length - 1; r++) {
      const f0 = rounds[r].fase;
      const f1 = rounds[r + 1].fase;
      const slots0 = [...document.querySelectorAll(`[data-fase="${f0}"] .jv-match-slot`)];
      const slots1 = [...document.querySelectorAll(`[data-fase="${f1}"] .jv-match-slot`)];

      slots1.forEach((slotDst, m) => {
        const s1 = slots0[m * 2];
        const s2 = slots0[m * 2 + 1];
        if (!s1 || !s2) return;
        const card1 = s1.querySelector(".jv-match-card");
        const card2 = s2.querySelector(".jv-match-card");
        const cardD = slotDst.querySelector(".jv-match-card");
        if (!card1 || !card2 || !cardD) return;
        const p1 = pos(card1);
        const p2 = pos(card2);
        const pd = pos(cardD);
        const xOut = p1.right;
        const xIn = pd.left;
        const xMid = xOut + (xIn - xOut) / 2;
        const yMid = (p1.midY + p2.midY) / 2;
        path(svg, `M ${xOut} ${p1.midY} H ${xMid} V ${yMid}`);
        path(svg, `M ${xOut} ${p2.midY} H ${xMid} V ${yMid}`);
        path(svg, `M ${xMid} ${yMid} H ${xIn}`);
      });
    }
  }

  async function carregar() {
    const url = window.JV_CONFIG && window.JV_CONFIG.apiUrl;
    if (!url) return;
    try {
      const resp = await fetch(url, { credentials: "same-origin" });
      if (!resp.ok) throw new Error(String(resp.status));
      const data = await resp.json();
      _lastPayload = data;
      render(data);
      setLive(true);
    } catch (e) {
      console.warn("[jv] fetch", e);
      setLive(false);
    }
  }

  function init() {
    carregar();
    _timer = setInterval(carregar, POLL_MS);
    window.addEventListener("resize", () => {
      if (_lastPayload && _lastPayload.rounds) desenharConectores(_lastPayload.rounds);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
