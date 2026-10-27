/* Chamada por foto — reconhecimento no navegador (face-api) e revisão.
 *
 * As fotos da turma ficam só neste aparelho: o que vai para o servidor é a
 * lista de presentes (mesmo POST da chamada manual) e, para quem deu
 * consentimento, o descritor do rosto (128 números).
 *
 * Dados da página em #cfDados: pessoas da chamada, cada uma com `motivo`
 * (null = entra no reconhecimento; 'sem_foto' | 'sem_consentimento' |
 * 'visitante' = só à mão), `descritores` já guardados e `calcular` (nome da
 * foto do cadastro cujo descritor ainda não existe).
 */
(function () {
  'use strict';

  var D = JSON.parse(document.getElementById('cfDados').textContent);
  var $ = function (id) { return document.getElementById(id); };

  var LIMIAR = 0.55;     // distância máxima para dizer "é esta pessoa"
  var CONFIRA = 0.47;    // acima disto, reconhece mas pede para conferir
  var REPETIDO = 0.5;    // mesmo aluno em outra foto: conta uma vez
  var MAX_LADO = 1600;
  var MAX_FOTOS = 3;

  var pessoas = D.pessoas.map(function (p) {
    p.descritores = p.descritores || [];
    return p;
  });
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
  function pct(d) {
    return Math.max(0, Math.min(100, Math.round((0.8 - d) / 0.5 * 100)));
  }
  function mostrar(passo) {
    ['passoEntrada', 'passoAnalise', 'passoProblema', 'passoRevisao', 'passoSalva'].forEach(function (p) {
      $(p).hidden = p !== passo;
    });
    window.scrollTo(0, 0);
  }

  // --------------------------------------------------------- modelos
  var modelos = null;
  function carregarModelos() {
    if (modelos) return modelos;
    modelos = (async function () {
      if (!window.faceapi) throw new Error('O reconhecimento não carregou. Confira a internet e recarregue a página.');
      // O motor precisa ser escolhido e iniciado antes do primeiro uso. WebGL
      // (placa de vídeo) é o rápido; aparelho sem ele cai para a CPU, mais lento.
      var tf = faceapi.tf;
      var ok = false;
      try { ok = await tf.setBackend('webgl'); } catch (e) { ok = false; }
      if (!ok) await tf.setBackend('cpu');
      await tf.ready();
      await faceapi.nets.ssdMobilenetv1.loadFromUri(D.modelos);
      await faceapi.nets.faceLandmark68Net.loadFromUri(D.modelos);
      await faceapi.nets.faceRecognitionNet.loadFromUri(D.modelos);
    })();
    modelos.then(function () {
      $('modelosStatus').textContent = 'Reconhecimento pronto.';
    }, function (e) {
      $('modelosStatus').textContent = e.message || 'Não foi possível carregar o reconhecimento.';
      modelos = null;
    });
    return modelos;
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
  async function enviarDescritores(itens) {
    for (var i = 0; i < itens.length; i += 50) {
      try {
        await fetch(D.urlDescritores, {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
          body: JSON.stringify({ itens: itens.slice(i, i + 50) })
        });
      } catch (e) { /* não impede a chamada: recalcula na próxima */ }
    }
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

  async function calcularCadastro() {
    var faltam = pessoas.filter(function (p) { return p.motivo === null && p.calcular; });
    var novos = [];
    var rotulo = document.querySelector('#analisePassos li[data-p=cadastro] span:last-child');
    for (var i = 0; i < faltam.length; i++) {
      var p = faltam[i];
      passo('cadastro', i / Math.max(1, faltam.length));
      rotulo.textContent = 'Lendo as fotos do cadastro (' + (i + 1) + ' de ' + faltam.length + ')';
      try {
        var img = reduzir(await carregarImagem(p.foto_url), 800);
        var r = await faceapi.detectSingleFace(img, new faceapi.SsdMobilenetv1Options({ minConfidence: 0.3 }))
          .withFaceLandmarks().withFaceDescriptor();
        if (r) {
          var d = Array.from(r.descriptor);
          p.descritores.push(d);
          novos.push({ aluno_id: Number(p.id), origem: 'cadastro', foto: p.calcular, descritor: d });
        } else if (!p.descritores.length) {
          p.semRosto = true;
        }
      } catch (e) {
        if (!p.descritores.length) p.semRosto = true;
      }
      p.calcular = null;
    }
    rotulo.textContent = 'Lendo as fotos do cadastro';
    if (novos.length) enviarDescritores(novos);
  }

  function distancia(desc, p) {
    var m = Infinity;
    p.descritores.forEach(function (d) { m = Math.min(m, faceapi.euclideanDistance(desc, d)); });
    return m;
  }

  function comparar() {
    var rostos = estado.rostos;
    var candidatos = pessoas.filter(function (p) { return p.motivo === null && p.descritores.length; });
    var pares = [];
    rostos.forEach(function (r, ri) {
      candidatos.forEach(function (p) {
        var d = distancia(r.descritor, p);
        if (d < LIMIAR) pares.push({ ri: ri, p: p, d: d });
      });
    });
    pares.sort(function (a, b) { return a.d - b.d; });
    var usados = {};
    pares.forEach(function (x) {
      var r = rostos[x.ri];
      if (r.aluno || usados[x.p.id]) return;
      r.aluno = x.p.id; r.dist = x.d; r.estado = 'reconhecido';
      usados[x.p.id] = r;
    });
    rostos.forEach(function (r) {
      if (r.aluno) return;
      var melhor = null;
      pares.forEach(function (x) { if (rostos[x.ri] === r && (!melhor || x.d < melhor.d)) melhor = x; });
      var dono = melhor && usados[melhor.p.id];
      r.estado = (dono && dono.foto !== r.foto && melhor.d < REPETIDO) ? 'repetido' : 'desconhecido';
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
      await carregarModelos();
      await calcularCadastro();
      passo('rostos');
      estado.rostos = [];
      var opc = new faceapi.SsdMobilenetv1Options({ minConfidence: 0.45, maxResults: 100 });
      for (var i = 0; i < estado.fotos.length; i++) {
        passo('rostos', i / estado.fotos.length);
        var dets = await faceapi.detectAllFaces(estado.fotos[i], opc).withFaceLandmarks().withFaceDescriptors();
        dets.forEach(function (d) {
          estado.rostos.push({ foto: i, box: d.detection.box, descritor: d.descriptor, aluno: null, dist: null, estado: 'novo' });
        });
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
      $('problemaTexto').textContent = (e && e.message && e.message !== 'imagem') ? e.message
        : 'O reconhecimento não rodou neste aparelho. Tente de novo ou faça a chamada manual.';
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
                    visitante: '#93c5fd', repetido: '#d6d3ce', ignorado: null }[r.estado];
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
    if (p.semRosto) return 'A foto do cadastro não mostra o rosto';
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
      if (['desconhecido', 'identificado', 'visitante', 'ignorado'].indexOf(r.estado) < 0) return;
      if (r.estado === 'desconhecido') pendentes++;
      var mini = el('canvas', { 'aria-hidden': 'true' });
      mini.width = 80; mini.height = 80;
      recortar(mini, r);
      var txt = r.estado === 'desconhecido' ? 'Quem é?'
        : r.estado === 'identificado' ? (porId[r.aluno] || {}).nome
        : r.estado === 'visitante' ? r.nome + ' (visitante)' : 'Ignorado';
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
      var confira = r.dist > CONFIRA;
      var nota = !estado.presentes.has(p.id) ? 'Desmarcado por você'
        : (confira ? 'Confira · ' : '') + pct(r.dist) + '% parecido';
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
    if (r.estado === 'visitante') estado.visitantes = estado.visitantes.filter(function (v) { return v.rosto !== r; });
    r.estado = 'desconhecido';
  }

  function abrirFolha(i) {
    atual = estado.rostos[i];
    var total = estado.rostos.filter(function (r) {
      return ['desconhecido', 'identificado', 'visitante', 'ignorado'].indexOf(r.estado) >= 0;
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
    var lista = pessoas.filter(function (p) {
      if (ocupados[p.id]) return false;
      if (estado.presentes.has(p.id) && !(atual && atual.aluno === p.id)) return false;
      return !termo || sem_acento(p.nome).indexOf(termo) >= 0;
    }).map(function (p) {
      return { p: p, d: p.descritores.length ? distancia(atual.descritor, p) : Infinity };
    }).sort(function (a, b) { return (a.d - b.d) || a.p.nome.localeCompare(b.p.nome); });
    if (!escolhido || !lista.some(function (x) { return x.p === escolhido; })) {
      escolhido = atual.aluno ? porId[atual.aluno] : (lista[0] ? lista[0].p : null);
    }
    var box = $('folhaOpcoes');
    box.innerHTML = '';
    lista.slice(0, 40).forEach(function (x) {
      var p = x.p;
      var nota = isFinite(x.d) ? pct(x.d) + '% parecido com a foto do cadastro' : notaAusente(p);
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
    if (!lista.length) box.appendChild(el('p', { class: 'cf-dica', text: 'Ninguém com esse nome fora da lista de presentes.' }));
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
    $('folhaConfirmar').textContent = escolhido ? 'É ' + escolhido.nome.split(' ')[0] + ' · marcar presente' : 'Marcar presente';
  }

  function confirmarRosto() {
    if (!atual || !escolhido) return;
    desfazer(atual);
    atual.aluno = escolhido.id;
    atual.estado = 'identificado';
    estado.presentes.add(escolhido.id);
    estado.origem[escolhido.id] = 'identificado';
    if (escolhido.pode_aprender && $('folhaGuardar').checked) {
      var d = Array.from(atual.descritor);
      escolhido.descritores.push(d);
      estado.guardar.push({ rosto: atual, aluno_id: Number(escolhido.id), origem: 'chamada', descritor: d });
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
      if (estado.guardar.length) {
        await enviarDescritores(estado.guardar.map(function (g) {
          return { aluno_id: g.aluno_id, origem: g.origem, descritor: g.descritor };
        }));
      }

      var conta = { foto: 0, identificado: 0, mao: 0 };
      ids.forEach(function (id) { conta[estado.origem[id] || 'mao']++; });
      $('fimPresentes').textContent = ids.length;
      $('fimAusentes').textContent = pessoas.length - ids.length;
      $('fimVisitantes').textContent = estado.visitantes.length;
      $('fimFoto').textContent = conta.foto;
      $('fimIdentificados').textContent = conta.identificado;
      $('fimMao').textContent = conta.mao;
      // Descarta as fotos: nada da imagem fica na página.
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

  // Começa a baixar os modelos já: quando a foto chegar, estão prontos.
  carregarModelos();
})();
