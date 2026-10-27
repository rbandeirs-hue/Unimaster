/* Chamada por foto — envio ao servidor (Amazon Rekognition) e revisão.
 *
 * O celular só tira a foto, reduz e envia: quem acha e compara os rostos é o
 * servidor, pelo Rekognition (utils/rekognition.py). Assim não depende da
 * força do aparelho nem do navegador. A foto da turma não é guardada.
 *
 * Dados da página em #cfDados: pessoas da chamada, cada uma com `motivo`
 * (null = entra no reconhecimento; 'sem_foto' | 'sem_consentimento' |
 * 'visitante' = só à mão), `indexar` (a foto do cadastro ainda não foi ao
 * reconhecimento) e `pode_aprender` (autorizou: o rosto indicado é guardado).
 */
(function () {
  'use strict';

  var D = JSON.parse(document.getElementById('cfDados').textContent);
  var $ = function (id) { return document.getElementById(id); };

  // Similaridade do Rekognition (0–100). Mesma pessoa costuma passar de 95.
  var LIMIAR = 85;       // a partir daqui, "é esta pessoa"
  var CONFIRA = 93;      // abaixo disto, reconhece mas pede para conferir
  var REPETIDO = 80;     // mesmo aluno em outra foto: conta uma vez
  var APRENDER = 97;     // reconhecido abaixo disto vira mais uma referência
  var MAX_APRENDER = 25; // por chamada, para não sair caro
  var MAX_LADO = 2400;   // a foto da turma fica grande: rosto pequeno precisa de pixel
  var MAX_FOTOS = 3;

  var pessoas = D.pessoas;
  var porId = {};
  pessoas.forEach(function (p) { porId[p.id] = p; });

  var estado = novoEstado();
  function novoEstado() {
    return { fotos: [], rostos: [], presentes: new Set(), origem: {}, visitantes: [], guardar: [] };
  }

  var csrf = document.querySelector('#formGravar [name=csrf_token]').value;

  // ------------------------------------------------------------ util
  function el(tag, attrs, filhos) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') e.textContent = attrs[k];
      else if (k === 'class') e.className = attrs[k];
      else e.setAttribute(k, attrs[k]);
    });
    (filhos || []).forEach(function (f) { if (f) e.appendChild(f); });
    return e;
  }
  function sem_acento(s) {
    return (s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  }
  function iniciais(nome) {
    var p = (nome || '').trim().split(/\s+/);
    return ((p[0] || '')[0] || '') + (p.length > 1 ? p[p.length - 1][0] : '');
  }
  function mostrar(passo) {
    ['passoEntrada', 'passoAnalise', 'passoProblema', 'passoRevisao', 'passoSalva'].forEach(function (p) {
      $(p).hidden = p !== passo;
    });
    window.scrollTo(0, 0);
  }

  // ---------------------------------------------------------- imagens
  function carregarImagem(src) {
    return new Promise(function (ok, erro) {
      var i = new Image();
      i.onload = function () { ok(i); };
      i.onerror = function () { erro(new Error('imagem')); };
      i.src = src;
    });
  }
  function reduzir(img, max) {
    var w = img.naturalWidth || img.width, h = img.naturalHeight || img.height;
    var e = Math.min(1, (max || MAX_LADO) / Math.max(w, h));
    var c = document.createElement('canvas');
    c.width = Math.round(w * e); c.height = Math.round(h * e);
    c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
    return c;
  }
  async function arquivoParaCanvas(arq) {
    var url = URL.createObjectURL(arq);
    try { return reduzir(await carregarImagem(url)); }
    finally { URL.revokeObjectURL(url); }
  }
  function recortar(destino, rosto) {
    var fonte = estado.fotos[rosto.foto], b = rosto.box;
    var m = Math.max(b.width, b.height) * 0.35;
    var lado = Math.max(b.width, b.height) + 2 * m;
    var x = Math.max(0, b.x + b.width / 2 - lado / 2), y = Math.max(0, b.y + b.height / 2 - lado / 2);
    var ctx = destino.getContext('2d');
    ctx.clearRect(0, 0, destino.width, destino.height);
    ctx.drawImage(fonte, x, y, lado, lado, 0, 0, destino.width, destino.height);
  }
  function recorteBlob(rosto) {
    var c = document.createElement('canvas');
    c.width = 320; c.height = 320;
    recortar(c, rosto);
    return new Promise(function (ok) { c.toBlob(ok, 'image/jpeg', 0.88); });
  }

  // -------------------------------------------------------- servidor
  async function postar(url, corpo) {
    var json = !(corpo instanceof FormData);
    var r = await fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: json ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrf } : { 'X-CSRFToken': csrf },
      body: json ? JSON.stringify(corpo) : corpo
    });
    var d = null;
    try { d = await r.json(); } catch (e) { d = null; }
    if (!r.ok || !d || !d.ok) throw new Error((d && d.erro) || 'O servidor não respondeu (erro ' + r.status + '). Tente de novo.');
    return d;
  }
  function canvasBlob(c, q) {
    return new Promise(function (ok) { c.toBlob(ok, 'image/jpeg', q || 0.88); });
  }

  // --------------------------------------------------------- entrada
  async function adicionarArquivos(lista) {
    var arqs = Array.prototype.slice.call(lista || []);
    for (var i = 0; i < arqs.length && estado.fotos.length < MAX_FOTOS; i++) {
      try { estado.fotos.push(await arquivoParaCanvas(arqs[i])); }
      catch (e) { $('modelosStatus').textContent = 'Uma das fotos não abriu. Tente outra.'; }
    }
    desenharEscolhidas();
  }
  function desenharEscolhidas() {
    var box = $('fotosEscolhidas');
    box.innerHTML = '';
    estado.fotos.forEach(function (c, i) {
      var v = el('canvas', { 'aria-label': 'Foto ' + (i + 1) });
      v.width = c.width; v.height = c.height;
      v.getContext('2d').drawImage(c, 0, 0);
      v.style.maxHeight = '180px'; v.style.objectFit = 'cover';
      box.appendChild(v);
    });
    var n = estado.fotos.length;
    box.hidden = n === 0;
    $('btnAnalisar').hidden = n === 0;
    $('btnAnalisar').textContent = n === 1 ? 'Analisar 1 foto' : 'Analisar ' + n + ' fotos';
    $('rotuloCamera').querySelector('span').textContent = n ? 'Tirar mais uma foto' : 'Tirar foto da turma';
    $('rotuloCamera').classList.toggle('cf-btn--forte', n === 0);
    $('rotuloCamera').hidden = $('rotuloGaleria').hidden = n >= MAX_FOTOS;
  }

  // -------------------------------------------------------- análise
  var PASSOS = ['modelos', 'cadastro', 'rostos', 'comparar'];
  function passo(nome, fracao) {
    var idx = PASSOS.indexOf(nome);
    document.querySelectorAll('#analisePassos li').forEach(function (li, i) {
      li.className = i < idx ? 'feito' : (i === idx ? 'agora' : '');
    });
    var total = (idx + (fracao || 0)) / PASSOS.length * 100;
    $('analiseBarra').style.width = total + '%';
    $('analiseBarra').parentNode.setAttribute('aria-valuenow', Math.round(total));
  }

  // Foto do cadastro de quem ainda não tem referência no reconhecimento.
  async function prepararCadastro() {
    var ids = pessoas.filter(function (p) { return p.motivo === null && p.indexar; }).map(function (p) { return p.id; });
    if (!ids.length) return;
    var d = await postar(D.urlPreparar, { ids: ids });
    d.prontos.forEach(function (id) { var p = porId[id]; if (p) { p.indexar = false; p.referencias = (p.referencias || 0) + 1; } });
    d.sem_rosto.forEach(function (id) { var p = porId[id]; if (p) { p.indexar = false; p.sem_rosto = true; } });
  }

  async function analisarFoto(foto, i) {
    var fd = new FormData();
    fd.append('foto', await canvasBlob(foto, 0.9), 'turma.jpg');
    fd.append('ids', pessoas.filter(function (p) { return p.motivo === null; }).map(function (p) { return p.id; }).join(','));
    var d = await postar(D.urlAnalisar, fd);
    // O servidor responde em pixels da imagem que recebeu; o canvas é o mesmo tamanho.
    var ex = foto.width / (d.largura || foto.width), ey = foto.height / (d.altura || foto.height);
    return d.rostos.map(function (r) {
      return { foto: i, aluno: null, sim: null, estado: 'novo', matches: r.matches || [],
               box: { x: r.box.x * ex, y: r.box.y * ey, width: r.box.width * ex, height: r.box.height * ey } };
    });
  }

  function simDe(r, id) {
    var m = (r.matches || []).filter(function (x) { return x.id === id; })[0];
    return m ? m.sim : null;
  }

  function comparar() {
    var rostos = estado.rostos;
    var pares = [];
    rostos.forEach(function (r, ri) {
      r.matches.forEach(function (m) {
        var p = porId[m.id];
        if (p && p.motivo === null && m.sim >= LIMIAR) pares.push({ ri: ri, p: p, sim: m.sim });
      });
    });
    pares.sort(function (a, b) { return b.sim - a.sim; });
    var usados = {};
    pares.forEach(function (x) {
      var r = rostos[x.ri];
      if (r.aluno || usados[x.p.id]) return;
      r.aluno = x.p.id; r.sim = x.sim; r.estado = 'reconhecido';
      usados[x.p.id] = r;
    });
    // Rosto que sobrou e se parece com alguém já reconhecido em OUTRA foto é a
    // mesma criança fotografada de novo: não vai para "Quem é?".
    rostos.forEach(function (r) {
      if (r.aluno) return;
      var dup = r.matches.some(function (m) { var dono = usados[m.id]; return dono && dono.foto !== r.foto && m.sim >= REPETIDO; });
      r.estado = dup ? 'repetido' : 'desconhecido';
    });

    // Quem a foto achou entra; quem já estava marcado continua marcado.
    estado.presentes = new Set();
    estado.origem = {};
    rostos.forEach(function (r) {
      if (r.estado === 'reconhecido') { estado.presentes.add(r.aluno); estado.origem[r.aluno] = 'foto'; }
    });
    pessoas.forEach(function (p) {
      if (p.marcado && !estado.presentes.has(p.id)) { estado.presentes.add(p.id); estado.origem[p.id] = 'mao'; }
    });
  }

  async function analisar() {
    if (!estado.fotos.length) return;
    mostrar('passoAnalise');
    $('analiseTitulo').textContent = estado.fotos.length === 1 ? 'Analisando 1 foto' : 'Analisando ' + estado.fotos.length + ' fotos';
    try {
      passo('modelos');
      await prepararCadastro();
      passo('cadastro');
      estado.rostos = [];
      for (var i = 0; i < estado.fotos.length; i++) {
        passo('rostos', i / estado.fotos.length);
        estado.rostos = estado.rostos.concat(await analisarFoto(estado.fotos[i], i));
      }
      passo('comparar');
      if (!estado.rostos.length) {
        $('problemaTitulo').textContent = 'Nenhum rosto encontrado';
        $('problemaTexto').textContent = 'A foto pode ter saído escura, de longe ou com luz forte atrás da turma.';
        mostrar('passoProblema');
        return;
      }
      comparar();
      desenharRevisao();
      mostrar('passoRevisao');
    } catch (e) {
      $('problemaTitulo').textContent = 'Não deu para analisar';
      $('problemaTexto').textContent = (e && e.message) || 'Tente de novo ou faça a chamada manual.';
      mostrar('passoProblema');
    }
  }

  // --------------------------------------------------------- revisão
  function desenharFotos() {
    var box = $('revisaoFotos');
    box.innerHTML = '';
    estado.fotos.forEach(function (fonte, fi) {
      var c = el('canvas');
      c.width = fonte.width; c.height = fonte.height;
      var ctx = c.getContext('2d');
      ctx.drawImage(fonte, 0, 0);
      var lw = Math.max(2, Math.round(fonte.width / 300));
      var n = 0;
      estado.rostos.forEach(function (r) {
        if (r.foto !== fi) return;
        var cor = { reconhecido: '#4ade80', identificado: '#4ade80', desconhecido: '#fbbf24',
                    visitante: '#93c5fd', repetido: '#d6d3ce', mesmo: '#d6d3ce', ignorado: null }[r.estado];
        if (r.estado === 'desconhecido') n++;
        if (!cor) return;
        ctx.lineWidth = lw;
        ctx.strokeStyle = cor;
        ctx.setLineDash(r.estado === 'desconhecido' ? [lw * 3, lw * 2] : []);
        ctx.strokeRect(r.box.x, r.box.y, r.box.width, r.box.height);
      });
      box.appendChild(c);
    });
  }

  function linhaPessoa(p, nota, confira) {
    var marcado = estado.presentes.has(p.id);
    var avatar = p.foto_url ? el('img', { src: p.foto_url, alt: '' }) : el('span', { class: 'ini', text: iniciais(p.nome) });
    var b = el('button', { type: 'button', class: 'cf-pessoa', 'aria-pressed': marcado ? 'true' : 'false' }, [
      avatar,
      el('span', { class: 'txt' }, [
        el('b', { text: p.nome, style: 'font-weight:500' }),
        el('span', { class: confira && marcado ? 'confira' : '', text: nota })
      ]),
      el('span', { class: 'cf-marca', 'aria-hidden': 'true' }, [el('i', { class: 'bi bi-check-lg' })])
    ]);
    b.addEventListener('click', function () {
      if (estado.presentes.has(p.id)) estado.presentes.delete(p.id);
      else { estado.presentes.add(p.id); if (!estado.origem[p.id]) estado.origem[p.id] = 'mao'; }
      desenharRevisao();
    });
    return b;
  }

  function notaAusente(p) {
    if (estado.presentes.has(p.id)) return p.marcado && estado.origem[p.id] === 'mao' ? 'Já estava marcado' : 'Marcado à mão';
    if (p.motivo === 'sem_foto') return 'Sem foto — identifique uma vez para passar a ser reconhecido';
    if (p.motivo === 'sem_consentimento') return 'Sem consentimento — marcar à mão';
    if (p.motivo === 'visitante') return 'Visitante ou registro avulso';
    if (p.sem_rosto) return 'A foto do cadastro não mostra o rosto — vale trocar';
    return 'Não encontrado nas fotos';
  }

  function desenharRevisao() {
    desenharFotos();
    var porRosto = {};
    estado.rostos.forEach(function (r) { if (r.aluno) porRosto[r.aluno] = r; });

    // rostos a identificar (e os já resolvidos, para poder trocar)
    var lr = $('listaRostos');
    lr.innerHTML = '';
    var pendentes = 0;
    estado.rostos.forEach(function (r, i) {
      if (['desconhecido', 'identificado', 'visitante', 'ignorado', 'mesmo'].indexOf(r.estado) < 0) return;
      if (r.estado === 'desconhecido') pendentes++;
      var mini = el('canvas', { 'aria-hidden': 'true' });
      mini.width = 80; mini.height = 80;
      recortar(mini, r);
      var txt = r.estado === 'desconhecido' ? 'Quem é?'
        : r.estado === 'identificado' ? (porId[r.aluno] || {}).nome
        : r.estado === 'visitante' ? r.nome + ' (visitante)'
        : r.estado === 'mesmo' ? (porId[r.mesmo] || {}).nome + ' (de novo)' : 'Ignorado';
      var b = el('button', { type: 'button', class: 'cf-rosto' + (r.estado === 'desconhecido' ? '' : ' resolvido') },
        [mini, el('span', { text: txt })]);
      b.addEventListener('click', function () { abrirFolha(i); });
      lr.appendChild(b);
    });
    $('blocoIdentificar').hidden = !lr.children.length;

    // reconhecidos pela foto
    var lrec = $('listaReconhecidos');
    lrec.innerHTML = '';
    var rec = estado.rostos.filter(function (r) { return r.estado === 'reconhecido'; })
      .sort(function (a, b) { return porId[a.aluno].nome.localeCompare(porId[b.aluno].nome); });
    rec.forEach(function (r) {
      var p = porId[r.aluno];
      var confira = r.sim < CONFIRA;
      var nota = !estado.presentes.has(p.id) ? 'Desmarcado por você'
        : (confira ? 'Confira · ' : '') + Math.round(r.sim) + '% parecido';
      lrec.appendChild(linhaPessoa(p, nota, confira));
    });
    $('nReconhecidos').textContent = rec.length;
    $('blocoReconhecidos').hidden = !rec.length;

    // o resto da chamada
    var la = $('listaAusentes');
    la.innerHTML = '';
    var resto = pessoas.filter(function (p) { return !porRosto[p.id]; });
    resto.forEach(function (p) { la.appendChild(linhaPessoa(p, notaAusente(p))); });
    $('nNaoApareceram').textContent = resto.length;

    var nPres = pessoas.filter(function (p) { return estado.presentes.has(p.id); }).length;
    $('nPresentes').textContent = nPres + (estado.visitantes.length ? ' +' + estado.visitantes.length : '');
    $('nIdentificar').textContent = pendentes;
    $('nAusentes').textContent = pessoas.length - nPres;
    $('btnSalvar').textContent = 'Salvar chamada · ' + nPres + (nPres === 1 ? ' presente' : ' presentes');
    $('avisoSalvar').textContent = pendentes
      ? (pendentes === 1 ? 'O rosto sem nome não entra' : 'Os ' + pendentes + ' rostos sem nome não entram') + ' se você salvar agora.'
      : '';
  }

  // ----------------------------------------------------- folha: quem é?
  var folha = $('folhaRosto');
  var atual = null, escolhido = null;

  function desfazer(r) {
    if (r.estado === 'identificado') {
      if (estado.origem[r.aluno] === 'identificado') { estado.presentes.delete(r.aluno); delete estado.origem[r.aluno]; }
      estado.guardar = estado.guardar.filter(function (g) { return g.rosto !== r; });
      r.aluno = null;
    }
    if (r.estado === 'mesmo') {
      estado.guardar = estado.guardar.filter(function (g) { return g.rosto !== r; });
      r.mesmo = null;
    }
    if (r.estado === 'visitante') estado.visitantes = estado.visitantes.filter(function (v) { return v.rosto !== r; });
    r.estado = 'desconhecido';
  }

  function abrirFolha(i) {
    atual = estado.rostos[i];
    var total = estado.rostos.filter(function (r) {
      return ['desconhecido', 'identificado', 'visitante', 'ignorado', 'mesmo'].indexOf(r.estado) >= 0;
    });
    $('folhaSub').textContent = 'Rosto ' + (total.indexOf(atual) + 1) + ' de ' + total.length +
      (estado.fotos.length > 1 ? ' · foto ' + (atual.foto + 1) : '');
    recortar($('folhaRecorte'), atual);
    $('folhaBusca').value = '';
    $('folhaVisitante').hidden = true;
    $('folhaVisitanteNome').value = atual.estado === 'visitante' ? atual.nome : '';
    escolhido = null;
    desenharOpcoes();
    if (folha.showModal) folha.showModal(); else folha.setAttribute('open', '');
  }
  function fecharFolha() {
    if (folha.close) folha.close(); else folha.removeAttribute('open');
    atual = null;
    desenharRevisao();
  }

  function desenharOpcoes() {
    var termo = sem_acento($('folhaBusca').value.trim());
    var ocupados = {};
    estado.rostos.forEach(function (r) { if (r.aluno && r !== atual) ocupados[r.aluno] = true; });
    // Primeiro quem ainda está sem presença; no fim, quem já está marcado — se
    // o rosto for de um deles, é a mesma criança aparecendo de novo.
    var lista = pessoas.filter(function (p) {
      return !termo || sem_acento(p.nome).indexOf(termo) >= 0;
    }).map(function (p) {
      var ja = !!ocupados[p.id] || (estado.presentes.has(p.id) && !(atual && atual.aluno === p.id));
      var sim = simDe(atual, p.id);
      return { p: p, ja: ja, sim: sim === null ? -1 : sim };
    }).sort(function (a, b) { return (a.ja - b.ja) || (b.sim - a.sim) || a.p.nome.localeCompare(b.p.nome); });
    if (!escolhido || !lista.some(function (x) { return x.p === escolhido; })) {
      escolhido = atual.aluno ? porId[atual.aluno] : atual.mesmo ? porId[atual.mesmo] : (lista[0] ? lista[0].p : null);
    }
    var escolhidoJa = lista.some(function (x) { return x.p === escolhido && x.ja; });
    var box = $('folhaOpcoes');
    box.innerHTML = '';
    lista.slice(0, 40).forEach(function (x) {
      var p = x.p;
      var nota = (x.ja ? 'Já presente · ' : '') +
        (x.sim >= 0 ? Math.round(x.sim) + '% parecido' : (x.ja ? 'mesma criança de novo?' : notaAusente(p)));
      var avatar = p.foto_url ? el('img', { src: p.foto_url, alt: '', style: 'width:38px;height:38px;border-radius:999px;object-fit:cover' })
        : el('span', { text: iniciais(p.nome), style: 'width:38px;height:38px;border-radius:999px;background:#e6e4e0;display:flex;align-items:center;justify-content:center;font-size:.75rem;font-weight:600;color:#6b6862;flex-shrink:0' });
      var b = el('button', { type: 'button', class: 'cf-opcao', 'aria-pressed': p === escolhido ? 'true' : 'false' }, [
        avatar,
        el('span', { style: 'flex:1;min-width:0' }, [
          el('b', { text: p.nome, style: 'display:block;font-size:.9rem' }),
          el('span', { text: nota, style: 'display:block;font-size:.75rem;color:#6b6862' })
        ])
      ]);
      b.addEventListener('click', function () { escolhido = p; desenharOpcoes(); });
      box.appendChild(b);
    });
    if (!lista.length) box.appendChild(el('p', { class: 'cf-dica', text: 'Ninguém com esse nome nesta chamada.' }));
    // Só guarda o rosto de quem consentiu; para os outros, diz por quê.
    var podeGuardar = !!(escolhido && escolhido.pode_aprender);
    $('folhaGuardarRotulo').hidden = !podeGuardar;
    var aviso = $('folhaGuardarAviso');
    aviso.hidden = !escolhido || podeGuardar;
    if (escolhido && !podeGuardar) {
      aviso.textContent = escolhido.motivo === 'visitante'
        ? 'Visitante não tem o rosto guardado.'
        : 'Sem consentimento, o rosto não é guardado: na próxima aula ele aparece de novo para identificar. ' +
          'O consentimento se lança em Chamada por foto, no menu.';
    }
    $('folhaConfirmar').disabled = !escolhido;
    $('folhaConfirmar').textContent = !escolhido ? 'Marcar presente'
      : 'É ' + escolhido.nome.split(' ')[0] + (escolhidoJa ? ' · já está presente' : ' · marcar presente');
  }

  function confirmarRosto() {
    if (!atual || !escolhido) return;
    desfazer(atual);
    var jaEsta = estado.presentes.has(escolhido.id);
    if (jaEsta) {
      // Mesma criança de novo: não muda a presença, mas o rosto ensina.
      atual.mesmo = escolhido.id;
      atual.estado = 'mesmo';
    } else {
      atual.aluno = escolhido.id;
      atual.estado = 'identificado';
      estado.presentes.add(escolhido.id);
      estado.origem[escolhido.id] = 'identificado';
    }
    if (escolhido.pode_aprender && $('folhaGuardar').checked) {
      estado.guardar.push({ rosto: atual, aluno_id: escolhido.id });
    }
    fecharFolha();
  }

  // ----------------------------------------------------------- salvar
  async function salvar() {
    var ids = pessoas.filter(function (p) { return estado.presentes.has(p.id); }).map(function (p) { return p.id; });
    if (!ids.length && !estado.visitantes.length &&
        !window.confirm('Ninguém está marcado como presente. Salvar assim apaga a chamada desta aula. Continuar?')) return;
    var btn = $('btnSalvar');
    btn.disabled = true;
    btn.textContent = 'Salvando…';
    try {
      var fd = new FormData($('formGravar'));
      ids.forEach(function (id) { fd.append('aluno_id', id); });
      var r = await fetch(D.urlGravar, { method: 'POST', body: fd, credentials: 'same-origin' });
      if (!r.ok) throw new Error('A chamada não foi salva (erro ' + r.status + '). Tente de novo.');

      // Visitantes depois da chamada: a gravação marcaria como ausente um
      // avulso que ainda não estava na lista enviada.
      for (var i = 0; i < estado.visitantes.length; i++) {
        var v = estado.visitantes[i];
        var f = new FormData($('formGravar'));
        f.append('acao', 'presenca_avulsa');
        f.append('nome_presenca_avulsa', v.nome);
        var blob = await recorteBlob(v.rosto);
        if (blob) f.append('foto_presenca_avulsa', blob, 'visitante.jpg');
        await fetch(D.urlGravar, { method: 'POST', body: f, credentials: 'same-origin' });
      }
      // Reconhecido com folga pequena (outro ângulo, outra luz) vira mais uma
      // referência do aluno: o reconhecimento melhora a cada aula.
      estado.rostos.forEach(function (r) {
        var p = r.estado === 'reconhecido' && porId[r.aluno];
        if (p && p.pode_aprender && estado.presentes.has(p.id) && r.sim < APRENDER) {
          estado.guardar.push({ rosto: r, aluno_id: p.id });
        }
      });
      // Um rosto por vez; falha aqui não desfaz a chamada, que já foi salva.
      var aprendidos = 0;
      for (var g = 0; g < estado.guardar.length && aprendidos < MAX_APRENDER; g++) {
        try {
          var fa = new FormData();
          fa.append('aluno_id', estado.guardar[g].aluno_id);
          fa.append('rosto', await recorteBlob(estado.guardar[g].rosto), 'rosto.jpg');
          await postar(D.urlAprender, fa);
          aprendidos++;
        } catch (e) { /* fica para a próxima */ }
      }

      var conta = { foto: 0, identificado: 0, mao: 0 };
      ids.forEach(function (id) { conta[estado.origem[id] || 'mao']++; });
      $('fimPresentes').textContent = ids.length;
      $('fimAusentes').textContent = pessoas.length - ids.length;
      $('fimVisitantes').textContent = estado.visitantes.length;
      $('fimFoto').textContent = conta.foto;
      $('fimIdentificados').textContent = conta.identificado;
      $('fimMao').textContent = conta.mao;
      // Descarta as fotos: nada da imagem fica na página (nem no servidor).
      estado.fotos = [];
      estado.rostos = [];
      $('revisaoFotos').innerHTML = '';
      $('fotosEscolhidas').innerHTML = '';
      mostrar('passoSalva');
    } catch (e) {
      btn.disabled = false;
      $('avisoSalvar').textContent = e.message || 'A chamada não foi salva. Tente de novo.';
      desenharRevisao();
      $('avisoSalvar').textContent = e.message || 'A chamada não foi salva. Tente de novo.';
    }
  }

  // ----------------------------------------------------------- eventos
  $('fotoCamera').addEventListener('change', function (e) { adicionarArquivos(e.target.files); e.target.value = ''; });
  $('fotoGaleria').addEventListener('change', function (e) { adicionarArquivos(e.target.files); e.target.value = ''; });
  $('btnAnalisar').addEventListener('click', analisar);
  $('btnSalvar').addEventListener('click', salvar);
  $('folhaBusca').addEventListener('input', function () { escolhido = null; desenharOpcoes(); });
  $('folhaConfirmar').addEventListener('click', confirmarRosto);
  folha.addEventListener('close', function () { if (atual) { atual = null; desenharRevisao(); } });

  document.addEventListener('click', function (e) {
    var a = e.target.closest('[data-acao]');
    if (!a) return;
    var acao = a.getAttribute('data-acao');
    if (acao === 'recomecar') {
      estado = novoEstado();
      desenharEscolhidas();
      mostrar('passoEntrada');
    } else if (acao === 'fecharFolha') {
      fecharFolha();
    } else if (acao === 'ignorar' && atual) {
      desfazer(atual);
      atual.estado = 'ignorado';
      fecharFolha();
    } else if (acao === 'visitante') {
      $('folhaVisitante').hidden = false;
      $('folhaVisitanteNome').focus();
    } else if (acao === 'confirmarVisitante' && atual) {
      var nome = $('folhaVisitanteNome').value.trim();
      if (nome.length < 2) { $('folhaVisitanteNome').focus(); return; }
      desfazer(atual);
      atual.estado = 'visitante';
      atual.nome = nome;
      estado.visitantes.push({ rosto: atual, nome: nome });
      fecharFolha();
    }
  });

})();
