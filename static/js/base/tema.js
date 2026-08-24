/* =====================================================================
   Modo noturno + inicialização dos toasts
   =====================================================================
   Extraído do <script> inline do base.html. As funções seguem globais
   (toggleDarkMode é chamada por onclick nos botões das duas bases).
   ===================================================================== */

document.addEventListener("DOMContentLoaded", () => {
    const toastElList = document.querySelectorAll(".toast");
    toastElList.forEach((toastEl) => {
        const toast = new bootstrap.Toast(toastEl);
        toast.show();
    });
    
    // Inicializar modo noturno
    initDarkMode();
});

// Função para alternar modo noturno
function toggleDarkMode() {
    const html = document.documentElement;
    const isDark = html.classList.toggle('dark-mode');
    
    // Salvar preferência no localStorage
    localStorage.setItem('darkMode', isDark ? 'enabled' : 'disabled');
    
    // Atualizar ícones
    updateDarkModeIcons(isDark);
}

// Função para inicializar modo noturno ao carregar a página
function initDarkMode() {
    const darkMode = localStorage.getItem('darkMode');
    const html = document.documentElement;
    
    if (darkMode === 'enabled') {
        html.classList.add('dark-mode');
        updateDarkModeIcons(true);
    } else {
        html.classList.remove('dark-mode');
        updateDarkModeIcons(false);
    }
}

// Função para atualizar ícones do modo noturno
function updateDarkModeIcons(isDark) {
    const iconMobile = document.getElementById('iconDarkModeMobile');
    const iconDesktop = document.getElementById('iconDarkModeDesktop');
    
    if (iconMobile) {
        iconMobile.className = isDark ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
    }
    if (iconDesktop) {
        iconDesktop.className = isDark ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
    }
}
