/* =============================================================
   Mesa de Controle — Sistema de Judô
   Máquina de estado da luta: idle → running → paused → done
                                          ↘ golden ↗
   ============================================================= */

// ── Estado ────────────────────────────────────────────────────

const OSAEKOMI_WAZARI_SEG = 10;
const OSAEKOMI_IPPON_SEG = 20;

const E = {
  status: 'idle',   // idle | running | paused | golden | done
  timer: {
    restante: DURACAO,
    duracaoRegulamento: DURACAO,
    extra: 0,         // segundos no golden score
    golden: false,
    tid: null,
  },
  azul:   { ippon: 0, wazari: 0, yuko: 0, shido: 0 },
  branco: { ippon: 0, wazari: 0, yuko: 0, shido: 0 },
  historico: [],     // stack para desfazer
  vencedor: null,
  motivo: null,
  osaekomi: {
    preparacao: null, // 'azul' | 'branco' — lado escolhido antes de iniciar
    lado: null,       // lado em contagem (enquanto tid ativo)
    segundos: 0,
    tid: null,
    wazari_dado: false,
  },
};

const MOTIVO_LABEL = {
  ippon:     'por Ippon',
  wazari_x2: 'por 2 Wazaris (equivalente a Ippon)',
  hansoku:   'por Hansoku-make (3 Shidos)',
  pontos:    'por contagem ao final do tempo',
  golden:    'no Golden Score',
  wo:        'por W.O.',
  manual:    'por decisão',
  resultado_salvo: 'resultado já registrado (correção)',
};

const CORRECAO_RESULTADO =
  typeof LUTA_FINALIZADA !== 'undefined' &&
  !!LUTA_FINALIZADA &&
  !!RESULTADO_MESA;

function _mesaAvulsoAtiva() {
  return typeof MESA_AVULSO !== 'undefined' && !!MESA_AVULSO;
}

function _placarEstadoPostUrl() {
  if (_mesaAvulsoAtiva()) {
    return `/placar/estado/avulso/${MESA_AVULSO}`;
  }
  return `/placar/estado/${LUTA.id}`;
}

function _podeAjustarContagem() {
  if (CORRECAO_RESULTADO && E.status === 'done') {
    return true;
  }
  return E.status !== 'done' && E.status !== 'idle';
}

// ── Timer ─────────────────────────────────────────────────────

function toggleTimer() {
  if (E.status === 'done') return;

  if (E.status === 'idle' || E.status === 'paused') {
    E.status = E.timer.golden ? 'golden' : 'running';
    E.timer.tid = setInterval(_tick, 1000);
  } else {
    clearInterval(E.timer.tid);
    E.timer.tid = null;
    E.status = 'paused';
  }

  _renderTimer();
  _atualizarBtnTimer();
  _atualizarInputsDuracao();
  _renderOsaekomi();
  _syncPlacar();
}

function _tick() {
  if (E.timer.golden) {
    E.timer.extra++;
  } else {
    E.timer.restante = Math.max(0, E.timer.restante - 1);

    if (E.timer.restante === 0) {
      clearInterval(E.timer.tid);
      E.timer.tid = null;
      _onTempoEsgotado();
      return;
    }
  }
  _renderTimer();
  _syncPlacar();
}

function _onTempoEsgotado() {
  const v = _vantagem();

  if (v !== 0) {
    _encerrar(v > 0 ? 'azul' : 'branco', 'pontos');
  } else {
    // empate → Golden Score disponível
    E.status = 'paused';
    E.timer.golden = true;
    document.getElementById('btn-golden').disabled = false;
    document.getElementById('timer-label').textContent = 'Golden Score disponível';
    document.getElementById('timer-display').className = 'timer golden';
    _atualizarBtnTimer();
  }
}

function iniciarGolden() {
  if (!E.timer.golden || E.status === 'done') return;
  E.status = 'golden';
  E.timer.tid = setInterval(_tick, 1000);
  document.getElementById('btn-golden').disabled = true;
  _atualizarBtnTimer();
  _atualizarInputsDuracao();
  _renderTimer();
  _renderOsaekomi();
  _syncPlacar();
}

// ── Osaekomi (10s Wazari / 20s Ippon — IJF) ───────────────────

function _pararOsaekomi() {
  const o = E.osaekomi;
  if (o.tid) {
    clearInterval(o.tid);
    o.tid = null;
  }
  o.lado = null;
  o.segundos = 0;
  o.wazari_dado = false;
  /* preparacao mantida para reiniciar no mesmo lado */
}

function _tickOsaekomi() {
  if (E.status === 'done') {
    _pararOsaekomi();
    _renderOsaekomi();
    return;
  }
  /* IJF: tempo de imobilização só avança com o cronômetro da luta em jogo (running/golden). */
  if (E.status !== 'running' && E.status !== 'golden') {
    _renderOsaekomi();
    _syncPlacar();
    return;
  }
  const o = E.osaekomi;
  if (!o.lado) return;

  o.segundos += 1;

  if (o.segundos >= OSAEKOMI_IPPON_SEG) {
    const L = o.lado;
    const tinhaWazariDaImobilizacao = o.wazari_dado;
    const prev = _clonePartida();
    _pararOsaekomi();
    if (tinhaWazariDaImobilizacao) {
      E[L].wazari = Math.max(0, E[L].wazari - 1);
    }
    E[L].ippon += 1;
    E.historico.push({ kind: 'snap', prev });
    _animarPlacar(L);
    _checarFim();
    _renderPlacar();
    _renderOsaekomi();
    _syncPlacar();
    return;
  }

  if (o.segundos === OSAEKOMI_WAZARI_SEG && !o.wazari_dado) {
    o.wazari_dado = true;
    const prev = _clonePartida();
    E[o.lado].wazari += 1;
    _aplicarRegraDoisWazaris(o.lado);
    E.historico.push({ kind: 'snap', prev });
    _animarPlacar(o.lado);
    _checarFim();
    _renderPlacar();
  }

  _renderOsaekomi();
  _syncPlacar();
}

/** Escolhe quem está em imobilização (ainda sem contar o tempo). */
function selecionarLadoOsaekomi(lado) {
  if (E.status === 'done') return;
  const o = E.osaekomi;
  if (o.tid) return;

  o.preparacao = lado;
  _renderOsaekomi();
  _syncPlacar();
}

/** Inicia o cronômetro de Osaekomi (10s / 20s). Exige luta em andamento e lado escolhido. */
function iniciarContagemOsaekomi() {
  if (E.status === 'done') return;
  if (E.status !== 'running' && E.status !== 'golden') {
    alert('Inicie ou retome o cronômetro da luta antes do Osaekomi.');
    return;
  }
  const o = E.osaekomi;
  if (o.tid) return;
  if (!o.preparacao) {
    alert('Selecione Azul ou Branco (quem está em imobilização).');
    return;
  }

  o.lado = o.preparacao;
  o.segundos = 0;
  o.wazari_dado = false;
  o.tid = setInterval(_tickOsaekomi, 1000);
  _renderOsaekomi();
  _syncPlacar();
}

/** Encerra a contagem de Osaekomi (toketa / saiu da imobilização). */
function pararOsaekomi() {
  if (E.status === 'done') return;
  const o = E.osaekomi;
  if (!o.tid) return;
  _pararOsaekomi();
  _renderOsaekomi();
  _syncPlacar();
}

function _formatOsaekomiClock(seg) {
  const s = Math.max(0, seg | 0);
  const mm = String(Math.floor(s / 60)).padStart(2, '0');
  const ss = String(s % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

function _osaekomiLegendaProgresso(seg) {
  if (seg < OSAEKOMI_WAZARI_SEG) {
    return `Próximo: Wazari em ${OSAEKOMI_WAZARI_SEG - seg}s`;
  }
  if (seg < OSAEKOMI_IPPON_SEG) {
    return `Próximo: Ippon em ${OSAEKOMI_IPPON_SEG - seg}s`;
  }
  return '';
}

function _renderOsaekomi() {
  const o = E.osaekomi;
  const el = document.getElementById('osk-display');
  const meta = document.getElementById('osk-meta');
  if (el) el.textContent = _formatOsaekomiClock(o.segundos);

  if (meta) {
    const relogioParado = E.status !== 'running' && E.status !== 'golden';
    if (o.lado && o.tid && relogioParado) {
      meta.textContent = 'Imobilização pausada (retome o cronômetro da luta)';
    } else if (o.lado && o.tid) {
      meta.textContent = _osaekomiLegendaProgresso(o.segundos);
    } else if (o.preparacao && (E.status === 'running' || E.status === 'golden')) {
      const L = o.preparacao === 'azul' ? 'Azul' : 'Branco';
      meta.textContent = `Lado: ${L} — pressione «Iniciar contagem»`;
    } else {
      meta.textContent =
        '1) Escolha Azul ou Branco · 2) Iniciar contagem · 10s = Wazari · 20s = Ippon';
    }
  }

  const lutaEmJogo = E.status === 'running' || E.status === 'golden';
  const ba = document.getElementById('btn-osk-azul');
  const bb = document.getElementById('btn-osk-branco');
  const bi = document.getElementById('btn-osk-iniciar');
  const bp = document.getElementById('btn-osk-parar');

  if (ba) {
    ba.textContent = 'Azul';
    ba.classList.toggle(
      'ativo',
      o.preparacao === 'azul' || (o.lado === 'azul' && !!o.tid)
    );
    ba.disabled = E.status === 'done' || !!o.tid;
  }
  if (bb) {
    bb.textContent = 'Branco';
    bb.classList.toggle(
      'ativo',
      o.preparacao === 'branco' || (o.lado === 'branco' && !!o.tid)
    );
    bb.disabled = E.status === 'done' || !!o.tid;
  }
  if (bi) {
    bi.disabled =
      E.status === 'done' ||
      !!o.tid ||
      !o.preparacao ||
      !lutaEmJogo;
  }
  if (bp) {
    bp.disabled = E.status === 'done' || !o.tid;
  }
}

function _atualizarBtnTimer() {
  const btn = document.getElementById('btn-timer');

  if (E.status === 'running' || E.status === 'golden') {
    btn.textContent = '⏸ Pausar';
    btn.className   = 'btn-ctrl btn-ctrl--pause';
  } else {
    btn.textContent = E.status === 'idle' ? '▶ Iniciar' : '▶ Retomar';
    btn.className   = 'btn-ctrl btn-ctrl--start';
  }
}

// ── Contagem (I / W / Y / Shido) — sem pontuação agregada ─────

function _clonePartida() {
  return {
    azul: { ...E.azul },
    branco: { ...E.branco },
  };
}

/** Dois wazaris consecutivos na contagem viram 1 ippon (regra usual). */
function _aplicarRegraDoisWazaris(lado) {
  const s = E[lado];
  while (s.wazari >= 2) {
    s.wazari -= 2;
    s.ippon += 1;
  }
}

/**
 * Ajusta contagem diretamente (+1 / -1). Wazari: ao chegar em 2 vira Ippon.
 */
function ajustarScore(lado, tipo, delta) {
  if (!_podeAjustarContagem()) return;
  if (!delta) return;

  const s = E[lado];
  const prev = _clonePartida();

  if (tipo === 'shido') {
    const n = Math.max(0, Math.min(3, s.shido + delta));
    if (n === s.shido) return;
    s.shido = n;
  } else {
    const nv = s[tipo] + delta;
    if (nv < 0) return;
    s[tipo] = nv;
    if (tipo === 'wazari' && delta > 0) {
      _aplicarRegraDoisWazaris(lado);
    }
  }

  E.historico.push({ kind: 'snap', prev });
  _animarPlacar(lado);
  _checarFim();
  _renderPlacar();
  _syncPlacar();
}

/** Zera só a contagem daquele tipo (undo continua funcionando). */
function zerarScore(lado, tipo) {
  if (!_podeAjustarContagem()) return;
  const s = E[lado];
  const cur = tipo === 'shido' ? s.shido : s[tipo];
  if (!cur) return;

  const prev = _clonePartida();
  if (tipo === 'shido') {
    s.shido = 0;
  } else {
    s[tipo] = 0;
  }

  E.historico.push({ kind: 'snap', prev });
  _animarPlacar(lado);
  _checarFim();
  _renderPlacar();
  _syncPlacar();
}

function desfazer() {
  if (!E.historico.length) return;
  if (E.status === 'done' && !CORRECAO_RESULTADO) return;

  const u = E.historico.pop();
  if (u.kind === 'snap' && u.prev) {
    E.azul = { ...u.prev.azul };
    E.branco = { ...u.prev.branco };
    _renderPlacar();
    _syncPlacar();
  }
}

function _checarFim() {
  if (CORRECAO_RESULTADO) return;
  const a = E.azul, b = E.branco;

  if (a.ippon >= 1) {
    _encerrar('azul', 'ippon');
    return;
  }
  if (b.ippon >= 1) {
    _encerrar('branco', 'ippon');
    return;
  }
  if (a.shido >= 3) {
    _encerrar('branco', 'hansoku');
    return;
  }
  if (b.shido >= 3) {
    _encerrar('azul', 'hansoku');
    return;
  }

  if (E.timer.golden && E.status === 'golden') {
    const v = _vantagem();
    if (v !== 0) {
      _encerrar(v > 0 ? 'azul' : 'branco', 'golden');
    }
  }
}

/** Compara vantagem: Ippon > Wazari > Yuko (contagens). */
function _vantagem() {
  const a = E.azul,
    b = E.branco;
  if (a.ippon !== b.ippon) {
    return a.ippon > b.ippon ? 1 : -1;
  }
  if (a.wazari !== b.wazari) {
    return a.wazari > b.wazari ? 1 : -1;
  }
  if (a.yuko !== b.yuko) {
    return a.yuko > b.yuko ? 1 : -1;
  }
  return 0;
}

function _contagemZerada() {
  const a = E.azul,
    b = E.branco;
  return (
    !a.ippon &&
    !a.wazari &&
    !a.yuko &&
    !a.shido &&
    !b.ippon &&
    !b.wazari &&
    !b.yuko &&
    !b.shido
  );
}

function aplicarDuracaoMinutos() {
  if (E.status === 'done') {
    return;
  }
  if (E.status === 'running' || E.status === 'golden') {
    alert('Pause a luta para alterar a duração.');
    return;
  }
  if (E.timer.golden) {
    return;
  }
  const inp = document.getElementById('input-minutos');
  let m = parseInt(inp && inp.value, 10);
  if (Number.isNaN(m) || m < 1) {
    m = 1;
  }
  if (m > 45) {
    m = 45;
  }
  if (inp) {
    inp.value = m;
  }
  const seg = m * 60;
  E.timer.duracaoRegulamento = seg;
  E.timer.restante = seg;
  _renderTimer();
  _syncPlacar();
}

function _atualizarInputsDuracao() {
  const inp = document.getElementById('input-minutos');
  const btn = document.getElementById('btn-duracao');
  const bloq =
    E.status === 'done' || E.status === 'running' || E.status === 'golden';
  if (inp) {
    inp.disabled = bloq;
  }
  if (btn) {
    btn.disabled = bloq;
  }
}

// ── W.O. ──────────────────────────────────────────────────────

function registrarWO() {
  if (E.status === 'done') {
    if (CORRECAO_RESULTADO) {
      alert('Em modo correção use os botões de contagem ou «Trocar vencedor» no modal; W.O. não se aplica aqui.');
    }
    return;
  }

  _pararOsaekomi();

  // Pausa o timer se estiver rodando
  if (E.timer.tid) { clearInterval(E.timer.tid); E.timer.tid = null; }

  const escolha = confirm(
    'W.O. — Qual atleta não compareceu?\n\n' +
    'OK      → AZUL não compareceu  (Branco vence)\n' +
    'Cancelar → BRANCO não compareceu (Azul vence)'
  );

  // Manipula scores para o backend calcular corretamente
  if (escolha) {
    E.azul.shido = 3;   // azul perde
    _encerrar('branco', 'wo');
  } else {
    E.branco.shido = 3; // branco perde
    _encerrar('azul', 'wo');
  }
}

// ── Encerramento ──────────────────────────────────────────────

function _encerrar(vencedor, motivo) {
  _pararOsaekomi();
  clearInterval(E.timer.tid);
  E.timer.tid = null;
  E.status   = 'done';
  E.vencedor = vencedor;
  E.motivo   = motivo;

  // desabilita todos os botões de pontuação
  document
    .querySelectorAll(
      '.btn, .btn-ctrl, .btn-osk, .btn-osk-ctrl, .btn-counter, .btn-zerar'
    )
    .forEach(b => {
      if (!b.closest('.modal-box')) {
        b.disabled = true;
      }
    });

  _renderPlacar();
  _renderOsaekomi();
  _atualizarInputsDuracao();
  // Garante que o telão receba vencedor/motivo antes do modal (evita poll sem vitória por Ippon).
  _syncPlacar().finally(() => _mostrarModal());
}

function pedirConfirmacao() {
  if (CORRECAO_RESULTADO) {
    alert('Ajuste o placar e use «Revisar e salvar correção» nas ações.');
    return;
  }
  if (E.status === 'done') return;

  if (_contagemZerada()) {
    alert('Nenhuma contagem registrada.\nUse W.O. ou ajuste I / W / Y / Shido antes de encerrar.');
    return;
  }
  const v = _vantagem();
  if (v === 0) {
    alert('Empate nas contagens — inicie o Golden Score ou ajuste Ippon / Wazari / Yuko.');
    return;
  }

  _encerrar(v > 0 ? 'azul' : 'branco', 'manual');
}

// ── Modal ─────────────────────────────────────────────────────

function _mostrarModal() {
  const a = E.azul, b = E.branco;
  const nomeVencedor = LUTA[E.vencedor]?.nome || E.vencedor;
  const outro = E.vencedor === 'azul' ? 'branco' : 'azul';
  const nomeOutro = LUTA[outro]?.nome || outro;

  const tempoTotal =
    E.timer.duracaoRegulamento - E.timer.restante + E.timer.extra;
  const mm = String(Math.floor(tempoTotal / 60)).padStart(2, '0');
  const ss = String(tempoTotal % 60).padStart(2, '0');
  const tempoStr = `${mm}:${ss}${E.timer.golden ? ' (GS)' : ''}`;

  document.getElementById('modal-vencedor').textContent  = nomeVencedor;
  document.getElementById('modal-metodo').textContent    = MOTIVO_LABEL[E.motivo] || '';
  document.getElementById('modal-scores').innerHTML =
    `<b>Azul:</b>   I:${a.ippon} · W:${a.wazari} · Y:${a.yuko} · S:${a.shido}<br>
     <b>Branco:</b> I:${b.ippon} · W:${b.wazari} · Y:${b.yuko} · S:${b.shido}<br>
     <b>Tempo:</b>  ${tempoStr}<br>
     <small style="opacity:.75">Contagem: I / W / Y · 2 Wazari = Ippon · Osaekomi 10s/20s</small>`;

  const btnTroca = document.getElementById('modal-btn-trocar-vencedor');
  if (btnTroca) {
    btnTroca.textContent = `⇄ Vencedor errado? Declarar ${nomeOutro.toUpperCase()}`;
  }

  document.getElementById('modal').hidden = false;
}

/** Antes de salvar: troca quem será gravado como vencedor (e no telão). */
function trocarVencedorNoModal() {
  if (E.status !== 'done') return;
  E.vencedor = E.vencedor === 'azul' ? 'branco' : 'azul';
  _mostrarModal();
  _syncPlacar();
}

function cancelarModal() {
  if (CORRECAO_RESULTADO) {
    document.getElementById('modal').hidden = true;
    return;
  }
  if (!confirm('Cancelar o encerramento e retornar à luta?')) return;

  // restaura estado
  E.status   = 'paused';
  E.vencedor = null;
  E.motivo   = null;

  // reabilita botões de pontuação
  document
    .querySelectorAll(
      '.btn, .btn-ctrl, .btn-osk, .btn-osk-ctrl, .btn-counter, .btn-zerar'
    )
    .forEach(b => {
      b.disabled = false;
    });
  document.getElementById('btn-golden').disabled = !E.timer.golden;
  document.getElementById('modal').hidden = true;

  _renderOsaekomi();
  _atualizarBtnTimer();
  _atualizarInputsDuracao();
  _renderPlacar();
}

async function salvarResultado() {
  if (E.vencedor !== 'azul' && E.vencedor !== 'branco') {
    alert('Vencedor indefinido. Use «Trocar vencedor» ou cancele e ajuste a luta.');
    return;
  }
  if (_mesaAvulsoAtiva()) {
    document.getElementById('modal').hidden = true;
    return;
  }
  const a = E.azul, b = E.branco;
  const tempoTotal =
    E.timer.duracaoRegulamento - E.timer.restante + E.timer.extra;

  const body = {
    ippon_azul:    a.ippon,
    wazari_azul:   a.wazari,
    yuko_azul:     a.yuko,
    shido_azul:    a.shido,
    ippon_branco:  b.ippon,
    wazari_branco: b.wazari,
    yuko_branco:   b.yuko,
    shido_branco:  b.shido,
    tempo_luta:    tempoTotal,
    vencedor_lado: E.vencedor,
  };

  const method = CORRECAO_RESULTADO ? 'PUT' : 'POST';

  try {
    const resp = await fetch(`/api/lutas/${LUTA.id}/resultado`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      alert('Erro ao salvar: ' + (err.error || `HTTP ${resp.status}`));
      return;
    }

    window.location.href = `/bracket/${LUTA.categoria_id}`;
  } catch (e) {
    alert('Erro de conexão: ' + e.message);
  }
}

function abrirModalCorrecao() {
  if (!CORRECAO_RESULTADO) return;
  if (E.vencedor !== 'azul' && E.vencedor !== 'branco') {
    alert(
      'Não foi possível determinar o lado do vencedor salvo. Verifique os atletas na luta.'
    );
    return;
  }
  _mostrarModal();
}

function _mesaAplicarModoCorrecaoUI() {
  const t = document.getElementById('btn-timer');
  if (t) t.disabled = true;
  const g = document.getElementById('btn-golden');
  if (g) g.disabled = true;
  const btnConf = document.getElementById('modal-btn-confirmar');
  if (btnConf) btnConf.textContent = '✓ Salvar correção';
  const modalTitulo = document.getElementById('modal-titulo');
  if (modalTitulo) modalTitulo.textContent = 'Confirmar correção';
}

// ── Render ────────────────────────────────────────────────────

function _renderTimer() {
  const t = E.timer;
  const el = document.getElementById('timer-display');
  const lbl = document.getElementById('timer-label');

  if (t.golden) {
    const mm = String(Math.floor(t.extra / 60)).padStart(2, '0');
    const ss = String(t.extra % 60).padStart(2, '0');
    el.textContent = `+${mm}:${ss}`;
    el.className   = 'timer golden';
    lbl.textContent = '⚡ GOLDEN SCORE';
  } else {
    const mm = String(Math.floor(t.restante / 60)).padStart(2, '0');
    const ss = String(t.restante % 60).padStart(2, '0');
    el.textContent = `${mm}:${ss}`;
    el.className   = t.restante <= 30 && E.status === 'running' ? 'timer urgente' : 'timer';

    const statusMap = {
      idle: 'Aguardando', running: 'Em andamento',
      paused: 'Pausado', done: 'Encerrada',
    };
    lbl.textContent = statusMap[E.status] || '';
  }
}

function _renderPlacar() {
  for (const lado of ['azul', 'branco']) {
    const s = E[lado];
    for (const t of ['ippon', 'wazari', 'yuko']) {
      const el = document.getElementById(`c-${t}-${lado}`);
      if (el) {
        el.textContent = s[t];
      }
    }
    const sh = document.getElementById(`c-shido-${lado}`);
    if (sh) {
      sh.textContent = s.shido;
    }

    const prefixo = lado === 'azul' ? 'sa' : 'sb';
    for (let i = 0; i < 3; i++) {
      const dot = document.getElementById(`${prefixo}${i}`);
      if (!dot) {
        continue;
      }
      const ativo = i < s.shido;
      dot.textContent = ativo ? '●' : '○';
      dot.className =
        'shido-dot' + (ativo ? (s.shido >= 3 ? ' hansoku' : ' ativo') : '');
    }
  }
}

function _animarPlacar(lado) {
  const wrap = document.getElementById(`contadores-${lado}`);
  if (!wrap) {
    return;
  }
  wrap.classList.remove('bump');
  void wrap.offsetWidth;
  wrap.classList.add('bump');
  setTimeout(() => wrap.classList.remove('bump'), 200);
}

// ── Sync placar público ───────────────────────────────────────

async function _syncPlacar() {
  try {
    const resp = await fetch(_placarEstadoPostUrl(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        status:   E.status,
        timer:    {
          restante: E.timer.restante,
          golden: E.timer.golden,
          extra: E.timer.extra,
          duracaoRegulamento: E.timer.duracaoRegulamento,
        },
        azul:     { ippon: E.azul.ippon,   wazari: E.azul.wazari,   yuko: E.azul.yuko,   shido: E.azul.shido },
        branco:   { ippon: E.branco.ippon, wazari: E.branco.wazari, yuko: E.branco.yuko, shido: E.branco.shido },
        vencedor: E.vencedor,
        motivo:   E.motivo,
        nomes:    { azul: LUTA.azul.nome, branco: LUTA.branco.nome },
        osaekomi: E.osaekomi.lado && E.osaekomi.tid
          ? {
              lado: E.osaekomi.lado,
              segundos: E.osaekomi.segundos,
              ativo: true,
              pausado:
                E.status !== 'running' && E.status !== 'golden',
            }
          : null,
      }),
    });
    return resp.ok;
  } catch (_) {
    return false;
  }
}

// ── Init ──────────────────────────────────────────────────────

(function _mesaCarregarResultadoSalvo() {
  if (!CORRECAO_RESULTADO || !RESULTADO_MESA) return;
  const r = RESULTADO_MESA;
  E.azul = {
    ippon: +r.ippon_azul || 0,
    wazari: +r.wazari_azul || 0,
    yuko: +r.yuko_azul || 0,
    shido: +r.shido_azul || 0,
  };
  E.branco = {
    ippon: +r.ippon_branco || 0,
    wazari: +r.wazari_branco || 0,
    yuko: +r.yuko_branco || 0,
    shido: +r.shido_branco || 0,
  };
  const tl = r.tempo_luta != null ? Number(r.tempo_luta) : 0;
  const base = typeof DURACAO !== 'undefined' ? DURACAO : 240;
  E.timer.duracaoRegulamento = Math.max(base, tl);
  E.timer.restante = Math.max(0, E.timer.duracaoRegulamento - tl);
  E.timer.extra = 0;
  E.timer.golden = false;
  E.status = 'done';
  E.vencedor =
    VENCEDOR_LADO_INICIAL === 'azul' || VENCEDOR_LADO_INICIAL === 'branco'
      ? VENCEDOR_LADO_INICIAL
      : null;
  E.motivo = 'resultado_salvo';
  E.historico = [];
  _mesaAplicarModoCorrecaoUI();
})();

(function _mesaInit() {
  const inp = document.getElementById('input-minutos');
  if (inp) {
    inp.value = Math.max(1, Math.round(E.timer.duracaoRegulamento / 60));
  }
})();

(function _mesaAvulsoUiInit() {
  if (!_mesaAvulsoAtiva()) return;
  const b = document.getElementById('modal-btn-confirmar');
  if (b) b.textContent = '✓ OK — telão';
  const t = document.getElementById('modal-titulo');
  if (t) t.textContent = 'Encerramento (avulso)';
})();

/** Placar estável por categoria: marca esta luta como a exibida em /placar/categoria/<id> */
async function _registrarPlacarCategoria() {
  if (!LUTA.categoria_id) return;
  try {
    await fetch(`/placar/categoria/${LUTA.categoria_id}/placar-luta`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ luta_id: LUTA.id }),
    });
  } catch (_) {}
}
_registrarPlacarCategoria();

_renderTimer();
_renderPlacar();
_renderOsaekomi();
_atualizarInputsDuracao();
