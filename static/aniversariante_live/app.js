/**
 * Modo aniversariante — live (ES6+)
 * API relativa ao blueprint Flask /aniversariante-live/
 *
 * WebSocket: defina window.__ANIV_USE_WS__ = true e injete Socket.IO quando integrar.
 */
(function () {
  "use strict";

  const API_BASE =
    window.__ANIV_API_BASE__ ||
    document.body?.dataset?.apiBase ||
    "/aniversariante-live";

  /** Modo responsável: escopo do aluno selecionado (injeta Flask em window.__ANIV_ALUNO_ESCOPO__). */
  function anivAlunoEscopoQuery() {
    const v = window.__ANIV_ALUNO_ESCOPO__;
    if (v != null && v !== "" && Number.isFinite(Number(v))) {
      return `&aluno_id=${encodeURIComponent(String(Number(v)))}`;
    }
    return "";
  }

  const POLL_MS = 4000;
  const MILESTONES = [100, 250, 500, 1000];

  /** Lê token CSRF do meta injetado pelo Flask (Flask-WTF). */
  function getCsrfToken() {
    const m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute("content") || "" : "";
  }

  async function fetchJson(url, opts = {}) {
    const headers = Object.assign(
      { Accept: "application/json", "Content-Type": "application/json" },
      opts.headers || {}
    );
    const t = getCsrfToken();
    if (t) headers["X-CSRFToken"] = t;
    const res = await fetch(url, Object.assign({}, opts, { headers, credentials: "same-origin" }));
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.msg || res.statusText || "Erro na requisição");
      err.status = res.status;
      err.data = data;
      throw err;
    }
    /* Alguns proxies devolvem 200 + JSON de erro; evita usar payload incompleto (ex.: sem aluno). */
    if (data && Object.prototype.hasOwnProperty.call(data, "ok") && data.ok === false) {
      const err = new Error(data.msg || "Erro na requisição");
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  // ---------- Emoji flutuante (requestAnimationFrame + CSS animation) ----------
  /**
   * Gera emojis que sobem pela tela (estilo live).
   * @param {HTMLElement} container — normalmente .fx-layer
   * @param {string} emoji
   * @param {number} count — quantidade (evite poluição: 8–18)
   */
  function spawnFloatingEmojis(container, emoji, count = 12) {
    if (!container || !emoji) return;
    const n = Math.min(Math.max(count, 4), 22);
    const frag = document.createDocumentFragment();
    for (let i = 0; i < n; i++) {
      const el = document.createElement("span");
      el.className = "fx-emoji";
      el.textContent = emoji;
      const x = 8 + Math.random() * 84;
      el.style.left = `${x}%`;
      const dur = 2.2 + Math.random() * 1.4;
      el.style.animationDuration = `${dur}s`;
      const dx = (Math.random() - 0.5) * 120;
      const rot = (Math.random() - 0.5) * 80;
      el.style.setProperty("--dx", `${dx}px`);
      el.style.setProperty("--rot", `${rot}deg`);
      el.style.animationDelay = `${Math.random() * 0.25}s`;
      frag.appendChild(el);
    }
    container.appendChild(frag);
    window.setTimeout(() => {
      while (container.childElementCount > 48) {
        container.removeChild(container.firstChild);
      }
    }, 4200);
  }

  const FESTA_EMOJIS = ["🎈", "✨", "🎊", "🎀", "⭐", "💫", "🎉", "🪩"];

  function trimBalloonLayer(max = 26) {
    const box = el.festaBalloons;
    if (!box) return;
    while (box.childElementCount > max) {
      box.removeChild(box.firstChild);
    }
  }

  /** Balão com foto (ou inicial) + emoji da interação — só modo aniversariante. */
  function spawnBalloonFromEvent(ev) {
    if (!el.festaBalloons || !ev) return;
    const emoji = ev.emoji || "🎉";
    const nome = (ev.autor_nome || "").trim() || "Alguém";
    const foto = (ev.autor_foto_url || "").trim();
    const initial = nome.charAt(0).toUpperCase() || "?";
    const wrap = document.createElement("div");
    wrap.className = "aniv-balloon";
    const x = 8 + Math.random() * 84;
    const drift = `${(Math.random() - 0.5) * 140}px`;
    const dur = 12 + Math.random() * 9;
    wrap.style.setProperty("--bx", `${x}%`);
    wrap.style.setProperty("--drift", drift);
    wrap.style.setProperty("--bdur", `${dur}s`);
    const imgHtml = foto
      ? `<img class="aniv-balloon-photo" src="${escapeHtml(foto)}" alt="">`
      : `<span class="aniv-balloon-fallback" aria-hidden="true">${escapeHtml(initial)}</span>`;
    wrap.innerHTML = `
      <div class="aniv-balloon-card" title="${escapeHtml(nome)}">
        ${imgHtml}
        <span class="aniv-balloon-emoji" aria-hidden="true">${escapeHtml(emoji)}</span>
      </div>
      <div class="aniv-balloon-string" aria-hidden="true"></div>`;
    el.festaBalloons.appendChild(wrap);
    trimBalloonLayer();
    const rm = () => {
      wrap.removeEventListener("animationend", rm);
      wrap.remove();
    };
    wrap.addEventListener("animationend", rm);
  }

  function clearFestaBalloons() {
    if (el.festaBalloons) el.festaBalloons.innerHTML = "";
  }

  function fillFestaBgAmbient() {
    const bg = el.festaBg;
    if (!bg) return;
    bg.innerHTML = "";
    bg.hidden = false;
    const n = 16;
    const frag = document.createDocumentFragment();
    for (let i = 0; i < n; i++) {
      const s = document.createElement("span");
      s.textContent = FESTA_EMOJIS[i % FESTA_EMOJIS.length];
      s.style.left = `${5 + Math.random() * 90}%`;
      s.style.top = `${4 + Math.random() * 88}%`;
      s.style.animationDelay = `${-Math.random() * 8}s`;
      frag.appendChild(s);
    }
    bg.appendChild(frag);
  }

  function stopFestivaAmbient() {
    if (state.festivaTimer) {
      clearInterval(state.festivaTimer);
      state.festivaTimer = null;
    }
    if (el.festaBg) {
      el.festaBg.innerHTML = "";
      el.festaBg.hidden = true;
    }
    clearFestaBalloons();
  }

  function startFestivaAmbient() {
    stopFestivaAmbient();
    if (!state.souAniversariante) return;
    fillFestaBgAmbient();
    state.festivaTimer = window.setInterval(() => {
      if (!state.souAniversariante || !state.liveId) return;
      const pick = FESTA_EMOJIS[Math.floor(Math.random() * FESTA_EMOJIS.length)];
      spawnFloatingEmojis(el.fxLayer, pick, 6 + Math.floor(Math.random() * 7));
      if (state.confetti && Math.random() > 0.35) {
        state.confetti.burst(900, 28 + Math.floor(Math.random() * 22));
      }
    }, 11000);
  }

  function scheduleBalloonReplay(eventos) {
    if (!state.souAniversariante || !Array.isArray(eventos) || !eventos.length) return;
    const slice = eventos.slice(-12);
    slice.forEach((ev, i) => {
      window.setTimeout(() => spawnBalloonFromEvent(ev), 180 + i * 200);
    });
  }

  // ---------- Confete leve (canvas, sem libs) ----------
  class LightConfetti {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.pieces = [];
      this.running = false;
      this._boundResize = () => this.resize();
    }

    resize() {
      const c = this.canvas;
      c.width = window.innerWidth;
      c.height = window.innerHeight;
    }

    burst(durationMs = 1400, count = 55) {
      this.resize();
      window.addEventListener("resize", this._boundResize);
      this.pieces = [];
      for (let i = 0; i < count; i++) {
        this.pieces.push({
          x: Math.random() * this.canvas.width,
          y: -20 - Math.random() * this.canvas.height * 0.4,
          w: 4 + Math.random() * 5,
          h: 6 + Math.random() * 9,
          vy: 2 + Math.random() * 4,
          vx: (Math.random() - 0.5) * 3,
          rot: Math.random() * Math.PI,
          vr: (Math.random() - 0.5) * 0.2,
          hue: 260 + Math.random() * 80,
        });
      }
      const end = performance.now() + durationMs;
      this.running = true;
      const loop = (now) => {
        if (!this.running) return;
        this._frame();
        if (now < end) requestAnimationFrame(loop);
        else this.stop();
      };
      requestAnimationFrame(loop);
    }

    _frame() {
      const { ctx, canvas, pieces } = this;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (const p of pieces) {
        p.y += p.vy;
        p.x += p.vx;
        p.rot += p.vr;
        ctx.save();
        ctx.translate(p.x, p.y);
        ctx.rotate(p.rot);
        ctx.fillStyle = `hsla(${p.hue}, 85%, 62%, 0.85)`;
        ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
        ctx.restore();
      }
    }

    stop() {
      this.running = false;
      window.removeEventListener("resize", this._boundResize);
      if (this.ctx) this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    }
  }

  // ---------- Router hash: #/live/:id ----------
  function parseRoute() {
    const h = (location.hash || "#/").replace(/^#/, "");
    const m = h.match(/^\/live\/(\d+)/);
    if (m) return { name: "live", id: parseInt(m[1], 10) };
    return { name: "list" };
  }

  function navToList() {
    location.hash = "#/";
  }

  function navToLive(id) {
    location.hash = `#/live/${id}`;
  }

  // ---------- DOM refs (preenchidos no init) ----------
  const el = {};

  function cacheDom() {
    el.app = document.getElementById("app");
    el.viewList = document.getElementById("view-list");
    el.viewLive = document.getElementById("view-live");
    el.btnBack = document.getElementById("btn-back");
    el.anivGrid = document.getElementById("aniv-grid");
    el.listState = document.getElementById("list-state");
    el.mesSelect = document.getElementById("mes-select");
    el.livePhoto = document.getElementById("live-photo");
    el.liveName = document.getElementById("live-name");
    /* Deploys antigos usavam #live-age; manter compatível evita null em textContent */
    el.liveAcademia = document.getElementById("live-academia");
    el.liveAniversario =
      document.getElementById("live-aniversario") || document.getElementById("live-age");
    el.counterVal = document.getElementById("counter-val");
    el.btnParabens = document.getElementById("btn-parabens");
    el.liveAviso = document.getElementById("live-interacao-aviso");
    el.feedList = document.getElementById("feed-list");
    el.fxLayer = document.getElementById("fx-layer");
    el.confetti = document.getElementById("confetti-canvas");
    el.festaBg = document.getElementById("festa-bg");
    el.festaBalloons = document.getElementById("festa-balloons");
    el.liveActions = document.getElementById("live-actions");
  }

  let state = {
    mes: new Date().getMonth() + 1,
    refMesAno: "",
    liveId: null,
    sinceId: 0,
    pollTimer: null,
    lastParabensCount: 0,
    milestonesDone: new Set(),
    confetti: null,
    /** Regra de calendário: pode interagir (parabéns + reações) */
    podeEnviarParabens: false,
    /** Um parabéns por usuário/aluno/ref; reações não contam */
    usuarioJaEnviouParabens: false,
    msgInteracaoBloqueada: "",
    /** Próprio aluno na tela da própria festa: sem botões; balões + fundo festivo */
    souAniversariante: false,
    festivaTimer: null,
  };

  function setView(name) {
    if (el.viewList) el.viewList.classList.toggle("is-active", name === "list");
    if (el.viewLive) el.viewLive.classList.toggle("is-active", name === "live");
    if (el.btnBack) el.btnBack.hidden = name !== "live";

    // Botão "Voltar" do header é contextual:
    //   - na lista: volta para a página anterior (?next ou painel)
    //   - na live: volta para a lista interna
    const btnVoltar = document.getElementById("btn-voltar-painel");
    if (btnVoltar) {
      if (name === "live") {
        btnVoltar.dataset.modo = "lista";
        btnVoltar.setAttribute("href", "#/");
        btnVoltar.title = "Voltar para a lista";
      } else {
        btnVoltar.dataset.modo = "fora";
        const def = btnVoltar.dataset.defaultBack || "/";
        btnVoltar.setAttribute("href", def);
        btnVoltar.title = "Voltar";
      }
    }
  }

  function applyInteracaoUI() {
    const msgDefault =
      "O botão é liberado a partir do dia do aniversário. Volte aqui na data ou após o dia. 🎂";
    const msgJaParabens =
      "Você já enviou parabéns. Reações seguem liberadas para interagir com o aniversariante.";
    const msgAniversariante =
      "Sua festa ao vivo: acompanhe parabéns e reações em tempo real. Aqui você só visualiza — quem manda carinho são seus colegas nas telas deles.";
    const av = el.liveAviso;
    const bp = el.btnParabens;
    const reacts = el.viewLive ? el.viewLive.querySelectorAll(".reaction-btn") : [];
    if (el.viewLive) {
      el.viewLive.classList.toggle("is-aniversariante", state.souAniversariante === true);
    }
    if (state.souAniversariante) {
      if (el.liveActions) el.liveActions.hidden = true;
      if (av) {
        av.hidden = false;
        av.textContent = msgAniversariante;
      }
      if (bp) {
        bp.disabled = true;
        bp.hidden = true;
      }
      reacts.forEach((b) => {
        b.disabled = true;
        b.hidden = true;
      });
      return;
    }
    if (el.liveActions) el.liveActions.hidden = false;
    if (bp) bp.hidden = false;
    reacts.forEach((b) => {
      b.hidden = false;
    });
    const podeReacoes = state.podeEnviarParabens;
    const podeParabensBtn = state.podeEnviarParabens && !state.usuarioJaEnviouParabens;
    /* Nunca escrever em nó ausente (HTML customizado / deploy parcial). */
    if (podeReacoes) {
      if (podeParabensBtn) {
        if (av) {
          av.hidden = true;
          av.textContent = "";
        }
        state.msgInteracaoBloqueada = "";
      } else {
        if (av) {
          av.hidden = false;
          av.textContent = msgJaParabens;
        }
      }
      if (bp) {
        bp.disabled = !podeParabensBtn;
        bp.title = state.usuarioJaEnviouParabens
          ? "Você já enviou parabéns para este aluno neste mês"
          : "";
      }
      reacts.forEach((b) => (b.disabled = false));
    } else {
      if (av) {
        av.hidden = false;
        av.textContent = (state.msgInteracaoBloqueada || "").trim() || msgDefault;
      }
      if (bp) {
        bp.disabled = true;
        bp.title = "";
      }
      reacts.forEach((b) => (b.disabled = true));
    }
  }

  function bumpCounter() {
    if (!el.counterVal) return;
    el.counterVal.classList.remove("is-bump");
    void el.counterVal.offsetWidth;
    el.counterVal.classList.add("is-bump");
  }

  function showMilestone(n) {
    const wrap = document.createElement("div");
    wrap.className = "milestone-flash";
    wrap.innerHTML = `<div class="milestone-card"><h3>${n} parabéns! 🎊</h3><p>A turma tá on fire</p></div>`;
    document.body.appendChild(wrap);
    window.setTimeout(() => wrap.remove(), 1200);
  }

  function scrollFeedBottom() {
    const box = el.feedList;
    if (!box) return;
    window.requestAnimationFrame(() => {
      box.scrollTop = box.scrollHeight;
    });
  }

  function appendFeedItem(ev, smooth = true) {
    if (!ev || ev.id == null || !el.feedList) return;
    const sid = String(ev.id);
    if (el.feedList.querySelector(`[data-id="${sid}"]`)) return;
    const row = document.createElement("div");
    row.className = "feed-item";
    row.dataset.id = sid;
    row.innerHTML = `<span>${escapeHtml(ev.texto)}</span><time datetime="${escapeHtml(
      ev.criado_em || ""
    )}">${escapeHtml(formatDateTimeBR(ev.criado_em))}</time>`;
    el.feedList.appendChild(row);
    if (smooth) scrollFeedBottom();
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /** API envia `YYYY-MM-DD HH:MM:SS` (MySQL) — exibe DD/MM/AAAA HH:MM:SS */
  function formatDateTimeBR(s) {
    const raw = String(s || "").trim();
    if (!raw) return "";
    const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/);
    if (m) return `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}:${m[6]}`;
    const d = new Date(raw.replace(" ", "T"));
    if (Number.isNaN(d.getTime())) return raw;
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  function updateCounterDisplay(n, animate) {
    if (!el.counterVal) return;
    const prev = state.lastParabensCount;
    el.counterVal.textContent = String(n);
    if (animate && n > prev) bumpCounter();
    for (const m of MILESTONES) {
      if (n >= m && prev < m && !state.milestonesDone.has(m)) {
        state.milestonesDone.add(m);
        showMilestone(m);
        state.confetti && state.confetti.burst(1800, 90);
        spawnFloatingEmojis(el.fxLayer, "🎉", 22);
      }
    }
    state.lastParabensCount = n;
  }

  async function loadList() {
    if (!el.listState || !el.anivGrid || !el.mesSelect) return;
    el.listState.innerHTML = '<div class="loader"></div>';
    el.anivGrid.innerHTML = "";
    try {
      const mes = parseInt(el.mesSelect.value, 10) || state.mes;
      const data = await fetchJson(`${API_BASE}/aniversariantes?mes=${mes}${anivAlunoEscopoQuery()}`);
      state.refMesAno = data.ref_mes_ano || state.refMesAno;
      const itens = data.itens || [];
      el.listState.innerHTML = "";
      if (!itens.length) {
        el.listState.innerHTML =
          '<p class="state-msg">Nenhum aniversariante neste mês no seu escopo.</p>';
        return;
      }
      const hoje = new Date();
      const hojeStr = `${String(hoje.getDate()).padStart(2, "0")}/${String(hoje.getMonth() + 1).padStart(2, "0")}`;
      const frag = document.createDocumentFragment();
      for (const a of itens) {
        const card = document.createElement("article");
        card.className = "aniv-card";
        const anivTxt = (a.aniversario_dia_mes || "").trim();
        const ehHoje = anivTxt && anivTxt.slice(0, 5) === hojeStr;
        const podeParabens = a.pode_enviar_parabens === true;
        if (ehHoje) card.classList.add("is-hoje");
        else if (podeParabens) card.classList.add("is-passado");
        const img = a.foto_url
          ? `<img class="aniv-avatar" src="${escapeHtml(a.foto_url)}" alt="" loading="lazy">`
          : `<div class="aniv-avatar aniv-avatar--cake">🎂</div>`;
        const meta = anivTxt
          ? `🎂 ${escapeHtml(anivTxt)}`
          : "Aniversariante do mês";
        let badge = "";
        if (ehHoje) badge = `<span class="badge-hoje">Hoje</span>`;
        else if (podeParabens) badge = `<span class="badge-passado">Já passou</span>`;
        let btnLabel, btnClass = "", btnDisabled = "", btnTitle = "";
        if (ehHoje) {
          btnLabel = "Parabéns 🎉";
        } else if (podeParabens) {
          btnLabel = "Mandar parabéns";
        } else {
          btnLabel = "Aguarde o dia";
          btnClass = " is-disabled";
          btnDisabled = " disabled";
          btnTitle = ' title="Disponível a partir do dia do aniversário"';
        }
        const btn = `<button type="button" class="btn-primary btn-open-live${btnClass}" data-id="${a.id}"${btnDisabled}${btnTitle}>${btnLabel}</button>`;
        card.innerHTML = `
          <div class="aniv-avatar-wrap">${img}</div>
          <div class="aniv-info">
            <h2 class="aniv-name">${escapeHtml(a.nome)} ${badge}</h2>
            <p class="aniv-meta">${meta}</p>
          </div>
          ${btn}
        `;
        frag.appendChild(card);
      }
      el.anivGrid.appendChild(frag);
      el.anivGrid.querySelectorAll(".btn-open-live:not(.is-disabled)").forEach((btn) => {
        btn.addEventListener("click", () => navToLive(parseInt(btn.dataset.id, 10)));
      });
    } catch (e) {
      el.listState.innerHTML = `<p class="state-msg error">${escapeHtml(e.message)}</p>`;
    }
  }

  async function loadLive(alunoId) {
    if (!el.feedList) return;
    stopFestivaAmbient();
    state.souAniversariante = false;
    el.feedList.innerHTML = "";
    state.sinceId = 0;
    state.lastParabensCount = 0;
    state.milestonesDone = new Set();
    const ref = state.refMesAno || defaultRef();
    try {
      const data = await fetchJson(
        `${API_BASE}/aniversariante/${alunoId}?ref_mes_ano=${encodeURIComponent(ref)}`
      );
      const al = data.aluno;
      if (!al || typeof al !== "object") {
        throw new Error((data && data.msg) || "Resposta sem dados do aniversariante.");
      }
      state.souAniversariante = data.sou_aniversariante === true;
      state.podeEnviarParabens = data.pode_enviar_parabens === true;
      state.usuarioJaEnviouParabens = data.usuario_ja_enviou_parabens === true;
      state.msgInteracaoBloqueada = data.msg_interacao_bloqueada || "";
      state.sinceId = Math.max(
        0,
        ...(data.eventos || []).map((x) => x.id || 0)
      );
      if (el.livePhoto) {
        el.livePhoto.src = al.foto_url || "";
        el.livePhoto.classList.toggle("is-pulse", !!al.foto_url);
        el.livePhoto.alt = al.nome || "";
      }
      if (el.liveName) el.liveName.textContent = al.nome || "";
      const acNome = (al.academia_nome || "").trim();
      if (el.liveAcademia) {
        el.liveAcademia.textContent = acNome || "";
      }
      const adm = (al.aniversario_dia_mes || "").trim();
      if (el.liveAniversario) {
        el.liveAniversario.textContent = adm ? `Aniversário: ${adm}` : "";
      }
      const totalP = data.total_parabens || 0;
      for (const m of MILESTONES) {
        if (totalP >= m) state.milestonesDone.add(m);
      }
      state.lastParabensCount = 0;
      updateCounterDisplay(totalP, false);
      for (const ev of data.eventos || []) {
        appendFeedItem(ev, false);
      }
      scrollFeedBottom();
      applyInteracaoUI();
      if (state.souAniversariante) {
        startFestivaAmbient();
        scheduleBalloonReplay(data.eventos || []);
      }
      startPoll(alunoId, ref);
    } catch (e) {
      el.feedList.innerHTML = `<p class="state-msg error">${escapeHtml(e.message)}</p>`;
    }
  }

  function defaultRef() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  }

  function stopPoll() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  function startPoll(alunoId, ref) {
    stopPoll();
    state.pollTimer = window.setInterval(async () => {
      try {
        const data = await fetchJson(
          `${API_BASE}/aniversariante/${alunoId}/feed?ref_mes_ano=${encodeURIComponent(
            ref
          )}&since_id=${state.sinceId}`
        );
        updateCounterDisplay(data.total_parabens, true);
        if (typeof data.pode_enviar_parabens === "boolean") {
          state.podeEnviarParabens = data.pode_enviar_parabens;
        }
        if (typeof data.usuario_ja_enviou_parabens === "boolean") {
          state.usuarioJaEnviouParabens = data.usuario_ja_enviou_parabens;
        }
        if (typeof data.sou_aniversariante === "boolean") {
          state.souAniversariante = data.sou_aniversariante;
        }
        if (
          typeof data.pode_enviar_parabens === "boolean" ||
          typeof data.usuario_ja_enviou_parabens === "boolean" ||
          typeof data.sou_aniversariante === "boolean"
        ) {
          applyInteracaoUI();
        }
        let maxId = state.sinceId;
        for (const ev of data.eventos || []) {
          if (ev.id > state.sinceId) {
            appendFeedItem(ev);
            if (state.souAniversariante) spawnBalloonFromEvent(ev);
            maxId = Math.max(maxId, ev.id);
          }
        }
        state.sinceId = maxId;
      } catch {
        /* silencioso no poll */
      }
    }, POLL_MS);
  }

  async function postAcao(alunoId, acao) {
    const ref = state.refMesAno || defaultRef();
    const body = { aluno_id: alunoId, acao, ref_mes_ano: ref };
    return fetchJson(`${API_BASE}/parabens`, { method: "POST", body: JSON.stringify(body) });
  }

  const REACTION_MAP = {
    "reaction-heart": { acao: "heart", emoji: "❤️" },
    "reaction-cake": { acao: "cake", emoji: "🎂" },
    "reaction-party": { acao: "party", emoji: "🥳" },
    "reaction-clap": { acao: "clap", emoji: "👏" },
  };

  async function runLiveAction(alunoId, acao, emojiFx) {
    if (!el.viewLive) return;
    if (state.souAniversariante) return;
    if (!state.podeEnviarParabens) {
      alert(
        "Só é possível enviar parabéns e reações a partir do dia do aniversário (no mês/ano da lista)."
      );
      return;
    }
    if (acao === "parabens" && state.usuarioJaEnviouParabens) {
      alert("Você já enviou parabéns para este aniversariante neste mês.");
      return;
    }
    const bp = el.btnParabens;
    const reacts = el.viewLive.querySelectorAll(".reaction-btn");
    if (bp) bp.disabled = true;
    reacts.forEach((b) => (b.disabled = true));
    try {
      const data = await postAcao(alunoId, acao);
      if (acao === "parabens") state.usuarioJaEnviouParabens = true;
      if (data.evento && data.evento.id > state.sinceId) {
        appendFeedItem(data.evento);
        state.sinceId = data.evento.id;
      }
      updateCounterDisplay(data.total_parabens, true);
      spawnFloatingEmojis(el.fxLayer, emojiFx, acao === "parabens" ? 16 : 10);
      if (acao === "parabens") state.confetti && state.confetti.burst(1200, 60);
    } catch (e) {
      alert(e.message || "Não foi possível enviar.");
    } finally {
      applyInteracaoUI();
    }
  }

  /** Um único listener (evita duplicar handlers ao trocar de rota). */
  function bindLiveDelegation() {
    if (state._delegationBound || !el.viewLive) return;
    state._delegationBound = true;
    el.viewLive.addEventListener("click", (e) => {
      const id = state.liveId;
      if (!id) return;
      const t = e.target;
      if (t.id === "btn-parabens") {
        e.preventDefault();
        runLiveAction(id, "parabens", "🎉");
        return;
      }
      const btn = t.closest(".reaction-btn");
      if (!btn || !el.viewLive.contains(btn)) return;
      const cfg = REACTION_MAP[btn.id];
      if (cfg) runLiveAction(id, cfg.acao, cfg.emoji);
    });
  }

  function onRoute() {
    const r = parseRoute();
    stopPoll();
    if (r.name === "list") {
      setView("list");
      state.liveId = null;
      stopFestivaAmbient();
      loadList();
    } else {
      setView("live");
      state.liveId = r.id;
      loadLive(r.id);
    }
  }

  function init() {
    cacheDom();
    if (!el.mesSelect || !el.viewList || !el.viewLive) {
      console.error(
        "[Aniv live] HTML incompleto: exigidos #mes-select, #view-list e #view-live."
      );
      return;
    }
    state.confetti = el.confetti ? new LightConfetti(el.confetti) : null;

    const d = new Date();
    el.mesSelect.value = String(d.getMonth() + 1);
    el.mesSelect.addEventListener("change", () => {
      state.mes = parseInt(el.mesSelect.value, 10);
      if (parseRoute().name === "list") loadList();
    });

    if (el.btnBack) el.btnBack.addEventListener("click", navToList);
    bindLiveDelegation();

    window.addEventListener("hashchange", onRoute);

    onRoute();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // API pública mínima para testes / extensões
  window.AnivLive = {
    spawnFloatingEmojis,
    API_BASE,
  };
})();
