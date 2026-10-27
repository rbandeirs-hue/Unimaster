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

  var LIMIAR = 0.58;     // distância máxima para dizer "é esta pessoa" (a biblioteca sugere 0,6)
  var CONFIRA = 0.5;     // acima disto, reconhece mas pede para conferir
  var REPETIDO = 0.62;   // mesmo aluno em outra foto: conta uma vez
  var APRENDER = 0.3;    // reconhecido com folga menor que isto vira mais uma referência
  var MAX_LADO = 3000;   // a foto da turma fica grande: rosto pequeno precisa de pixel
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
  // Celular com WebGL de precisão reduzida (comum em Android) faz o detector
  // errar e os números do rosto saírem tortos: o cadastro não é lido e o rosto
  // já indicado não bate de novo. Por isso o motor se autotesta num rosto de
  // referência, calculado no servidor; se não bater, troca: WebGL (rápido) →
  // WebAssembly (mesma conta da CPU, ~10x mais rápido que ela) → CPU.
  var REF_SCORE = 0.9604;
  var REF_DESC = [-0.0539, 0.09736, 0.09807, -0.08141, -0.11523, 0.01202, -0.13585, -0.04563, 0.18254, -0.0214, 0.12021, -0.04676, -0.18774, 0.09389, -0.11829, 0.12444, -0.18656, -0.13548, -0.01522, -0.06051, 0.01539, 0.05844, 0.02688, 0.11383, -0.11737, -0.28481, -0.0739, -0.03285, 0.04013, -0.13192, -0.01953, 0.09916, -0.21656, -0.00669, 0.02448, 0.1089, -0.03726, -0.10601, 0.16955, 0.06742, -0.1943, -0.0465, 0.11431, 0.34274, 0.23706, 0.09262, -0.00934, -0.04891, 0.10216, -0.29759, 0.04063, 0.2632, 0.04266, 0.06647, 0.04732, -0.1626, 0.06037, 0.07149, -0.12653, 0.08446, 0.1036, -0.04115, 0.06761, -0.09784, 0.27887, 0.09127, -0.1004, -0.09731, 0.19175, -0.13935, -0.07801, 0.05084, -0.13608, -0.17709, -0.27009, -0.01002, 0.39981, 0.14558, -0.08603, 0.12824, -0.05483, -0.03595, -0.0248, 0.14389, -0.12267, 0.06207, -0.06877, 0.07276, 0.2533, 0.00041, 0.03883, 0.20274, -0.00097, -0.05235, 0.0334, 0.07091, -0.12162, 0.01973, -0.20611, -0.00167, -0.02498, -0.04619, 0.0322, 0.16191, -0.22611, 0.12521, 0.00972, -0.08977, -0.03822, 0.02256, -0.10301, -0.0638, 0.19287, -0.24287, 0.14564, 0.14774, 0.10323, 0.1266, 0.06594, 0.15444, 0.02146, -0.03129, -0.075, -0.06656, -0.00191, -0.06358, 0.01002, 0.08772];
  var WASM = 'https://cdn.jsdelivr.net/npm/@tensorflow/tfjs-backend-wasm@4.16.0/dist/';
  var diag = { motor: null, testes: [], cadastro: { tentados: 0, lidos: 0 } };

  async function autoteste() {
    try {
      var img = await carregarImagem(D.referencia);
      var r = await faceapi.detectSingleFace(img, new faceapi.SsdMobilenetv1Options({ minConfidence: 0.3 }))
        .withFaceLandmarks().withFaceDescriptor();
      if (!r) return { ok: false, nota: 0, dist: 9 };
      var dist = faceapi.euclideanDistance(r.descriptor, REF_DESC);
      return { ok: Math.abs(r.detection.score - REF_SCORE) < 0.06 && dist < 0.12,
               nota: Math.round(r.detection.score * 100) / 100, dist: Math.round(dist * 1000) / 1000 };
    } catch (e) {
      return { ok: false, nota: 0, dist: 9, erro: String(e && e.message || e).slice(0, 80) };
    }
  }

  var modelos = null;
  function carregarModelos() {
    if (modelos) return modelos;
    modelos = (async function () {
      if (!window.faceapi) throw new Error('O reconhecimento não carregou. Confira a internet e recarregue a página.');
      var tf = faceapi.tf;
      var motores = ['webgl', 'wasm', 'cpu'];
      // ?motor=wasm na URL força um motor: saída para um aparelho que se dê mal com o automático.
      var forcado = new URLSearchParams(location.search).get('motor');
      if (motores.indexOf(forcado) >= 0) motores = [forcado];
      for (var k = 0; k < motores.length; k++) {
        var m = motores[k], ok = false;
        try {
          if (m === 'wasm') tf.setWasmPaths(WASM);
          ok = await tf.setBackend(m);
          if (ok) await tf.ready();
        } catch (e) { ok = false; }
        if (!ok) { diag.testes.push({ motor: m, indisponivel: true }); continue; }
        if (!faceapi.nets.ssdMobilenetv1.isLoaded) {
          await faceapi.nets.ssdMobilenetv1.loadFromUri(D.modelos);
          await faceapi.nets.faceLandmark68Net.loadFromUri(D.modelos);
          await faceapi.nets.faceRecognitionNet.loadFromUri(D.modelos);
        }
        var t = await autoteste();
        t.motor = m;
        diag.testes.push(t);
        if (t.ok || m === 'cpu') { diag.motor = m; return; }
      }
      throw new Error('O reconhecimento não rodou neste aparelho.');
    })();
    modelos.then(function () {
      $('modelosStatus').textContent = 'Reconhecimento pronto' +
        (diag.motor === 'webgl' ? '.' : diag.motor === 'wasm' ? ' (modo compatível).' : ' (modo lento: pode demorar).');
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
          body: JSON.stringify({ itens: itens.slice(i, i + 50), diag: diag })
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
      var lido = false;
      try {
        var r = await detectarUm(await carregarImagem(p.foto_url));
        lido = !!r;
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
      diag.cadastro.tentados++;
      if (lido) diag.cadastro.lidos++;
      p.calcular = null;
    }
    rotulo.textContent = 'Lendo as fotos do cadastro';
    // Vai mesmo sem nenhum lido: leva o diagnóstico do aparelho.
    if (faltam.length) enviarDescritores(novos);
  }

  // ------------------------------------------------------- detecção
  var SSD = function (conf) { return new faceapi.SsdMobilenetv1Options({ minConfidence: conf, maxResults: 100 }); };

  // Foto do cadastro: o recorte do sistema deixa o rosto ocupando o quadro
  // inteiro, e o detector se perde sem margem. Põe uma moldura neutra em volta;
  // se ainda assim não achar, tenta de novo menos exigente.
  async function detectarUm(img) {
    var base = reduzir(img, 640);
    var m = Math.round(Math.max(base.width, base.height) * 0.35);
    var c = document.createElement('canvas');
    c.width = base.width + 2 * m; c.height = base.height + 2 * m;
    var ctx = c.getContext('2d');
    ctx.fillStyle = '#808080';
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.drawImage(base, m, m);
    var tentativas = [[c, 0.3], [c, 0.15], [base, 0.15]];
    for (var i = 0; i < tentativas.length; i++) {
      var r = await faceapi.detectSingleFace(tentativas[i][0], SSD(tentativas[i][1]))
        .withFaceLandmarks().withFaceDescriptor();
      if (r) return r;
    }
    return null;
  }

  function iou(a, b) {
    var x1 = Math.max(a.x, b.x), y1 = Math.max(a.y, b.y);
    var x2 = Math.min(a.x + a.width, b.x + b.width), y2 = Math.min(a.y + a.height, b.y + b.height);
    var inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
    var menor = Math.min(a.width * a.height, b.width * b.height);
    return { iou: inter / (a.width * a.height + b.width * b.height - inter), cobre: inter / menor };
  }

  // Foto da turma: o detector encolhe tudo para 512 px por dentro, e numa foto
  // de grupo o rosto do fundo some. Por isso passa três vezes, de longe para
  // perto: a foto inteira (rostos grandes, na frente), uma grade média e uma
  // grade fina de pedaços de ~640 px, que numa foto de celular dá uns 35
  // pedaços — cada um ampliado por dentro, o que acha até o rosto da última
  // fileira de uma turma de 50+. Junta tudo sem repetir rosto.
  var PEDACO_FINO = 640, SOBRA = 0.3;

  function grade(W, H, lado) {
    lado = Math.min(lado, W, H);
    var passo = lado * (1 - SOBRA);
    var cols = Math.max(1, Math.ceil((W - lado) / passo) + 1), lins = Math.max(1, Math.ceil((H - lado) / passo) + 1);
    var out = [];
    for (var li = 0; li < lins; li++) {
      for (var co = 0; co < cols; co++) {
        var x = cols === 1 ? 0 : Math.round(co * (W - lado) / (cols - 1));
        var y = lins === 1 ? 0 : Math.round(li * (H - lado) / (lins - 1));
        out.push({ x: x, y: y, w: lado, h: lado });
      }
    }
    return out;
  }

  async function detectarTodos(foto, aoAvancar) {
    var W = foto.width, H = foto.height;
    var pedacos = [{ x: 0, y: 0, w: W, h: H, inteira: true }]
      .concat(grade(W, H, Math.round(Math.max(W, H) / 2.2)))
      .concat(Math.max(W, H) > PEDACO_FINO * 1.5 ? grade(W, H, PEDACO_FINO) : []);
    var achados = [];
    var t = document.createElement('canvas');
    for (var k = 0; k < pedacos.length; k++) {
      var pc = pedacos[k];
      var fonte = foto;
      if (!pc.inteira) {
        t.width = pc.w; t.height = pc.h;
        t.getContext('2d').drawImage(foto, pc.x, pc.y, pc.w, pc.h, 0, 0, pc.w, pc.h);
        fonte = t;
      }
      var dets = await faceapi.detectAllFaces(fonte, SSD(pc.inteira ? 0.45 : 0.4)).withFaceLandmarks().withFaceDescriptors();
      dets.forEach(function (d) {
        var b = d.detection.box;
        // Rosto cortado na borda do pedaço é meio rosto: o vizinho, que se
        // sobrepõe em 30%, o pega inteiro.
        if (!pc.inteira && ((b.x < 3 && pc.x > 0) || (b.y < 3 && pc.y > 0) ||
            (b.x + b.width > pc.w - 3 && pc.x + pc.w < W) || (b.y + b.height > pc.h - 3 && pc.y + pc.h < H))) return;
        achados.push({ box: { x: pc.x + b.x, y: pc.y + b.y, width: b.width, height: b.height },
                       score: d.detection.score, descritor: d.descriptor });
      });
      if (aoAvancar) aoAvancar((k + 1) / pedacos.length);
    }
    achados.sort(function (a, b) { return b.score - a.score; });
    var ficam = [];
    achados.forEach(function (a) {
      var repetido = ficam.some(function (f) { var q = iou(a.box, f.box); return q.iou > 0.3 || q.cobre > 0.6; });
      if (!repetido) ficam.push(a);
    });
    return ficam;
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
    // Rosto que sobrou e se parece com alguém já reconhecido em OUTRA foto é a
    // mesma criança fotografada de novo: não vai para "Quem é?".
    rostos.forEach(function (r) {
      if (r.aluno) return;
      var melhor = null;
      Object.keys(usados).forEach(function (id) {
        var dono = usados[id];
        if (dono.foto === r.foto) return;
        var d = distancia(r.descritor, porId[id]);
        if (d < REPETIDO && (!melhor || d < melhor.d)) melhor = { d: d };
      });
      r.estado = melhor ? 'repetido' : 'desconhecido';
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
      for (var i = 0; i < estado.fotos.length; i++) {
        var nf = estado.fotos.length, fi = i;
        passo('rostos', i / nf);
        var dets = await detectarTodos(estado.fotos[i], function (f) { passo('rostos', (fi + f) / nf); });
        dets.forEach(function (d) {
          estado.rostos.push({ foto: i, box: d.box, descritor: d.descritor, aluno: null, dist: null, estado: 'novo' });
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
      return { p: p, ja: ja, d: p.descritores.length ? distancia(atual.descritor, p) : Infinity };
    }).sort(function (a, b) { return (a.ja - b.ja) || (a.d - b.d) || a.p.nome.localeCompare(b.p.nome); });
    if (!escolhido || !lista.some(function (x) { return x.p === escolhido; })) {
      escolhido = atual.aluno ? porId[atual.aluno] : atual.mesmo ? porId[atual.mesmo] : (lista[0] ? lista[0].p : null);
    }
    var escolhidoJa = lista.some(function (x) { return x.p === escolhido && x.ja; });
    var box = $('folhaOpcoes');
    box.innerHTML = '';
    lista.slice(0, 40).forEach(function (x) {
      var p = x.p;
      var nota = (x.ja ? 'Já presente · ' : '') +
        (isFinite(x.d) ? pct(x.d) + '% parecido' : (x.ja ? 'mesma criança de novo?' : notaAusente(p)));
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
      // Reconhecido com folga pequena (outro ângulo, outra luz) vira mais uma
      // referência do aluno: o reconhecimento melhora a cada aula.
      estado.rostos.forEach(function (r) {
        var p = r.estado === 'reconhecido' && porId[r.aluno];
        if (p && p.pode_aprender && estado.presentes.has(p.id) && r.dist > APRENDER) {
          estado.guardar.push({ rosto: r, aluno_id: Number(p.id), origem: 'chamada', descritor: Array.from(r.descritor) });
        }
      });
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
