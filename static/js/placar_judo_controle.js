// ============================================================
// 🥋 PLACAR DE JUDÔ - JavaScript de Controle
// ============================================================

let socket;

// Toast em vez de alert - mais visível
function showToast(mensagem, tipo = 'info') {
    const container = document.getElementById('placar-toast-container') || document.querySelector('.toast-container');
    if (!container) { alert(mensagem); return; }
    const id = 'toast-' + Date.now();
    const icons = { success: 'bi-check-circle-fill text-success', danger: 'bi-exclamation-triangle-fill text-danger', warning: 'bi-exclamation-circle-fill text-warning', info: 'bi-info-circle-fill text-info' };
    const icon = icons[tipo] || icons.info;
    const html = `
        <div id="${id}" class="toast toast-placar toast-${tipo}" role="alert" data-bs-autohide="true" data-bs-delay="4000">
            <div class="toast-header bg-white">
                <i class="bi ${icon} me-2"></i>
                <strong class="me-auto">${tipo === 'success' ? 'Sucesso' : tipo === 'danger' ? 'Erro' : tipo === 'warning' ? 'Atenção' : 'Informação'}</strong>
                <button type="button" class="btn-close" data-bs-dismiss="toast"></button>
            </div>
            <div class="toast-body">${mensagem.replace(/\n/g, '<br>')}</div>
        </div>`;
    container.insertAdjacentHTML('beforeend', html);
    const el = document.getElementById(id);
    if (el && typeof bootstrap !== 'undefined') {
        const t = new bootstrap.Toast(el, { delay: 4500 });
        t.show();
        el.addEventListener('hidden.bs.toast', () => el.remove());
    } else {
        el && el.remove();
        alert(mensagem);
    }
}
let intervalo_tempo;
let intervalo_osaekomi = null;
let ultimaLuta = null;
let osaekomi_base_elapsed = 0;
let osaekomi_base_time = 0;
let tempo_atual = TEMPO_RESTANTE;
let golden_score_ativo = GOLDEN_SCORE_ATIVADO;
let tempo_golden_score = TEMPO_GOLDEN_SCORE;
let luta_finalizada = false;
let _statusLutaAtual = typeof LUTA_STATUS !== 'undefined' ? LUTA_STATUS : 'aguardando';

function lutaPermitePontuacao() {
    return (
        (_statusLutaAtual === 'em_andamento' || _statusLutaAtual === 'pausada') &&
        !luta_finalizada
    );
}

// Conectar ao WebSocket
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOMContentLoaded - Inicializando placar');
    console.log('Variáveis:', { LUTA_ID, LUTA_STATUS, TEMPO_RESTANTE });
    
    if (!LUTA_ID) {
        console.error('LUTA_ID não definido! Verifique o template.');
        showToast('Erro: ID da luta não encontrado. Recarregue a página.', 'danger');
        return;
    }
    
    try {
        // Detectar URL base automaticamente
        const protocol = window.location.protocol === 'https:' ? 'https:' : 'http:';
        const host = window.location.host;
        const socketUrl = `${protocol}//${host}`;
        
        console.log('Conectando Socket.IO em:', socketUrl);
        
        socket = io(socketUrl, {
            transports: ['websocket', 'polling'],
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionAttempts: Infinity
        });
        console.log('Socket.IO inicializado');
        
        // Entrar na sala da luta
        socket.emit('join_luta', { luta_id: LUTA_ID });
        console.log('Entrou na sala da luta:', LUTA_ID);
        
        // Escutar atualizações do placar (ESTADO COMPLETO do backend)
        socket.on('placar_atualizado', function(luta) {
            // Backend envia estado completo calculado - frontend apenas renderiza
            if (luta && typeof luta === 'object') {
                console.log('📥 Recebido estado completo:', {
                    tempo: luta.tempo_restante_segundos,
                    status: luta.status,
                    id: luta.id || luta.luta_id
                });
                atualizarPlacar(luta);
            } else {
                console.warn('⚠️ Dados inválidos recebidos:', luta);
            }
        });
        
        socket.on('joined', function(data) {
            console.log('Confirmado: entrou na sala', data);
        });
        
        socket.on('connect', function() {
            console.log('WebSocket conectado');
        });
        
        socket.on('disconnect', function() {
            console.warn('WebSocket desconectado');
        });
        
        socket.on('connect_error', function(error) {
            console.error('Erro de conexão WebSocket:', error);
        });
        
        // Atualizar estado inicial
        atualizarEstado(LUTA_STATUS);

        const btnVoltar = document.getElementById('btn-voltar-placar');
        if (btnVoltar && btnVoltar.dataset.voltarHref) {
            btnVoltar.addEventListener('click', function () {
                if (btnVoltar.disabled) return;
                window.location.href = btnVoltar.dataset.voltarHref;
            });
        }

        // REMOVIDO: Não iniciar contador local - tempo vem do backend via WebSocket
        
        // Listeners diretos nos botões Osaekomi - mais confiável que delegação
        function handleOsaekomiClick(e) {
            const btn = e.currentTarget;
            if (btn.disabled) return;
            e.preventDefault();
            e.stopPropagation();
            if (btn.classList.contains('mm-osaekomi-ativo') || btn.classList.contains('btn-danger')) {
                osaekomiCancelar();
            } else {
                let lado = btn.id.includes('branco') ? 'branco' : 'azul';
                const trocado = document.getElementById('controle-martialmatch')?.getAttribute('data-trocado') === '1';
                if (trocado) lado = lado === 'branco' ? 'azul' : 'branco';
                osaekomiIniciar(lado);
            }
        }
        ['btn-osaekomi-branco', 'btn-osaekomi-azul', 'btn-osaekomi-branco-mm', 'btn-osaekomi-azul-mm'].forEach(function(id) {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener('click', handleOsaekomiClick, { passive: false, capture: false });
            }
        });
        
        // Adicionar event listeners aos botões de ponto (backup para onclick)
        document.querySelectorAll('.btn-ponto').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                
                // Extrair cor e tipo do onclick ou data attributes
                const onclick = this.getAttribute('onclick');
                if (onclick) {
                    // Se já tem onclick, não fazer nada (deixa o onclick funcionar)
                    return;
                }
                
                // Alternativa: usar data attributes
                const cor = this.dataset.cor;
                const tipo = this.dataset.tipo;
                if (cor && tipo) {
                    marcarPonto(cor, tipo, this);
                }
            });
        });
        
        console.log('Placar inicializado com sucesso');
    } catch (error) {
        console.error('Erro ao inicializar:', error);
        showToast('Erro ao inicializar o placar. Verifique o console.', 'danger');
    }
});

// Funções de controle da luta
function iniciarLuta() {
    console.log('iniciarLuta chamado', { LUTA_ID, luta_finalizada });
    
    if (luta_finalizada) {
        showToast('Luta já finalizada!', 'warning');
        return;
    }
    
    if (!LUTA_ID) {
        showToast('Erro: ID da luta não encontrado!', 'danger');
        console.error('LUTA_ID não definido');
        return;
    }
    
    const url = `/eventos-competicoes/placar-judo/${LUTA_ID}/api/atualizar`;
    console.log('Enviando requisição para:', url);
    
    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({ acao: 'iniciar' })
    })
    .then(response => {
        console.log('Resposta recebida:', response.status, response.statusText);
        if (!response.ok) {
            return response.json().then(err => {
                throw new Error(err.erro || `Erro HTTP: ${response.status}`);
            });
        }
        return response.json();
    })
    .then(data => {
        console.log('Dados recebidos:', data);
        if (data.sucesso) {
            atualizarEstado('em_andamento');
            iniciarContador();
            if (data.luta) {
                atualizarPlacar(data.luta);
            }
        } else {
            showToast('Erro: ' + (data.erro || 'Não foi possível iniciar a luta'), 'danger');
            console.error('Erro na resposta:', data);
        }
    })
    .catch(error => {
        console.error('Erro ao iniciar luta:', error);
        showToast('Erro ao iniciar a luta: ' + error.message, 'danger');
    });
}

function pausarLuta() {
    fetch(`/eventos-competicoes/placar-judo/${LUTA_ID}/api/atualizar`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ acao: 'pausar' })
    })
    .then(response => response.json())
    .then(data => {
        if (data.sucesso) {
            atualizarEstado('pausada');
            pararContador();
        }
    })
    .catch(error => {
        console.error('Erro:', error);
    });
}

function retomarLuta() {
    fetch(`/eventos-competicoes/placar-judo/${LUTA_ID}/api/atualizar`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ acao: 'retomar' })
    })
    .then(response => response.json())
    .then(data => {
        if (data.sucesso) {
            atualizarEstado('em_andamento');
            iniciarContador();
        }
    })
    .catch(error => {
        console.error('Erro:', error);
    });
}

function finalizarLuta() {
    const modal = new bootstrap.Modal(document.getElementById('modalFinalizar'));
    modal.show();
}

function confirmarFinalizar() {
    const vencedor = document.getElementById('vencedor-select').value;
    const tipo_vitoria = document.getElementById('tipo-vitoria-select').value;
    
    fetch(`/eventos-competicoes/placar-judo/${LUTA_ID}/api/atualizar`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ 
            acao: 'finalizar',
            vencedor: vencedor,
            tipo_vitoria: tipo_vitoria
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.sucesso) {
            atualizarEstado('finalizada');
            pararContador();
            bootstrap.Modal.getInstance(document.getElementById('modalFinalizar')).hide();
            showToast('Luta finalizada com sucesso!', 'success');
            if (data.proxima_luta_id) {
                const pid = data.proxima_luta_id;
                let url = `/eventos-competicoes/placar-judo/${pid}/controle`;
                if (typeof window !== 'undefined' && window.location.pathname.indexOf('/externo/') !== -1) {
                    const m = window.location.pathname.match(/\/externo\/(\d+)\//);
                    if (m) {
                        url = `/externo/${m[1]}/placar/${pid}/controle`;
                    }
                }
                setTimeout(function() { window.location.href = url; }, 600);
            }
        } else {
            showToast('Erro: ' + (data.erro || 'Não foi possível finalizar a luta'), 'danger');
        }
    })
    .catch(error => {
        console.error('Erro:', error);
        showToast('Erro ao finalizar a luta', 'danger');
    });
}

function resetarLuta() {
    if (!confirm('⚠️ ATENÇÃO: Isso irá resetar TODA a luta para o estado inicial.\n\nPontuação, tempo e status serão zerados.\n\nDeseja continuar?')) {
        return;
    }
    
    fetch(`/eventos-competicoes/placar-judo/${LUTA_ID}/api/resetar`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        credentials: 'same-origin'
    })
    .then(response => response.json())
    .then(data => {
        if (data.sucesso) {
            showToast('Luta resetada com sucesso!', 'success');
            // Manter modelo atual antes do reload
            const wrapper = document.getElementById('placar-controle-wrapper');
            const modeloAtual = wrapper ? wrapper.getAttribute('data-modelo') : 'unimaster';
            const fixo = wrapper && wrapper.getAttribute('data-controle-fixo') === '1';
            if (!fixo) {
                try { sessionStorage.setItem('placar_controle_modelo', modeloAtual); } catch (e) {}
            }
            // Recarregar página para garantir estado limpo
            window.location.reload();
        } else {
            showToast('Erro: ' + (data.erro || 'Não foi possível resetar a luta'), 'danger');
        }
    })
    .catch(error => {
        console.error('Erro ao resetar luta:', error);
        showToast('Erro ao resetar a luta: ' + error.message, 'danger');
    });
}

function toggleGoldenScore() {
    golden_score_ativo = !golden_score_ativo;
    
    fetch(`/eventos-competicoes/placar-judo/${LUTA_ID}/api/atualizar`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ 
            acao: 'golden_score',
            ativado: golden_score_ativo,
            tempo_golden_score: tempo_golden_score
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.sucesso && data.luta) {
            golden_score_ativo = data.luta.golden_score_ativado;
            tempo_golden_score = data.luta.tempo_golden_score_segundos || 0;
            atualizarDisplayGoldenScore();
        }
    })
    .catch(error => {
        console.error('Erro:', error);
    });
}

function marcarPonto(cor, tipo, eventElement) {
    console.log('marcarPonto chamado:', { cor, tipo, LUTA_ID, luta_finalizada });
    
    if (luta_finalizada) {
        showToast('Luta já finalizada!', 'warning');
        return;
    }

    if (!lutaPermitePontuacao()) {
        showToast('Inicie a luta (ou retome após pausa) para registrar pontuação.', 'warning');
        return;
    }
    
    if (!LUTA_ID) {
        showToast('Erro: ID da luta não encontrado!', 'danger');
        console.error('LUTA_ID não definido');
        return;
    }
    
    const acao = `${tipo}_${cor}`;
    const btn = eventElement ? eventElement.closest('.btn-ponto') : 
                (window.event ? window.event.target.closest('.btn-ponto') : null);
    
    console.log('Marcando ponto:', acao);
    
    // Feedback visual imediato
    if (btn) {
        btn.classList.add('ponto-animado');
        btn.style.opacity = '0.7';
        setTimeout(() => {
            btn.classList.remove('ponto-animado');
            btn.style.opacity = '1';
        }, 300);
    }
    
    const url = `/eventos-competicoes/placar-judo/${LUTA_ID}/api/atualizar`;
    console.log('Enviando requisição para:', url);
    
    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({ acao: acao })
    })
    .then(response => {
        console.log('Resposta recebida:', response.status);
        if (!response.ok) {
            return response.json().then(err => {
                throw new Error(err.erro || `Erro HTTP: ${response.status}`);
            });
        }
        return response.json();
    })
    .then(data => {
        console.log('Ponto marcado com sucesso:', data);
        if (data.sucesso) {
            // Feedback visual de sucesso
            if (btn) {
                btn.classList.add('btn-success');
                setTimeout(() => {
                    btn.classList.remove('btn-success');
                }, 500);
            }
            
            // Atualizar placar com dados recebidos
            if (data.luta) {
                atualizarPlacar(data.luta);
            }

            if (data.luta && data.luta.status === 'finalizada') {
                pararContador();
                const v = data.luta.vencedor;
                const vencedorTexto =
                    v === 'empate'
                        ? 'Empate'
                        : v === 'branco'
                          ? data.luta.atleta_branco_nome || 'BRANCO'
                          : data.luta.atleta_azul_nome || 'AZUL';
                const tv = (data.luta.tipo_vitoria || '').toLowerCase();
                let msg;
                if (v === 'empate') {
                    msg = 'Luta finalizada — empate.';
                } else if (tv === 'ippon') {
                    msg = `🏆 IPPON! Luta finalizada.\nVencedor: ${vencedorTexto}`;
                } else if (tv === 'golden_score') {
                    msg = `🏆 Luta finalizada (Golden Score).\nVencedor: ${vencedorTexto}`;
                } else if (tv === 'hansoku_make') {
                    msg = `Luta finalizada por Hansoku-make.\nVencedor: ${vencedorTexto}`;
                } else {
                    msg = `Luta finalizada.\nVencedor: ${vencedorTexto}`;
                }
                showToast(msg, 'success');
            }
            
            // Feedback de som (opcional - pode ser adicionado depois)
            // playSound('ponto');
        } else {
            showToast('Erro: ' + (data.erro || 'Não foi possível marcar o ponto'), 'danger');
            console.error('Erro na resposta:', data);
        }
    })
    .catch(error => {
        console.error('Erro ao marcar ponto:', error);
        showToast('Erro ao marcar ponto: ' + error.message, 'danger');
        
        // Reverter feedback visual em caso de erro
        if (btn) {
            btn.style.opacity = '1';
        }
    });
}

// REMOVIDO: Contador de tempo local - backend é a única fonte de verdade
// O tempo agora é calculado e enviado pelo backend via WebSocket
function iniciarContador() {
    // Não fazer nada - tempo vem do backend
    pararContador();
}

function pararContador() {
    if (intervalo_tempo) {
        clearInterval(intervalo_tempo);
        intervalo_tempo = null;
    }
}

function iniciarContadorOsaekomi(elapsed, lado) {
    if (intervalo_osaekomi) clearInterval(intervalo_osaekomi);
    osaekomi_base_elapsed = parseInt(elapsed) || 0;
    osaekomi_base_time = Date.now();
    intervalo_osaekomi = setInterval(function() {
        const seg = osaekomi_base_elapsed + Math.floor((Date.now() - osaekomi_base_time) / 1000);
        const m = Math.floor(seg / 60);
        const s = seg % 60;
        const fmt = (m > 0 ? m + ':' : '0:') + (s < 10 ? '0' : '') + s;
        ['osaekomi-timer-branco', 'osaekomi-timer-azul', 'osaekomi-timer-valor-branco-mm', 'osaekomi-timer-valor-azul-mm'].forEach(function(id) {
            const el = document.getElementById(id);
            if (el && ((lado === 'branco' && id.includes('branco')) || (lado === 'azul' && id.includes('azul')))) {
                el.textContent = fmt;
            }
        });
    }, 200);
}

function pararContadorOsaekomi() {
    if (intervalo_osaekomi) {
        clearInterval(intervalo_osaekomi);
        intervalo_osaekomi = null;
    }
}

// REMOVIDO: atualizarTempoServidor - tempo agora é calculado pelo backend

function atualizarDisplayTempo() {
    const display = document.getElementById('tempo-display');
    const displayMm = document.getElementById('tempo-display-mm');
    const gsLabel = document.getElementById('golden-score-label-controle');
    const gsLabelMm = document.getElementById('golden-score-label-mm');

    if (golden_score_ativo) {
        const minutos = Math.floor(tempo_golden_score / 60);
        const segundos = tempo_golden_score % 60;
        const tempoTexto = `${String(minutos).padStart(2, '0')}:${String(segundos).padStart(2, '0')}`;
        if (display) {
            display.textContent = tempoTexto;
            display.style.color = '#dc3545';
            display.classList.remove('text-primary');
        }
        if (displayMm) {
            displayMm.textContent = tempoTexto;
            displayMm.style.color = '#dc3545';
            displayMm.classList.add('tempo-golden-score');
        }
        if (gsLabel) gsLabel.style.display = 'block';
        if (gsLabelMm) gsLabelMm.style.display = 'block';
    } else {
        const minutos = Math.floor(tempo_atual / 60);
        const segundos = tempo_atual % 60;
        const tempoTexto = `${String(minutos).padStart(2, '0')}:${String(segundos).padStart(2, '0')}`;
        if (display) {
            display.textContent = tempoTexto;
            display.style.color = '';
            display.classList.add('text-primary');
        }
        if (displayMm) {
            displayMm.textContent = tempoTexto;
            displayMm.style.color = '';
            displayMm.classList.remove('tempo-golden-score');
        }
        if (gsLabel) gsLabel.style.display = 'none';
        if (gsLabelMm) gsLabelMm.style.display = 'none';
    }
}

function atualizarDisplayGoldenScore() {
    atualizarDisplayTempo();
}

function sincronizarBotoesAcaoPorStatus(status) {
    const podeUsarAcoesMesa = status === 'em_andamento' || status === 'pausada';
    const podeTrocarLados = status === 'aguardando';

    [
        'btn-finalizar',
        'btn-finalizar-mm',
        'btn-golden-score',
        'btn-golden-score-mm',
        'btn-resetar',
        'btn-resetar-mm',
    ].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.disabled = !podeUsarAcoesMesa;
    });

    document.querySelectorAll('#placar-controle-wrapper .btn-desfazer').forEach((el) => {
        el.disabled = !podeUsarAcoesMesa;
    });

    const btnTrocarLados = document.getElementById('btn-trocar-lados-mm');
    if (btnTrocarLados) {
        btnTrocarLados.disabled = !podeTrocarLados;
        btnTrocarLados.title = podeTrocarLados
            ? 'Trocar nomes: quem é Azul passa a ser Branco e vice-versa'
            : 'Troca de lados disponível apenas antes de iniciar a luta';
    }
}

function atualizarEstado(status) {
    console.log('Atualizando estado para:', status);
    _statusLutaAtual = status;

    const btnVoltarPlacar = document.getElementById('btn-voltar-placar');
    if (btnVoltarPlacar && btnVoltarPlacar.dataset.voltarHref) {
        const bloqueado = status === 'em_andamento';
        btnVoltarPlacar.disabled = bloqueado;
        btnVoltarPlacar.title = bloqueado
            ? 'Disponível quando a luta não estiver em andamento'
            : 'Volta à lista do placar e coloca a TV da área em espera (área + aguardando luta)';
    }

    const btnIniciar = document.getElementById('btn-iniciar');
    const btnPausar = document.getElementById('btn-pausar');
    const btnRetomar = document.getElementById('btn-retomar');
    const btnFinalizar = document.getElementById('btn-finalizar');
    const btnIniciarMm = document.getElementById('btn-iniciar-mm');
    const btnPausarMm = document.getElementById('btn-pausar-mm');
    const btnRetomarMm = document.getElementById('btn-retomar-mm');
    const btnFinalizarMm = document.getElementById('btn-finalizar-mm');
    
    const setVisibility = (showIniciar, showPausar, showRetomar) => {
        if (btnIniciar) btnIniciar.style.display = showIniciar ? 'inline-block' : 'none';
        if (btnPausar) btnPausar.style.display = showPausar ? 'inline-block' : 'none';
        if (btnRetomar) btnRetomar.style.display = showRetomar ? 'inline-block' : 'none';
        if (btnIniciarMm) btnIniciarMm.style.display = showIniciar ? 'inline-block' : 'none';
        if (btnPausarMm) btnPausarMm.style.display = showPausar ? 'inline-block' : 'none';
        if (btnRetomarMm) btnRetomarMm.style.display = showRetomar ? 'inline-block' : 'none';
    };
    
    if (!btnIniciar || !btnPausar || !btnRetomar || !btnFinalizar) {
        console.error('Botões não encontrados!', {
            btnIniciar: !!btnIniciar,
            btnPausar: !!btnPausar,
            btnRetomar: !!btnRetomar,
            btnFinalizar: !!btnFinalizar
        });
        return;
    }
    
    setVisibility(false, false, false);
    
    if (status === 'aguardando') {
        setVisibility(true, false, false);
        console.log('Mostrando botão Iniciar');
    } else if (status === 'em_andamento') {
        setVisibility(false, true, false);
        if (golden_score_ativo) atualizarDisplayGoldenScore();
        console.log('Mostrando botão Pausar');
    } else if (status === 'pausada') {
        setVisibility(false, false, true);
        console.log('Mostrando botão Retomar');
    } else if (status === 'finalizada') {
        luta_finalizada = true;
        pararContador();
        console.log('Luta finalizada');
    } else {
        luta_finalizada = false;
    }
    sincronizarBotoesAcaoPorStatus(status);

    const posVitoria = document.getElementById('controle-pos-vitoria-row');
    if (posVitoria) {
        posVitoria.style.display = status === 'finalizada' ? 'block' : 'none';
    }

    const podePontosUi = lutaPermitePontuacao();
    const wrapPlacarEstado = document.getElementById('placar-controle-wrapper');
    if (wrapPlacarEstado) {
        wrapPlacarEstado.classList.toggle('placar-pontos-bloqueados', !podePontosUi);
    }
    document
        .querySelectorAll(
            '.controle-unimaster button.btn-ponto.btn-adicionar, .controle-unimaster button.btn-ponto.btn-remover'
        )
        .forEach((b) => {
            b.disabled = !podePontosUi;
        });
    document.querySelectorAll('#placar-controle-wrapper .btn-desfazer').forEach((b) => {
        b.disabled = !podePontosUi || b.disabled;
    });
    if (!podePontosUi) {
        ['btn-osaekomi-branco', 'btn-osaekomi-azul', 'btn-osaekomi-branco-mm', 'btn-osaekomi-azul-mm'].forEach(
            (id) => {
                const el = document.getElementById(id);
                if (el) el.disabled = true;
            }
        );
    }
}

// Desfazer última ação (usa backend para descobrir o último ponto/penalidade e reverter)
function desfazerUltimaAcao() {
    if (!LUTA_ID) {
        showToast('Erro: ID da luta não encontrado!', 'danger');
        return;
    }

    if (!lutaPermitePontuacao()) {
        showToast('Inicie a luta para poder desfazer pontuação.', 'warning');
        return;
    }

    if (!confirm('Deseja desfazer a última pontuação/penalidade registrada?')) {
        return;
    }

    fetch(`/eventos-competicoes/placar-judo/${LUTA_ID}/api/atualizar`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({ acao: 'desfazer_ultima_acao' })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(err => {
                throw new Error(err.erro || `Erro HTTP: ${response.status}`);
            });
        }
        return response.json();
    })
    .then(data => {
        if (data.sucesso && data.luta) {
            atualizarPlacar(data.luta);
        } else {
            showToast('Erro: ' + (data.erro || 'Não foi possível desfazer a última ação'), 'danger');
        }
    })
    .catch(error => {
        console.error('Erro ao desfazer última ação:', error);
        showToast('Erro ao desfazer última ação: ' + error.message, 'danger');
    });
}

window.desfazerUltimaAcao = desfazerUltimaAcao;

function atualizarPlacar(luta) {
    console.log('Atualizando placar com dados:', luta);
    ultimaLuta = luta;

    const podePontuar =
        (luta.status === 'em_andamento' || luta.status === 'pausada') && luta.status !== 'finalizada';
    const wrapPlacar = document.getElementById('placar-controle-wrapper');
    if (wrapPlacar) wrapPlacar.classList.toggle('placar-pontos-bloqueados', !podePontuar);
    
    const trocado = document.getElementById('controle-martialmatch')?.getAttribute('data-trocado') === '1';
    
    // Atualizar pontuação: Unimaster sempre normal; MM aplica trocado
    const updUnimaster = (id, val) => {
        const v = val !== undefined && val !== null ? String(val) : '0';
        const el = document.getElementById(id);
        if (el) el.textContent = v;
    };
    const updMm = (id, val) => {
        const v = val !== undefined && val !== null ? String(val) : '0';
        const el = document.getElementById(id + '-mm');
        if (el) el.textContent = v;
    };
    updUnimaster('ippon-branco', luta.pontos_branco_ippon);
    updUnimaster('wazaari-branco', luta.pontos_branco_wazaari);
    updUnimaster('shido-branco', luta.pontos_branco_shido);
    updUnimaster('yoko-branco', luta.pontos_branco_yoko);
    updUnimaster('ippon-azul', luta.pontos_azul_ippon);
    updUnimaster('wazaari-azul', luta.pontos_azul_wazaari);
    updUnimaster('shido-azul', luta.pontos_azul_shido);
    updUnimaster('yoko-azul', luta.pontos_azul_yoko);
    if (trocado) {
        updMm('ippon-branco', luta.pontos_azul_ippon);
        updMm('wazaari-branco', luta.pontos_azul_wazaari);
        updMm('shido-branco', luta.pontos_azul_shido);
        updMm('yoko-branco', luta.pontos_azul_yoko);
        updMm('ippon-azul', luta.pontos_branco_ippon);
        updMm('wazaari-azul', luta.pontos_branco_wazaari);
        updMm('shido-azul', luta.pontos_branco_shido);
        updMm('yoko-azul', luta.pontos_branco_yoko);
    } else {
        updMm('ippon-branco', luta.pontos_branco_ippon);
        updMm('wazaari-branco', luta.pontos_branco_wazaari);
        updMm('shido-branco', luta.pontos_branco_shido);
        updMm('yoko-branco', luta.pontos_branco_yoko);
        updMm('ippon-azul', luta.pontos_azul_ippon);
        updMm('wazaari-azul', luta.pontos_azul_wazaari);
        updMm('shido-azul', luta.pontos_azul_shido);
        updMm('yoko-azul', luta.pontos_azul_yoko);
    }
    
    // ATUALIZAR TEMPO - Backend é ÚNICA fonte de verdade
    // Frontend NÃO calcula, apenas renderiza o valor recebido
    const novoTempo = parseInt(luta.tempo_restante_segundos) || 0;
    if (novoTempo !== tempo_atual) {
        console.log('⏱️ Tempo mudou:', tempo_atual, '->', novoTempo);
        tempo_atual = novoTempo;
        atualizarDisplayTempo();
    } else {
        // Mesmo valor, mas garantir que display está atualizado
        atualizarDisplayTempo();
    }
    
    // Atualizar Golden Score (backend calcula)
    const golden_score_anterior = golden_score_ativo;
    const tempo_golden_score_anterior = tempo_golden_score;
    golden_score_ativo = luta.golden_score_ativado || false;
    tempo_golden_score = parseInt(luta.tempo_golden_score_segundos) || 0;
    
    // Log quando golden score for ativado automaticamente
    if (!golden_score_anterior && golden_score_ativo) {
        console.log('🏆 Golden Score ativado automaticamente após contagem chegar a zero!');
    }
    
    // Log quando tempo do golden score mudar (para debug)
    if (golden_score_ativo && tempo_golden_score !== tempo_golden_score_anterior) {
        console.log(`⏱️ Golden Score tempo atualizado: ${tempo_golden_score_anterior}s -> ${tempo_golden_score}s`);
    }
    
    atualizarDisplayGoldenScore();

    const setTxt = (id, text) => {
        const el = document.getElementById(id);
        if (el && text != null) el.textContent = text;
    };
    setTxt('controle-nome-branco', luta.atleta_branco_nome);
    setTxt('controle-nome-azul', luta.atleta_azul_nome);
    const cb = document.getElementById('controle-academia-branco');
    const ca = document.getElementById('controle-academia-azul');
    if (cb) {
        const t = (luta.atleta_branco_academia || '').trim();
        cb.textContent = t;
        cb.style.display = t ? 'block' : 'none';
    }
    if (ca) {
        const t = (luta.atleta_azul_academia || '').trim();
        ca.textContent = t;
        ca.style.display = t ? 'block' : 'none';
    }
    const mmNb = document.querySelector('.mm-strip-branco .mm-nome');
    const mmNa = document.querySelector('.mm-strip-azul .mm-nome');
    const mmAb = document.querySelector('.mm-strip-branco .mm-academia');
    const mmAa = document.querySelector('.mm-strip-azul .mm-academia');
    if (mmNb && luta.atleta_branco_nome != null) mmNb.textContent = luta.atleta_branco_nome;
    if (mmNa && luta.atleta_azul_nome != null) mmNa.textContent = luta.atleta_azul_nome;
    if (mmAb) mmAb.textContent = (luta.atleta_branco_academia || '').toUpperCase();
    if (mmAa) mmAa.textContent = (luta.atleta_azul_academia || '').toUpperCase();
    const selV = document.getElementById('vencedor-select');
    if (selV && luta.atleta_branco_nome && luta.atleta_azul_nome) {
        const o0 = selV.querySelector('option[value="branco"]');
        const o1 = selV.querySelector('option[value="azul"]');
        if (o0) o0.textContent = luta.atleta_branco_nome + ' (Branco)';
        if (o1) o1.textContent = luta.atleta_azul_nome + ' (Azul)';
    }
    
    // Osaekomi: nome no botão = OSAEKOMI (iniciar) ou TOKETA (parar); mesmo layout - e + ao lado
    const osaekomiAtivo = !!luta.osaekomi_ativo;
    const osaekomiLado = (luta.osaekomi_lado || '').toLowerCase();
    const osaekomiElapsed = parseInt(luta.osaekomi_elapsed_seconds) || 0;
    const m = Math.floor(osaekomiElapsed / 60);
    const s = osaekomiElapsed % 60;
    const osaekomiFmt = (m > 0 ? m + ':' : '0:') + (s < 10 ? '0' : '') + s;
    const brancoBtn = document.getElementById('btn-osaekomi-branco');
    if (brancoBtn) {
        if (!podePontuar) {
            brancoBtn.textContent = 'OSAEKOMI';
            brancoBtn.className = 'btn btn-outline-dark btn-lg btn-ponto';
            brancoBtn.disabled = true;
        } else if (osaekomiAtivo && osaekomiLado === 'branco') {
            brancoBtn.textContent = 'TOKETA';
            brancoBtn.className = 'btn btn-danger btn-lg btn-ponto';
            brancoBtn.disabled = false;
        } else {
            brancoBtn.textContent = 'OSAEKOMI';
            brancoBtn.className = 'btn btn-outline-dark btn-lg btn-ponto';
            brancoBtn.disabled = osaekomiAtivo;
        }
    }
    const azulBtn = document.getElementById('btn-osaekomi-azul');
    if (azulBtn) {
        if (!podePontuar) {
            azulBtn.textContent = 'OSAEKOMI';
            azulBtn.className = 'btn btn-outline-primary btn-lg btn-ponto';
            azulBtn.disabled = true;
        } else if (osaekomiAtivo && osaekomiLado === 'azul') {
            azulBtn.textContent = 'TOKETA';
            azulBtn.className = 'btn btn-danger btn-lg btn-ponto';
            azulBtn.disabled = false;
        } else {
            azulBtn.textContent = 'OSAEKOMI';
            azulBtn.className = 'btn btn-outline-primary btn-lg btn-ponto';
            azulBtn.disabled = osaekomiAtivo;
        }
    }
    const timerBrancoEl = document.getElementById('osaekomi-timer-branco');
    const timerAzulEl = document.getElementById('osaekomi-timer-azul');
    if (timerBrancoEl) {
        timerBrancoEl.textContent = osaekomiFmt;
        timerBrancoEl.style.display = (osaekomiAtivo && osaekomiLado === 'branco') ? '' : 'none';
    }
    if (timerAzulEl) {
        timerAzulEl.textContent = osaekomiFmt;
        timerAzulEl.style.display = (osaekomiAtivo && osaekomiLado === 'azul') ? '' : 'none';
    }
    
    // MartialMatch: Osaekomi flutuante perto de cada strip
    const osaekomiBoxBrancoMm = document.getElementById('osaekomi-timer-box-branco-mm');
    const osaekomiBoxAzulMm = document.getElementById('osaekomi-timer-box-azul-mm');
    const osaekomiValorBrancoMm = document.getElementById('osaekomi-timer-valor-branco-mm');
    const osaekomiValorAzulMm = document.getElementById('osaekomi-timer-valor-azul-mm');
    const brancoBtnMm = document.getElementById('btn-osaekomi-branco-mm');
    const azulBtnMm = document.getElementById('btn-osaekomi-azul-mm');
    if (osaekomiBoxBrancoMm) osaekomiBoxBrancoMm.classList.toggle('active', osaekomiAtivo && (trocado ? osaekomiLado === 'azul' : osaekomiLado === 'branco'));
    if (osaekomiBoxAzulMm) osaekomiBoxAzulMm.classList.toggle('active', osaekomiAtivo && (trocado ? osaekomiLado === 'branco' : osaekomiLado === 'azul'));
    if (osaekomiValorBrancoMm) osaekomiValorBrancoMm.textContent = osaekomiFmt;
    if (osaekomiValorAzulMm) osaekomiValorAzulMm.textContent = osaekomiFmt;
    // Osaekomi timer local: quando trocado, branco strip mostra azul
    if (osaekomiAtivo && osaekomiLado) {
        const ladoDisplay = trocado ? (osaekomiLado === 'branco' ? 'azul' : 'branco') : osaekomiLado;
        iniciarContadorOsaekomi(osaekomiElapsed, ladoDisplay);
    } else {
        pararContadorOsaekomi();
    }
    const brancoMostraAzul = trocado;
    const azulMostraBranco = trocado;
    if (brancoBtnMm) {
        const ativo = osaekomiAtivo && (brancoMostraAzul ? osaekomiLado === 'azul' : osaekomiLado === 'branco');
        if (ativo) {
            brancoBtnMm.innerHTML = '<i class="bi bi-stop-circle-fill"></i>';
            brancoBtnMm.className = 'mm-osaekomi-btn mm-osaekomi-btn-branco mm-osaekomi-ativo';
        } else {
            brancoBtnMm.innerHTML = '<i class="bi bi-stopwatch"></i>';
            brancoBtnMm.className = 'mm-osaekomi-btn mm-osaekomi-btn-branco';
        }
        brancoBtnMm.disabled = !podePontuar || (osaekomiAtivo && !ativo);
    }
    if (azulBtnMm) {
        const ativo = osaekomiAtivo && (azulMostraBranco ? osaekomiLado === 'branco' : osaekomiLado === 'azul');
        if (ativo) {
            azulBtnMm.innerHTML = '<i class="bi bi-stop-circle-fill"></i>';
            azulBtnMm.className = 'mm-osaekomi-btn mm-osaekomi-btn-azul mm-osaekomi-ativo';
        } else {
            azulBtnMm.innerHTML = '<i class="bi bi-stopwatch"></i>';
            azulBtnMm.className = 'mm-osaekomi-btn mm-osaekomi-btn-azul';
        }
        azulBtnMm.disabled = !podePontuar || (osaekomiAtivo && !ativo);
    }

    document
        .querySelectorAll(
            '.controle-unimaster button.btn-ponto.btn-adicionar, .controle-unimaster button.btn-ponto.btn-remover'
        )
        .forEach((b) => {
            b.disabled = !podePontuar;
        });
    document.querySelectorAll('#placar-controle-wrapper .btn-desfazer').forEach((b) => {
        b.disabled = !podePontuar;
    });
    
    // Atualizar estado
    atualizarEstado(luta.status);
    
    // Parar qualquer contador local (não deve existir, mas por segurança)
    pararContador();
    
    // Não iniciar contador local - tempo vem do backend via WebSocket
}

// Função para remover ponto
function removerPonto(cor, tipo, eventElement) {
    console.log('removerPonto chamado:', { cor, tipo, LUTA_ID });
    
    if (!LUTA_ID) {
        showToast('Erro: ID da luta não encontrado!', 'danger');
        return;
    }

    if (!lutaPermitePontuacao()) {
        showToast('Inicie a luta para alterar pontuação.', 'warning');
        return;
    }
    
    const btn = eventElement || (window.event ? window.event.target.closest('.btn-remover') : null);
    
    const url = `/eventos-competicoes/placar-judo/${LUTA_ID}/api/atualizar`;
    
    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({ 
            acao: 'desfazer_ponto',
            tipo_ponto: tipo,
            cor: cor
        })
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(err => {
                throw new Error(err.erro || `Erro HTTP: ${response.status}`);
            });
        }
        return response.json();
    })
    .then(data => {
        console.log('Ponto removido:', data);
        if (data.sucesso) {
            // Feedback visual
            if (btn) {
                btn.classList.add('btn-success');
                setTimeout(() => {
                    btn.classList.remove('btn-success');
                }, 300);
            }
            
            // Atualizar placar
            if (data.luta) {
                atualizarPlacar(data.luta);
            }
        } else {
            showToast('Erro: ' + (data.erro || 'Não foi possível remover o ponto'), 'danger');
        }
    })
    .catch(error => {
        console.error('Erro ao remover ponto:', error);
        showToast('Erro ao remover ponto: ' + error.message, 'danger');
    });
}

function osaekomiIniciar(lado) {
    if (!LUTA_ID) { showToast('Erro: ID da luta não encontrado.', 'danger'); return; }
    if (!lutaPermitePontuacao()) {
        showToast('Inicie a luta para usar Osaekomi.', 'warning');
        return;
    }
    const url = `/eventos-competicoes/placar-judo/${LUTA_ID}/api/atualizar`;
    fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ acao: 'osaekomi_iniciar', lado: lado })
    })
    .then(r => r.ok ? r.json() : r.json().then(e => { throw new Error(e.erro || r.status); }))
    .then(data => {
        if (data.sucesso && data.luta) atualizarPlacar(data.luta);
        else if (data.erro) showToast(data.erro, 'danger');
    })
    .catch(e => { console.error(e); showToast('Osaekomi: ' + e.message, 'danger'); });
}

function osaekomiCancelar() {
    if (!LUTA_ID) { showToast('Erro: ID da luta não encontrado.', 'danger'); return; }
    if (!lutaPermitePontuacao()) {
        showToast('Inicie a luta para usar Osaekomi.', 'warning');
        return;
    }
    const url = `/eventos-competicoes/placar-judo/${LUTA_ID}/api/atualizar`;
    fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ acao: 'osaekomi_cancelar' })
    })
    .then(r => r.ok ? r.json() : r.json().then(e => { throw new Error(e.erro || r.status); }))
    .then(data => {
        if (data.sucesso && data.luta) atualizarPlacar(data.luta);
        else if (data.erro) showToast(data.erro, 'danger');
    })
    .catch(e => { console.error(e); showToast('Cancelar Osaekomi: ' + e.message, 'danger'); });
}

// Tornar funções globais para acesso via onclick
window.marcarPonto = marcarPonto;
window.removerPonto = removerPonto;
window.osaekomiIniciar = osaekomiIniciar;
window.osaekomiCancelar = osaekomiCancelar;
window.resetarLuta = resetarLuta;
window.iniciarLuta = iniciarLuta;
window.pausarLuta = pausarLuta;
window.retomarLuta = retomarLuta;
window.finalizarLuta = finalizarLuta;
window.confirmarFinalizar = confirmarFinalizar;
window.toggleGoldenScore = toggleGoldenScore;

// Tela cheia do placar (controle)
function toggleFullscreenPlacarControle() {
    try {
        const doc = document;
        const docEl = doc.documentElement;
        const isFullscreen = doc.fullscreenElement || doc.webkitFullscreenElement || doc.mozFullScreenElement || doc.msFullscreenElement;

        if (!isFullscreen) {
            if (docEl.requestFullscreen) {
                docEl.requestFullscreen();
            } else if (docEl.webkitRequestFullscreen) {
                docEl.webkitRequestFullscreen();
            } else if (docEl.mozRequestFullScreen) {
                docEl.mozRequestFullScreen();
            } else if (docEl.msRequestFullscreen) {
                docEl.msRequestFullscreen();
            }
        } else {
            if (doc.exitFullscreen) {
                doc.exitFullscreen();
            } else if (doc.webkitExitFullscreen) {
                doc.webkitExitFullscreen();
            } else if (doc.mozCancelFullScreen) {
                doc.mozCancelFullScreen();
            } else if (doc.msExitFullscreen) {
                doc.msExitFullscreen();
            }
        }
        document.body.classList.toggle('placar-fullscreen');
    } catch (e) {
        console.error('Erro ao alternar tela cheia do placar (controle):', e);
    }
}

window.toggleFullscreenPlacarControle = toggleFullscreenPlacarControle;

// Modelo MartialMatch: clique no card adiciona ponto
function marcarPontoCardMm(event, cor, tipo) {
    if (event && event.target && event.target.closest && event.target.closest('.mm-card-remover')) return;
    const trocado = document.getElementById('controle-martialmatch')?.getAttribute('data-trocado') === '1';
    const corEfetiva = trocado ? (cor === 'branco' ? 'azul' : 'branco') : cor;
    marcarPonto(corEfetiva, tipo, null);
}
window.marcarPontoCardMm = marcarPontoCardMm;

function removerPontoCardMm(cor, tipo, el) {
    const trocado = document.getElementById('controle-martialmatch')?.getAttribute('data-trocado') === '1';
    const corEfetiva = trocado ? (cor === 'branco' ? 'azul' : 'branco') : cor;
    removerPonto(corEfetiva, tipo, el);
}
window.removerPontoCardMm = removerPontoCardMm;
