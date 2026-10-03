/* =======================================================================
   Diálogos do sistema — alerta e confirmação
   =======================================================================
   Substitui `alert()` e `confirm()` do navegador, que chegavam com a cara
   do sistema operacional, botão "OK" em inglês em alguns aparelhos e nenhum
   jeito de distinguir "salvar" de "apagar para sempre".

   Como usar:

     Dialogo.alerta('CPF inválido.')                     -> Promise
     Dialogo.confirmar('Excluir o aluno?')               -> Promise<boolean>
     Dialogo.confirmar(texto, { tom: 'perigo', titulo, confirmar, cancelar })

   Declarativo, sem escrever JS (é o caminho das ~75 telas convertidas):

     <form ... data-confirmar="Excluir a forma Pix?">
     <a href="..." data-confirmar="Sair sem salvar?" data-confirmar-tom="aviso">

   `window.alert` fica apontando para o diálogo daqui, então toda chamada
   antiga ganha o desenho novo sem tocar na tela. `window.confirm` NÃO é
   substituível: ele devolve a resposta na hora, e uma caixa desenhada em
   HTML só responde depois — por isso a conversão das chamadas para
   `data-confirmar` ou para a promessa acima.
   ======================================================================= */

(function (window, document) {
  'use strict';

  var aberto = null;     // { fundo, resolver, focoAnterior }
  var fila = [];         // diálogos pedidos enquanto outro estava aberto

  var ICONES = {
    info:   'bi-info-circle-fill',
    perigo: 'bi-exclamation-triangle-fill',
    aviso:  'bi-exclamation-circle-fill',
    ok:     'bi-check-circle-fill'
  };

  var TITULOS = {
    info:   'Atenção',
    perigo: 'Confirmar',
    aviso:  'Atenção',
    ok:     'Tudo certo'
  };

  /* O `\n` das mensagens antigas vem literal quando a frase mora num
     atributo HTML; aqui ele volta a ser quebra de linha. */
  function normalizar(texto) {
    return String(texto == null ? '' : texto).replace(/\\n/g, '\n');
  }

  function criarCaixa(opcoes) {
    var tom = opcoes.tom || 'info';

    var fundo = document.createElement('div');
    fundo.className = 'dlg-fundo';

    var caixa = document.createElement('div');
    caixa.className = 'dlg dlg--' + tom;
    caixa.setAttribute('role', 'alertdialog');
    caixa.setAttribute('aria-modal', 'true');

    var topo = document.createElement('div');
    topo.className = 'dlg__topo';

    var ico = document.createElement('span');
    ico.className = 'dlg__ico';
    ico.setAttribute('aria-hidden', 'true');
    ico.innerHTML = '<i class="bi ' + (ICONES[tom] || ICONES.info) + '"></i>';

    var corpo = document.createElement('div');
    corpo.className = 'dlg__corpo';

    var titulo = document.createElement('h2');
    titulo.className = 'dlg__titulo';
    titulo.textContent = opcoes.titulo || TITULOS[tom] || TITULOS.info;
    titulo.id = 'dlg-titulo-' + Date.now();
    caixa.setAttribute('aria-labelledby', titulo.id);

    var texto = document.createElement('p');
    texto.className = 'dlg__texto';
    texto.textContent = normalizar(opcoes.texto);

    corpo.appendChild(titulo);
    corpo.appendChild(texto);
    topo.appendChild(ico);
    topo.appendChild(corpo);
    caixa.appendChild(topo);

    var acoes = document.createElement('div');
    acoes.className = 'dlg__acoes';

    var btnCancelar = null;
    if (opcoes.pergunta) {
      btnCancelar = document.createElement('button');
      btnCancelar.type = 'button';
      btnCancelar.className = 'dlg__btn';
      btnCancelar.textContent = opcoes.cancelar || 'Cancelar';
      acoes.appendChild(btnCancelar);
    }

    var btnOk = document.createElement('button');
    btnOk.type = 'button';
    btnOk.className = 'dlg__btn ' + (tom === 'perigo' ? 'dlg__btn--perigo' : 'dlg__btn--forte');
    btnOk.textContent = opcoes.confirmar || (opcoes.pergunta ? 'Confirmar' : 'Entendi');
    acoes.appendChild(btnOk);

    caixa.appendChild(acoes);
    fundo.appendChild(caixa);

    return { fundo: fundo, caixa: caixa, btnOk: btnOk, btnCancelar: btnCancelar };
  }

  function fechar(resposta) {
    if (!aberto) return;
    var atual = aberto;
    aberto = null;

    atual.fundo.classList.remove('is-aberto');
    document.removeEventListener('keydown', atual.aoTeclar, true);

    window.setTimeout(function () {
      if (atual.fundo.parentNode) atual.fundo.parentNode.removeChild(atual.fundo);
      if (!document.querySelector('.dlg-fundo')) {
        document.body.style.removeProperty('overflow');
      }
      if (atual.focoAnterior && atual.focoAnterior.focus) {
        try { atual.focoAnterior.focus(); } catch (e) { /* elemento saiu da tela */ }
      }
      atual.resolver(resposta);
      if (fila.length) abrir(fila.shift());
    }, 160);
  }

  function abrir(pedido) {
    var partes = criarCaixa(pedido.opcoes);
    var focoAnterior = document.activeElement;

    function aoTeclar(ev) {
      if (ev.key === 'Escape') {
        ev.preventDefault();
        fechar(false);
        return;
      }
      if (ev.key === 'Enter' && document.activeElement !== partes.btnCancelar) {
        ev.preventDefault();
        fechar(true);
        return;
      }
      // Tab não escapa da caixa: só há dois botões, então basta alternar.
      if (ev.key === 'Tab' && partes.btnCancelar) {
        ev.preventDefault();
        var proximo = document.activeElement === partes.btnOk ? partes.btnCancelar : partes.btnOk;
        proximo.focus();
      }
    }

    partes.btnOk.addEventListener('click', function () { fechar(true); });
    if (partes.btnCancelar) {
      partes.btnCancelar.addEventListener('click', function () { fechar(false); });
    }
    // Clique fora fecha como "não": é o gesto de desistir.
    partes.fundo.addEventListener('mousedown', function (ev) {
      if (ev.target === partes.fundo) fechar(false);
    });

    document.body.appendChild(partes.fundo);
    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', aoTeclar, true);

    aberto = {
      fundo: partes.fundo,
      resolver: pedido.resolver,
      focoAnterior: focoAnterior,
      aoTeclar: aoTeclar
    };

    // Um quadro depois, para a transição de entrada acontecer.
    window.requestAnimationFrame(function () {
      partes.fundo.classList.add('is-aberto');
      // O foco começa na ação segura quando a outra é destrutiva.
      var inicial = (pedido.opcoes.tom === 'perigo' && partes.btnCancelar)
        ? partes.btnCancelar : partes.btnOk;
      inicial.focus();
    });
  }

  function pedir(opcoes) {
    return new Promise(function (resolver) {
      var pedido = { opcoes: opcoes, resolver: resolver };
      if (aberto) fila.push(pedido);
      else abrir(pedido);
    });
  }

  var Dialogo = {
    alerta: function (texto, opcoes) {
      opcoes = opcoes || {};
      return pedir({
        texto: texto,
        pergunta: false,
        tom: opcoes.tom || 'info',
        titulo: opcoes.titulo,
        confirmar: opcoes.confirmar
      });
    },

    confirmar: function (texto, opcoes) {
      opcoes = opcoes || {};
      return pedir({
        texto: texto,
        pergunta: true,
        tom: opcoes.tom || 'perigo',
        titulo: opcoes.titulo,
        confirmar: opcoes.confirmar,
        cancelar: opcoes.cancelar
      });
    },

    /* Pergunta a partir de um evento que já está acontecendo (submit de
       formulário, clique em botão). Segura o evento, pergunta e, com o sim,
       refaz a ação original — é o substituto de
       `if (!confirm(...)) e.preventDefault();`, que dependia de o navegador
       responder na hora. */
    confirmarEvento: function (ev, texto, opcoes) {
      // `alvo` é obrigatório quando o ouvinte é delegado (no document): ali
      // `currentTarget` é o document, e quem precisa ser reenviado é o form.
      var alvo = (opcoes && opcoes.alvo) || ev.currentTarget || ev.target;
      if (!alvo || alvo.__dlgLiberado) return;

      ev.preventDefault();
      ev.stopPropagation();

      Dialogo.confirmar(texto, opcoes).then(function (ok) {
        if (!ok) return;
        alvo.__dlgLiberado = true;
        if (alvo.tagName === 'FORM') {
          if (alvo.requestSubmit) alvo.requestSubmit();
          else alvo.submit();
        } else if (alvo.click) {
          alvo.click();
        }
        window.setTimeout(function () { alvo.__dlgLiberado = false; }, 0);
      });
    },

    /* Para quem já tem a resposta e só quer dizer que deu certo. */
    sucesso: function (texto, opcoes) {
      opcoes = opcoes || {};
      opcoes.tom = 'ok';
      return Dialogo.alerta(texto, opcoes);
    }
  };

  window.Dialogo = Dialogo;

  /* `alert()` vira o diálogo do sistema. A única diferença de
     comportamento é que ele não trava a página: quem chamava
     `alert(msg); return;` continua funcionando igual. */
  window.alert = function (mensagem) {
    Dialogo.alerta(mensagem);
  };

  /* ----------------------------------------------------- modo declarativo */
  function opcoesDoElemento(el) {
    return {
      tom: el.getAttribute('data-confirmar-tom') || 'perigo',
      titulo: el.getAttribute('data-confirmar-titulo') || undefined,
      confirmar: el.getAttribute('data-confirmar-acao') || undefined,
      cancelar: el.getAttribute('data-confirmar-cancelar') || undefined
    };
  }

  // Captura antes de qualquer handler da tela: a pergunta vem primeiro.
  document.addEventListener('click', function (ev) {
    var el = ev.target && ev.target.closest ? ev.target.closest('[data-confirmar]') : null;
    if (!el || el.tagName === 'FORM' || el.__dlgLiberado) return;

    ev.preventDefault();
    ev.stopPropagation();

    Dialogo.confirmar(el.getAttribute('data-confirmar'), opcoesDoElemento(el))
      .then(function (ok) {
        if (!ok) return;
        el.__dlgLiberado = true;
        el.click();
        window.setTimeout(function () { el.__dlgLiberado = false; }, 0);
      });
  }, true);

  document.addEventListener('submit', function (ev) {
    var form = ev.target;
    if (!form || !form.hasAttribute || !form.hasAttribute('data-confirmar')) return;
    if (form.__dlgLiberado) return;

    ev.preventDefault();
    ev.stopPropagation();

    Dialogo.confirmar(form.getAttribute('data-confirmar'), opcoesDoElemento(form))
      .then(function (ok) {
        if (!ok) return;
        form.__dlgLiberado = true;
        // `requestSubmit` mantém os outros handlers da tela vivos; o
        // `submit()` cru os pularia.
        if (form.requestSubmit) form.requestSubmit();
        else form.submit();
        window.setTimeout(function () { form.__dlgLiberado = false; }, 0);
      });
  }, true);

})(window, document);
