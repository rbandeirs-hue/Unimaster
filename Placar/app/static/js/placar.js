/* =============================================================
   Placar Público — polling do estado da mesa
   ============================================================= */

const STATUS_LABEL = {
  idle:    'Aguardando',
  running: 'Em andamento',
  paused:  'Pausado',
  golden:  'Golden Score',
  done:    'Encerrada',
};

const OSAEKOMI_WAZARI_SEG = 10;
const OSAEKOMI_IPPON_SEG = 20;

function _formatOsaekomiClock(seg) {
  const s = Math.max(0, seg | 0);
  const mm = String(Math.floor(s / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

const MOTIVO_LABEL = {
  ippon:           'IPPON',
  wazari_x2:       '2 WAZARIS',
  hansoku:         'HANSOKU-MAKE',
  pontos:          'POR TEMPO (CONTAGEM)',
  golden:          'GOLDEN SCORE',
  wo:              'W.O.',
  manual:          '',
  resultado_salvo: '',
};

let _vencedorMostrado = false;
/** Em modo /placar/categoria/:id, detecta troca de luta para limpar overlay de vencedor */
let _ultimaMetaLutaId =
  LUTA_ID !== null && LUTA_ID !== undefined ? Number(LUTA_ID) : null;
if (Number.isNaN(_ultimaMetaLutaId)) _ultimaMetaLutaId = null;

function _pollUrl() {
  if (typeof PLACAR_AVULSO !== 'undefined' && PLACAR_AVULSO) {
    return `/placar/estado/avulso/${PLACAR_AVULSO}`;
  }
  return CATEGORIA_ID
    ? `/placar/estado/categoria/${CATEGORIA_ID}`
    : `/placar/estado/${LUTA_ID}`;
}

// ── Init ──────────────────────────────────────────────────────
document.getElementById('p-nome-azul').textContent   = ATLETA.azul.nome;
document.getElementById('p-club-azul') && (document.getElementById('p-club-azul').textContent = ATLETA.azul.club);
document.getElementById('p-nome-branco').textContent = ATLETA.branco.nome;

setInterval(poll, 900);
poll();

// ── Poll ──────────────────────────────────────────────────────
async function poll() {
  try {
    if (
      CATEGORIA_ID == null &&
      LUTA_ID == null &&
      !(typeof PLACAR_AVULSO !== 'undefined' && PLACAR_AVULSO)
    ) {
      return;
    }
    const r = await fetch(_pollUrl());
    if (!r.ok) return;
    render(await r.json());
  } catch (_) {}
}

function aplicarMeta(meta) {
  if (!meta) return;
  const fe = document.getElementById('p-header-fase');
  const le = document.getElementById('p-header-luta');
  if (fe && meta.fase != null) {
    fe.textContent = meta.fase ? String(meta.fase).replace(/_/g, ' ').toUpperCase() : '—';
  }
  if (le) {
    if (meta.numero_luta != null) {
      le.textContent = 'Luta ' + meta.numero_luta;
    } else if (meta.luta_id == null) {
      le.textContent = 'Luta —';
    }
  }
  const lidRaw = meta.luta_id;
  const lid =
    lidRaw !== null && lidRaw !== undefined && lidRaw !== ''
      ? Number(lidRaw)
      : null;
  const lidOk = lid != null && !Number.isNaN(lid);
  if (lidOk && lid !== _ultimaMetaLutaId) {
    if (_ultimaMetaLutaId != null) {
      _vencedorMostrado = false;
      const ov = document.getElementById('p-overlay');
      if (ov) ov.hidden = true;
    }
    _ultimaMetaLutaId = lid;
  }
}

/** Garante overlay mesmo se vencedor/motivo vierem ausentes no JSON (ex.: round-trip / cache). */
function inferirVencedor(dados) {
  if (dados.vencedor === 'azul' || dados.vencedor === 'branco') {
    return dados.vencedor;
  }
  const a = dados.azul;
  const b = dados.branco;
  if (!a || !b) return dados.vencedor;
  const ia = a.ippon | 0;
  const ib = b.ippon | 0;
  if (ia >= 1 && ib < 1) return 'azul';
  if (ib >= 1 && ia < 1) return 'branco';
  const sa = a.shido | 0;
  const sb = b.shido | 0;
  if (sa >= 3 && sb < 3) return 'branco';
  if (sb >= 3 && sa < 3) return 'azul';
  return dados.vencedor;
}

function inferirMotivo(dados, venc) {
  if (dados.motivo) return dados.motivo;
  if (!venc) return '';
  const a = dados.azul;
  const b = dados.branco;
  if (!a || !b) return '';
  if (venc === 'azul' && (a.ippon | 0) >= 1) return 'ippon';
  if (venc === 'branco' && (b.ippon | 0) >= 1) return 'ippon';
  if (venc === 'branco' && (a.shido | 0) >= 3) return 'hansoku';
  if (venc === 'azul' && (b.shido | 0) >= 3) return 'hansoku';
  return '';
}

// ── Render ────────────────────────────────────────────────────
function render(dados) {
  if (!dados) {
    return;
  }

  if (dados.aguardando_mesa) {
    aplicarMeta(dados.meta);
    document.getElementById('p-timer').textContent  = '--:--';
    document.getElementById('p-timer').className    = 'sb-timer idle';
    document.getElementById('p-status').textContent = 'Aguardando mesa';
    document.getElementById('p-status').className   = 'sb-status';
    document.getElementById('p-nome-azul').textContent   = '—';
    document.getElementById('p-nome-branco').textContent = '—';
    const ca = document.getElementById('p-club-azul');
    const cb = document.getElementById('p-club-branco');
    if (ca) ca.textContent = '';
    if (cb) cb.textContent = '';
    renderOsaekomi(null);
    for (const lado of ['azul', 'branco']) {
      renderLado(lado, { ippon: 0, wazari: 0, yuko: 0, shido: 0 }, null);
    }
    return;
  }

  aplicarMeta(dados.meta);

  if (!dados.status) {
    document.getElementById('p-timer').textContent  = '--:--';
    document.getElementById('p-timer').className    = 'sb-timer idle';
    document.getElementById('p-status').textContent = 'Aguardando';
    document.getElementById('p-status').className   = 'sb-status';
    renderOsaekomi(null);
    return;
  }

  const { status, timer, osaekomi } = dados;
  const z = { ippon: 0, wazari: 0, yuko: 0, shido: 0 };
  const azul = dados.azul || z;
  const branco = dados.branco || z;
  const vencedor = inferirVencedor(dados);
  const motivo = inferirMotivo(dados, vencedor) || dados.motivo || '';

  if (dados.nomes) {
    document.getElementById('p-nome-azul').textContent   = dados.nomes.azul   || ATLETA.azul.nome;
    document.getElementById('p-nome-branco').textContent = dados.nomes.branco || ATLETA.branco.nome;
  }

  renderLado('azul',   azul,   vencedor);
  renderLado('branco', branco, vencedor);
  renderTimer(timer, status);
  renderOsaekomi(osaekomi);

  const stEl = document.getElementById('p-status');
  stEl.textContent = STATUS_LABEL[status] || status;
  stEl.className   = 'sb-status ' + (status || '');

  if (status === 'done' && !_vencedorMostrado) {
    _vencedorMostrado = true;
    mostrarVencedor(vencedor, motivo, dados);
  }
}

function renderLado(lado, s, vencedor) {
  if (!s) return;

  setTec(`p-ippon-${lado}`, s.ippon, 0);
  setTec(`p-wazari-${lado}`, s.wazari, 0);
  setTec(`p-yuko-${lado}`, s.yuko || 0, 0);

  // Shidos
  const prefix = lado === 'azul' ? 'psa' : 'psb';
  for (let i = 0; i < 3; i++) {
    const dot = document.getElementById(`${prefix}${i}`);
    const ativo = i < s.shido;
    dot.textContent = ativo ? '●' : '○';
    dot.className   = 'sb-sh-dot' + (ativo ? (s.shido >= 3 ? ' hansoku' : ' ativo') : '');
  }
}

function setTec(id, val, _unused) {
  const el = document.getElementById(id);
  if (!el) return;
  const prev = parseInt(el.textContent, 10);
  el.textContent = val;
  if (val !== prev) bump(el);
}

function renderOsaekomi(osk) {
  const wrap = document.getElementById('p-osk-wrap');
  const lbl = document.getElementById('p-osk-lbl');
  const seg = document.getElementById('p-osk-seg');
  const meta = document.getElementById('p-osk-meta');
  if (!wrap || !lbl || !seg) return;

  if (osk && osk.lado && osk.ativo) {
    const s = osk.segundos ?? 0;
    wrap.hidden = false;
    wrap.className = 'sb-osk sb-osk--' + osk.lado;
    lbl.textContent = osk.lado === 'azul' ? 'Osaekomi — Azul' : 'Osaekomi — Branco';
    seg.textContent = _formatOsaekomiClock(s);
    if (meta) {
      if (osk.pausado) {
        meta.textContent = 'Tempo de imobilização pausado';
      } else if (s < OSAEKOMI_WAZARI_SEG) {
        meta.textContent = `Wazari em ${OSAEKOMI_WAZARI_SEG - s}s · Ippon em ${OSAEKOMI_IPPON_SEG - s}s`;
      } else if (s < OSAEKOMI_IPPON_SEG) {
        meta.textContent = `Ippon em ${OSAEKOMI_IPPON_SEG - s}s`;
      } else {
        meta.textContent = '';
      }
    }
    if (s >= OSAEKOMI_WAZARI_SEG) seg.classList.add('sb-osk-urgente');
    else seg.classList.remove('sb-osk-urgente');
  } else {
    wrap.hidden = true;
    seg.classList.remove('sb-osk-urgente');
    if (meta) meta.textContent = '';
  }
}

function renderTimer(timer, status) {
  if (!timer) return;
  const el = document.getElementById('p-timer');

  if (timer.golden) {
    const mm = String(Math.floor(timer.extra / 60)).padStart(2, '0');
    const ss = String(timer.extra % 60).padStart(2, '0');
    el.textContent = `+${mm}:${ss}`;
    el.className   = 'sb-timer golden';
  } else {
    const t =
      timer.restante ??
      timer.duracaoRegulamento ??
      DURACAO;
    const mm = String(Math.floor(t / 60)).padStart(2, '0');
    const ss = String(t % 60).padStart(2, '0');
    el.textContent = `${mm}:${ss}`;
    el.className   = 'sb-timer' + (
      status === 'idle'                    ? ' idle'    :
      status === 'running' && t <= 30      ? ' urgente' : ''
    );
  }
}

// ── Overlay vencedor ──────────────────────────────────────────
function mostrarVencedor(vencedor, motivo, dados) {
  let nomeVenc = '—';
  if (vencedor === 'azul') {
    nomeVenc = dados.nomes?.azul || ATLETA.azul.nome || '—';
  }
  if (vencedor === 'branco') {
    nomeVenc = dados.nomes?.branco || ATLETA.branco.nome || '—';
  }

  document.getElementById('po-nome').textContent   = nomeVenc;
  let metodoLinha = Object.prototype.hasOwnProperty.call(MOTIVO_LABEL, motivo)
    ? MOTIVO_LABEL[motivo]
    : null;
  if (metodoLinha === '' || metodoLinha == null) {
    if (motivo === 'resultado_salvo') metodoLinha = '';
    else if (motivo) metodoLinha = String(motivo).replace(/_/g, ' ').toUpperCase();
    else metodoLinha = '';
  }
  document.getElementById('po-metodo').textContent = metodoLinha;
  document.getElementById('p-overlay').hidden = false;
}

// ── Utils ─────────────────────────────────────────────────────
function bump(el) {
  el.classList.remove('bump');
  void el.offsetWidth;
  el.classList.add('bump');
  setTimeout(() => el.classList.remove('bump'), 200);
}
