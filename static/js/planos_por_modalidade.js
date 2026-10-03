/* Filtra o <select> de plano pela(s) modalidade(s) escolhida(s) no formulário.
   Cada <option> traz data-mods="1,7" (modalidades do plano; vazio = sem
   modalidade, aparece sempre). Uso:
     PlanosPorModalidade(selectPlano, function () { return ['1', '7']; }, gatilhos)
   Regra: primeiro os planos cujas modalidades são EXATAMENTE as escolhidas
   (Judô → planos de Judô; Judô + Jiu-Jitsu → o combo dos dois). Se nenhum bater
   exato, os que incluem alguma das escolhidas. Nada escolhido: todos. */
window.PlanosPorModalidade = function (sel, escolhidas, gatilhos) {
  if (!sel) return;
  function aplicar() {
    var mods = (escolhidas() || []).filter(Boolean).map(String).sort();
    var opcoes = Array.prototype.filter.call(sel.options, function (o) { return o.hasAttribute('data-mods'); });
    function mostra(o, ok) { o.hidden = !ok; o.disabled = !ok; }
    if (!mods.length) { opcoes.forEach(function (o) { mostra(o, true); }); return; }
    var exatos = opcoes.filter(function (o) {
      var pm = (o.getAttribute('data-mods') || '').split(',').filter(Boolean).sort();
      return pm.length && pm.join(',') === mods.join(',');
    });
    opcoes.forEach(function (o) {
      var pm = (o.getAttribute('data-mods') || '').split(',').filter(Boolean);
      var ok = !pm.length || (exatos.length ? exatos.indexOf(o) >= 0
                                            : pm.some(function (m) { return mods.indexOf(m) >= 0; }));
      mostra(o, ok);
    });
    var atual = sel.options[sel.selectedIndex];
    if (atual && atual.disabled) {
      var prim = Array.prototype.find.call(sel.options, function (o) { return !o.disabled && o.value; });
      sel.value = prim ? prim.value : '';
      sel.dispatchEvent(new Event('change'));
    }
  }
  (gatilhos || []).forEach(function (g) { if (g) g.addEventListener('change', aplicar); });
  aplicar();
};
