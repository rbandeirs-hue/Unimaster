/* =====================================================================
   CSRF automático — formulários, fetch() e XMLHttpRequest
   =====================================================================
   Vivia inline no base.html. Enquanto ficou lá, toda tela migrada para o
   shell perdia a proteção e o POST voltava 400 — foi o que aconteceu com
   a matrícula em turma na lista de alunos.

   Agora é arquivo e as DUAS bases carregam. Depende apenas da
   <meta name="csrf-token"> presente no <head> de ambas.
   ===================================================================== */

// ── CSRF: injeção automática em formulários e requisições AJAX ──────────────
(function () {
    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    var csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';
    if (!csrfToken) return;

    // 1) Injeta campo oculto em todos os <form method="post"> da página
    function injetarEmForms() {
        document.querySelectorAll('form').forEach(function (form) {
            var method = (form.getAttribute('method') || 'get').toLowerCase();
            if (method !== 'post') return;
            if (form.querySelector('input[name="csrf_token"]')) return;
            var input = document.createElement('input');
            input.type  = 'hidden';
            input.name  = 'csrf_token';
            input.value = csrfToken;
            form.appendChild(input);
        });
    }

    // Executa ao carregar e observa novos forms adicionados dinamicamente
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', injetarEmForms);
    } else {
        injetarEmForms();
    }
    var observer = new MutationObserver(injetarEmForms);
    observer.observe(document.body, { childList: true, subtree: true });

    // 2) Intercepta fetch() para enviar X-CSRFToken automaticamente
    var _fetch = window.fetch;
    window.fetch = function (url, opts) {
        opts = opts || {};
        var method = (opts.method || 'GET').toUpperCase();
        if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
            opts.headers = opts.headers || {};
            if (opts.headers instanceof Headers) {
                if (!opts.headers.has('X-CSRFToken')) opts.headers.set('X-CSRFToken', csrfToken);
            } else {
                opts.headers['X-CSRFToken'] = opts.headers['X-CSRFToken'] || csrfToken;
            }
        }
        return _fetch.call(this, url, opts);
    };

    // 3) Intercepta XMLHttpRequest
    var _open = XMLHttpRequest.prototype.open;
    var _send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method) {
        this._csrfMethod = method.toUpperCase();
        return _open.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function () {
        if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(this._csrfMethod)) {
            this.setRequestHeader('X-CSRFToken', csrfToken);
        }
        return _send.apply(this, arguments);
    };
})();
