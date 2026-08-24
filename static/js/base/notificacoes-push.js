/* =====================================================================
   Notificações in-app + Web Push
   =====================================================================
   Extraído do base.html. Os valores que vinham de Jinja (chave VAPID e as
   rotas de notificação) chegam por `window.UNIMASTER`, publicado pelo
   partial templates/components/_base_scripts.html — é o que permite este
   arquivo ser estático e cacheável.

   Push e notificações compartilham a mesma IIFE (`_pushDisponivel`,
   `_marcarBellInativo`): separar em dois arquivos quebraria o fechamento,
   então seguem juntos, como já estavam.
   ===================================================================== */
(function () {
  var CFG = (window.UNIMASTER || {});
  if (!CFG.urls) return;            // página sem as rotas: nada a fazer

/* ── Web Push — registro do Service Worker e subscribe ───── */
/* Preferir /sw.js (Flask envia Service-Worker-Allowed: /). Se 404 (proxy), cai em /static/sw.js. */
(function(){
  const _pushDisponivel =
    typeof navigator !== "undefined" &&
    "serviceWorker" in navigator &&
    typeof window.PushManager !== "undefined";

  const VAPID_PUBLIC_KEY = CFG.vapidPublicKey;

  async function obterRegistroPush() {
    try {
      const reg = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
      await reg.ready;
      return reg;
    } catch (e) {
      let reg = await navigator.serviceWorker.getRegistration();
      if (reg) {
        await reg.ready;
        return reg;
      }
      reg = await navigator.serviceWorker.register('/static/sw.js');
      await reg.ready;
      return reg;
    }
  }

  function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = window.atob(base64);
    return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
  }

  function csrfPushToken() {
    const m = document.querySelector('meta[name="csrf-token"]');
    return m ? (m.getAttribute('content') || '').trim() : '';
  }

  let _pushSubscribeAbort = null;

  async function atualizarEstadoVisualSino(reg) {
    try {
      if (Notification.permission === 'denied') {
        _marcarBellInativo();
        return;
      }
      if (Notification.permission !== 'granted') {
        _marcarBellInativo();
        return;
      }
      const sub = await reg.pushManager.getSubscription();
      if (!sub) {
        _marcarBellInativo();
        return;
      }
      const r = await enviarSubscription(sub);
      if (r && r.aborted) return;
      const still = await reg.pushManager.getSubscription();
      if (!still) {
        _marcarBellInativo();
        return;
      }
      if (r && r.ok) _marcarBellAtivo();
      else _marcarBellInativo();
    } catch (e) {
      _marcarBellInativo();
    }
  }

  async function registrarPush() {
    try {
      const reg = await obterRegistroPush();
      await atualizarEstadoVisualSino(reg);
    } catch (e) { /* silencioso */ }
  }

  async function desativarPushNoAparelho(reg, sub) {
    if (_pushSubscribeAbort) {
      try { _pushSubscribeAbort.abort(); } catch (_) {}
      _pushSubscribeAbort = null;
    }
    if (!csrfPushToken()) {
      mostrarToastPush('Token de segurança ausente. Recarregue a página.', 'danger');
      return;
    }
    const endpoint = sub.endpoint;
    try {
      await sub.unsubscribe();
    } catch (e) { /* continua para remover no servidor */ }
    const tok = csrfPushToken();
    const res = await fetch('/push/unsubscribe', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-CSRFToken': tok,
      },
      body: JSON.stringify({ endpoint: endpoint }),
    });
    if (!res.ok) {
      mostrarToastPush('Removido neste aparelho; aviso se o servidor não confirmou a remoção.', 'warning');
    } else {
      mostrarToastPush('Notificações desativadas neste aparelho.', 'info');
    }
    _marcarBellInativo();
  }

  let _pushToggleBusy = false;

  async function togglePushNotificacao() {
    if (!_pushDisponivel) {
      mostrarToastPush(
        "Notificações push não estão disponíveis neste navegador ou precisam de HTTPS.",
        "warning"
      );
      return;
    }
    if (_pushToggleBusy) return;
    _pushToggleBusy = true;
    try {
      const reg = await obterRegistroPush();
      if (Notification.permission === 'granted') {
        const sub = await reg.pushManager.getSubscription();
        if (sub) {
          await desativarPushNoAparelho(reg, sub);
          return;
        }
      }
      await ativarPush();
    } catch (e) {
      const det = (e && e.message) ? String(e.message) : String(e);
      mostrarToastPush('Erro: ' + det, 'danger');
    } finally {
      _pushToggleBusy = false;
    }
  }

  async function ativarPush() {
    try {
      const reg = await obterRegistroPush();

      if (!csrfPushToken()) {
        mostrarToastPush('Token de segurança ausente. Recarregue a página.', 'danger');
        return;
      }

      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        mostrarToastPush('Notificações bloqueadas', 'warning');
        return;
      }
      let sub = await reg.pushManager.getSubscription();
      if (!sub) {
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
        });
      }
      const r = await enviarSubscription(sub);
      if (r.aborted) return;
      if (r.ok) {
        mostrarToastPush('Notificações ativadas!', 'success');
        _marcarBellAtivo();
      } else {
        mostrarToastPush(r.msg || 'Não foi possível salvar a assinatura no servidor.', 'danger');
      }
    } catch(e) {
      const det = (e && e.message) ? String(e.message) : String(e);
      mostrarToastPush('Erro ao ativar notificações: ' + det, 'danger');
    }
  }

  async function enviarSubscription(sub) {
    if (_pushSubscribeAbort) {
      try { _pushSubscribeAbort.abort(); } catch (_) {}
    }
    const ac = new AbortController();
    _pushSubscribeAbort = ac;
    try {
      const tok = csrfPushToken();
      const res = await fetch('/push/subscribe', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'X-CSRFToken': tok,
        },
        body: JSON.stringify(sub.toJSON()),
        signal: ac.signal,
      });
      if (res.ok) return { ok: true };
      let msg = 'Não foi possível salvar (HTTP ' + res.status + ').';
      try {
        const j = await res.json();
        if (j && j.msg) msg = j.msg;
        else if (j && j.status === 'erro' && j.msg) msg = j.msg;
      } catch (_) {}
      return { ok: false, msg };
    } catch (e) {
      if (e && e.name === 'AbortError') return { ok: false, aborted: true, msg: '' };
      return { ok: false, msg: 'Falha de rede ao salvar assinatura.' };
    } finally {
      if (_pushSubscribeAbort === ac) _pushSubscribeAbort = null;
    }
  }

  function mostrarToastPush(msg, tipo) {
    const wrap = document.getElementById('toast-container');
    if (!wrap) return;
    const cls =
      tipo === 'success'
        ? 'text-bg-success'
        : tipo === 'warning'
          ? 'text-bg-warning'
          : tipo === 'info'
            ? 'text-bg-info'
            : 'text-bg-danger';
    const el = document.createElement('div');
    el.className = `toast align-items-center ${cls} border-0 mb-2`;
    el.setAttribute('role','alert');
    const row = document.createElement('div');
    row.className = 'd-flex';
    const body = document.createElement('div');
    body.className = 'toast-body';
    body.textContent = msg;
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'btn-close btn-close-white me-2 m-auto';
    close.setAttribute('data-bs-dismiss', 'toast');
    row.appendChild(body);
    row.appendChild(close);
    el.appendChild(row);
    wrap.appendChild(el);
    new bootstrap.Toast(el, {delay:4000}).show();
  }

  function _marcarBellAtivo() {
    document.querySelectorAll('.btn-ativar-push').forEach(b => {
      const ic = b.querySelector('i');
      if (ic) ic.className = 'bi bi-bell-fill';
      b.style.color = '#f97316';
      b.title = 'Desativar notificações push neste aparelho';
    });
  }

  function _marcarBellInativo() {
    document.querySelectorAll('.btn-ativar-push').forEach(b => {
      const ic = b.querySelector('i');
      if (ic) ic.className = 'bi bi-bell';
      b.style.color = '';
      b.title = 'Ativar notificações push neste aparelho';
    });
  }

  // Expõe globalmente (teste de push no perfil usa obterRegistroPush + VAPID)
  window.obterRegistroPush = obterRegistroPush;
  window.unimasterUrlBase64ToUint8Array = urlBase64ToUint8Array;
  window.unimasterVapidPublicKey = VAPID_PUBLIC_KEY;
  window.unimasterAtualizarSinoPushVisual = function (ativo) {
    if (ativo) _marcarBellAtivo();
    else _marcarBellInativo();
  };
  window.ativarPush = togglePushNotificacao;

  async function atualizarBadgeNotificacoes() {
    try {
      const r = await fetch(CFG.urls.unreadCount, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!r.ok) return;
      const j = await r.json().catch(() => ({}));
      const count = Math.max(0, parseInt((j && j.count) || 0, 10) || 0);
      document.querySelectorAll("[data-notif-badge]").forEach((el) => {
        if (count > 0) {
          el.textContent = count > 99 ? "99+" : String(count);
          el.classList.remove("d-none");
        } else {
          el.textContent = "0";
          el.classList.add("d-none");
        }
      });
    } catch (_) {
      /* silencioso */
    }
  }

  async function marcarNotificacaoLidaEIr(refId, refTipo, dest) {
    try {
      await fetch(CFG.urls.marcarLida, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({
          ref_id: parseInt(String(refId), 10),
          ref_tipo: refTipo || "parabens_live",
        }),
      });
    } catch (_) {}
    try {
      await atualizarBadgeNotificacoes();
    } catch (_) {}
    window.location.assign(dest || "/");
  }

  async function notifToolbarAcao(tipo) {
    const url =
      tipo === "marcar-todas"
        ? CFG.urls.marcarTodasLidas
        : CFG.urls.limparLidas;
    try {
      await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: "{}",
      });
    } catch (_) {}
    await carregarNotificacoesInApp();
    await atualizarBadgeNotificacoes();
  }

  function _notifEmptyMsg() {
    const p = document.createElement("p");
    p.className = "text-muted small text-center py-4 px-3 mb-0";
    p.textContent = "Não existem notificações no momento.";
    return p;
  }

  async function carregarNotificacoesInApp() {
    const containers = document.querySelectorAll("[data-notif-list-container]");
    const setLoading = () => {
      containers.forEach((el) => {
        el.innerHTML = "";
        const d = document.createElement("div");
        d.className = "p-3 text-muted small text-center";
        d.textContent = "Carregando…";
        el.appendChild(d);
      });
    };
    setLoading();
    try {
      const r = await fetch(CFG.urls.listar, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) throw new Error((j && j.msg) || "erro");
      const items = Array.isArray(j.items) ? j.items : [];
      const buildBody = () => {
        if (items.length === 0) return _notifEmptyMsg();
        const wrap = document.createElement("div");
        wrap.className = "list-group list-group-flush";
        items.forEach((it) => {
          const lida = !!it.lida;
          const a = document.createElement("a");
          a.className =
            "list-group-item list-group-item-action border-0 border-bottom py-2 px-3 text-decoration-none text-body " +
            (lida ? "notif-item-lida" : "notif-item-nao-lida");
          const link = it.link && String(it.link).startsWith("/") ? String(it.link) : "/";
          a.href = link;
          const refId = it.ref_id != null ? parseInt(String(it.ref_id), 10) : NaN;
          if (!Number.isNaN(refId) && refId > 0) {
            a.setAttribute("data-notif-ref-id", String(refId));
            a.setAttribute(
              "data-notif-ref-tipo",
              it.ref_tipo ? String(it.ref_tipo) : "parabens_live"
            );
            a.addEventListener("click", function (ev) {
              const rid = this.getAttribute("data-notif-ref-id");
              if (!rid) return;
              ev.preventDefault();
              marcarNotificacaoLidaEIr(
                rid,
                this.getAttribute("data-notif-ref-tipo"),
                this.getAttribute("href") || "/"
              );
            });
          }
          const linha1 =
            it.linha1 != null && String(it.linha1).trim() !== ""
              ? String(it.linha1).trim()
              : String(it.titulo || "").trim();
          const linha2 =
            it.linha2 != null && String(it.linha2).trim() !== ""
              ? String(it.linha2).trim()
              : "Toque para dar parabéns.";
          const t1 = document.createElement("div");
          t1.className = "fw-semibold small text-break notif-item-titulo";
          t1.textContent = linha1;
          const t2 = document.createElement("div");
          t2.className = "text-muted";
          t2.style.fontSize = "0.8rem";
          t2.textContent = linha2;
          a.appendChild(t1);
          a.appendChild(t2);
          if (it.data_br) {
            const t3 = document.createElement("div");
            t3.className = "text-muted mt-1";
            t3.style.fontSize = "0.72rem";
            t3.textContent = String(it.data_br);
            a.appendChild(t3);
          }
          wrap.appendChild(a);
        });
        return wrap;
      };
      const body = buildBody();
      containers.forEach((el) => {
        el.innerHTML = "";
        el.appendChild(body.cloneNode(true));
      });
    } catch (_) {
      containers.forEach((el) => {
        el.innerHTML = "";
        const p = document.createElement("p");
        p.className = "text-danger small text-center py-3 px-3 mb-0";
        p.textContent = "Não foi possível carregar as notificações.";
        el.appendChild(p);
      });
    }
  }

  document.querySelectorAll("[data-notif-root]").forEach(function (root) {
    root.addEventListener("shown.bs.dropdown", function () {
      carregarNotificacoesInApp();
      atualizarBadgeNotificacoes();
    });
  });

  document.addEventListener("click", function (ev) {
    if (ev.target.closest(".js-notif-marcar-todas")) {
      ev.preventDefault();
      notifToolbarAcao("marcar-todas");
      return;
    }
    if (ev.target.closest(".js-notif-limpar-lidas")) {
      ev.preventDefault();
      notifToolbarAcao("limpar-lidas");
    }
  });

  window.atualizarBadgeChatLive = atualizarBadgeNotificacoes;
  window.atualizarBadgeNotificacoes = atualizarBadgeNotificacoes;

  if (_pushDisponivel) {
    // Registra o SW na carga (não use só .ready antes do register — na 1ª visita pode não resolver)
    registrarPush();
  } else {
    _marcarBellInativo();
  }
  atualizarBadgeNotificacoes();
  setInterval(atualizarBadgeNotificacoes, 60000);
})();
})();
