/* =====================================================================
   Formulários — evita o preenchimento automático de e-mail e senha nas
   telas de cadastro de usuário. Extraído do base.html.
   ===================================================================== */

// Garantir que campos de email e senha em formulários de cadastro não sejam preenchidos automaticamente
(function() {
    // Aguardar carregamento completo da página
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', limparCamposCadastro);
    } else {
        limparCamposCadastro();
    }
    
    function limparCamposCadastro() {
        // Limpar campos de email e senha em formulários de cadastro de usuário
        var forms = document.querySelectorAll('form[action*="cadastro"], form[action*="cadastro_usuario"]');
        forms.forEach(function(form) {
            var emailInput = form.querySelector('input[type="email"][name="email"]');
            var senhaInput = form.querySelector('input[type="password"][name="senha"]');
            
            if (emailInput && !emailInput.hasAttribute('data-keep-value')) {
                emailInput.value = '';
                emailInput.removeAttribute('readonly');
                emailInput.removeAttribute('disabled');
            }
            
            if (senhaInput && !senhaInput.hasAttribute('data-keep-value')) {
                senhaInput.value = '';
                senhaInput.removeAttribute('readonly');
                senhaInput.removeAttribute('disabled');
            }
        });
    }
})();
