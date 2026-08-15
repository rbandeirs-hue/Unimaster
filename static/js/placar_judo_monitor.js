// ============================================================
// 🥋 PLACAR DE JUDÔ - JavaScript do Monitor (Visualização)
// ============================================================

let socket;
let intervalo_tempo;
let tempo_atual = typeof TEMPO_INICIAL !== 'undefined' ? TEMPO_INICIAL : 0;
let golden_score_ativo = typeof GOLDEN_SCORE_INICIAL !== 'undefined' ? GOLDEN_SCORE_INICIAL : false;
let tempo_golden_score = typeof TEMPO_GS_INICIAL !== 'undefined' ? TEMPO_GS_INICIAL : 0;
let _monitorUltimoStatus = null;
let _standbyEncerramentoInterval = null;

function cancelarEncerramentoPendente() {
    if (_standbyEncerramentoInterval) {
        clearInterval(_standbyEncerramentoInterval);
        _standbyEncerramentoInterval = null;
    }
    const wrap = document.getElementById('monitor-encerramento-countdown');
    if (wrap) wrap.style.display = 'none';
}

function vencedorVisivelNoDOM() {
    const vb = document.querySelector('.vencedor-banner');
    if (!vb) return false;
    const st = window.getComputedStyle(vb);
    return st.display !== 'none' && st.visibility !== 'hidden' && parseFloat(st.opacity || '1') > 0.05;
}

function executarTransicaoStandby(anStandby, msg) {
    cancelarEncerramentoPendente();
    const acoesFim = document.getElementById('monitor-pos-vitoria-acoes');
    if (acoesFim) acoesFim.style.display = 'none';
    if (socket && LUTA_ID) {
        socket.emit('leave_luta', { luta_id: LUTA_ID });
    }
    LUTA_ID = 0;
    mostrarStandbyMonitor(msg, anStandby);
    esconderVencedor();
}

/** Monitor por área: volta à tela de espera. Monitor por luta: redireciona à lista do evento. */
function fecharPlacarVoltarLista() {
    cancelarEncerramentoPendente();
    const porArea = typeof MONITOR_POR_AREA !== 'undefined' && MONITOR_POR_AREA;
    if (porArea) {
        const an =
            typeof AREA_MONITOR_NUM !== 'undefined' && AREA_MONITOR_NUM != null
                ? AREA_MONITOR_NUM
                : null;
        executarTransicaoStandby(an, 'Aguardando próxima luta');
        return;
    }
    const url =
        typeof MONITOR_VOLTAR_LISTA_URL === 'string' && MONITOR_VOLTAR_LISTA_URL
            ? MONITOR_VOLTAR_LISTA_URL
            : null;
    if (url) {
        window.location.href = url;
        return;
    }
    const acoes = document.getElementById('monitor-pos-vitoria-acoes');
    if (acoes) acoes.style.display = 'none';
    esconderVencedor();
}

window.fecharPlacarVoltarLista = fecharPlacarVoltarLista;

function aplicarPlacarVisualEsperaArea(areaNum) {
    const ev = typeof EVENTO_NOME_MONITOR !== 'undefined' ? EVENTO_NOME_MONITOR : '';
    const dur = typeof TEMPO_INICIAL !== 'undefined' ? TEMPO_INICIAL : 300;
    const cat = areaNum != null && areaNum !== '' ? 'ÁREA ' + String(areaNum) : '';
    atualizarPlacar({
        evento_nome: ev,
        atleta_branco_nome: '—',
        atleta_azul_nome: '—',
        atleta_branco_academia: '',
        atleta_azul_academia: '',
        categoria_nome: cat,
        tempo_restante_segundos: dur,
        status: 'aguardando',
        golden_score_ativado: false,
        tempo_golden_score_segundos: 0,
        pontos_branco_ippon: 0,
        pontos_branco_wazaari: 0,
        pontos_branco_yoko: 0,
        pontos_branco_shido: 0,
        pontos_azul_ippon: 0,
        pontos_azul_wazaari: 0,
        pontos_azul_yoko: 0,
        pontos_azul_shido: 0,
        pontos_branco_hansokumake: 0,
        pontos_azul_hansokumake: 0,
        osaekomi_ativo: false,
        osaekomi_lado: '',
        osaekomi_elapsed_seconds: 0,
        vencedor: null,
        tipo_vitoria: null,
    });
}

function mostrarStandbyMonitor(mensagem, areaNum) {
    const el = document.getElementById('placar-monitor-standby');
    if (!el) return;
    const an = areaNum != null && areaNum !== ''
        ? areaNum
        : (typeof AREA_MONITOR_NUM !== 'undefined' && AREA_MONITOR_NUM != null ? AREA_MONITOR_NUM : null);
    const numEl = el.querySelector('.placar-standby-numero');
    const labelEl = el.querySelector('.placar-standby-label');
    if (labelEl && an != null) {
        labelEl.textContent = 'ÁREA';
        labelEl.style.display = '';
    }
    if (numEl != null && an != null) {
        numEl.textContent = String(an);
        numEl.style.display = '';
    }
    const t = el.querySelector('.placar-standby-mensagem');
    if (t && mensagem) t.textContent = mensagem;
    if (typeof MONITOR_POR_AREA !== 'undefined' && MONITOR_POR_AREA && an != null) {
        aplicarPlacarVisualEsperaArea(an);
    }
    el.style.display = 'flex';
}

function esconderStandbyMonitor() {
    const el = document.getElementById('placar-monitor-standby');
    if (el) el.style.display = 'none';
}

function trocarSalaMonitorParaLuta(novoLutaId, lutaCompleta) {
    if (!socket || !novoLutaId) return;
    if (LUTA_ID && LUTA_ID !== novoLutaId) {
        socket.emit('leave_luta', { luta_id: LUTA_ID });
    }
    LUTA_ID = novoLutaId;
    socket.emit('join_luta', { luta_id: LUTA_ID });
    if (lutaCompleta && typeof lutaCompleta === 'object') {
        esconderVencedor();
        atualizarPlacar(lutaCompleta);
    }
}

// Conectar ao WebSocket
document.addEventListener('DOMContentLoaded', function() {
    console.log('Monitor - Inicializando...', { LUTA_ID, EVENTO_MONITOR_ID, MONITOR_POR_AREA, AREA_MONITOR_NUM });

    if (typeof ERRO_MONITOR_HTML !== 'undefined' && ERRO_MONITOR_HTML) {
        return;
    }

    const porArea = typeof MONITOR_POR_AREA !== 'undefined' && MONITOR_POR_AREA;
    if (porArea) {
        if (EVENTO_MONITOR_ID == null || typeof AREA_MONITOR_NUM === 'undefined' || AREA_MONITOR_NUM == null) {
            console.error('Monitor por área: evento_id / area_num obrigatórios.');
            return;
        }
    } else if (!LUTA_ID && EVENTO_MONITOR_ID == null) {
        console.error('LUTA_ID / evento não definido!');
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
            reconnectionAttempts: Infinity,
            timeout: 5000,
            forceNew: false
        });
        
        console.log('Socket.IO inicializado');

        function entrarSalasMonitor() {
            if (porArea) {
                socket.emit('join_placar_area', { evento_id: EVENTO_MONITOR_ID, area_num: AREA_MONITOR_NUM });
            } else if (EVENTO_MONITOR_ID != null) {
                socket.emit('join_evento_placar', { evento_id: EVENTO_MONITOR_ID });
            }
            if (LUTA_ID) {
                socket.emit('join_luta', { luta_id: LUTA_ID });
                console.log('Solicitado entrada na sala da luta:', LUTA_ID);
            }
        }
        entrarSalasMonitor();

        socket.on('placar_monitor_area', function(payload) {
            if (!porArea || !payload || typeof payload !== 'object') return;
            if (parseInt(payload.evento_id, 10) !== parseInt(EVENTO_MONITOR_ID, 10)) return;
            if (parseInt(payload.area_num, 10) !== parseInt(AREA_MONITOR_NUM, 10)) return;
            if (payload.modo === 'standby') {
                cancelarEncerramentoPendente();
                const anStandby = payload.area_num != null ? payload.area_num : AREA_MONITOR_NUM;
                const msg = payload.mensagem || 'Aguardando próxima luta';
                const pausaSeg = typeof MONITOR_PAUSA_APOS_VITORIA_SEG === 'number'
                    ? MONITOR_PAUSA_APOS_VITORIA_SEG
                    : 12;
                const precisaPausa = _monitorUltimoStatus === 'finalizada' || vencedorVisivelNoDOM();
                if (precisaPausa && pausaSeg > 0) {
                    let left = Math.round(pausaSeg);
                    const wrap = document.getElementById('monitor-encerramento-countdown');
                    const span = document.getElementById('monitor-encerramento-seg');
                    if (wrap) {
                        wrap.style.display = 'flex';
                        if (span) span.textContent = String(left);
                    }
                    _standbyEncerramentoInterval = setInterval(function () {
                        left -= 1;
                        if (span) span.textContent = String(Math.max(0, left));
                        if (left <= 0) {
                            clearInterval(_standbyEncerramentoInterval);
                            _standbyEncerramentoInterval = null;
                            executarTransicaoStandby(anStandby, msg);
                        }
                    }, 1000);
                } else {
                    executarTransicaoStandby(anStandby, msg);
                }
                return;
            }
            if (payload.modo === 'luta' && payload.luta_id) {
                cancelarEncerramentoPendente();
                esconderStandbyMonitor();
                trocarSalaMonitorParaLuta(payload.luta_id, payload.luta);
            }
        });
        
        socket.on('placar_monitor_evento', function(payload) {
            if (porArea) return;
            if (!payload || typeof payload !== 'object') return;
            if (EVENTO_MONITOR_ID == null || payload.evento_id !== EVENTO_MONITOR_ID) return;
            const nid = payload.luta_id;
            const nl = payload.luta;
            console.log('📺 Monitor evento: trocar para luta', nid);
            trocarSalaMonitorParaLuta(nid, nl);
        });
        
        // Escutar atualizações do placar (ESTADO COMPLETO do backend)
        socket.on('placar_atualizado', function(luta) {
            // Backend envia estado completo calculado - frontend apenas renderiza
            if (luta && typeof luta === 'object') {
                const lid = luta.id || luta.luta_id;
                if (LUTA_ID && lid && parseInt(lid, 10) !== parseInt(LUTA_ID, 10)) {
                    return;
                }
                console.log('📥 Recebido estado completo:', {
                    tempo: luta.tempo_restante_segundos,
                    status: luta.status,
                    id: lid
                });
                atualizarPlacar(luta);
                atualizarStatusConexao(true);
            } else {
                console.warn('⚠️ Dados inválidos recebidos:', luta);
            }
        });
        
        // Confirmação de entrada
        socket.on('joined', function(data) {
            console.log('Confirmado: entrou na sala', data);
        });
        
        // Eventos de conexão
        socket.on('connect', function() {
            console.log('✅ WebSocket conectado');
            atualizarStatusConexao(true);
            if (porArea) {
                socket.emit('join_placar_area', { evento_id: EVENTO_MONITOR_ID, area_num: AREA_MONITOR_NUM });
            } else if (EVENTO_MONITOR_ID != null) {
                socket.emit('join_evento_placar', { evento_id: EVENTO_MONITOR_ID });
            }
            if (LUTA_ID) {
                socket.emit('join_luta', { luta_id: LUTA_ID });
            }
        });
        
        socket.on('disconnect', function() {
            console.warn('⚠️ WebSocket desconectado');
            atualizarStatusConexao(false);
        });
        
        socket.on('connect_error', function(error) {
            console.error('❌ Erro de conexão WebSocket:', error);
            atualizarStatusConexao(false);
            // Tentar reconectar após 1 segundo
            setTimeout(() => {
                if (!socket.connected) {
                    console.log('Tentando reconectar...');
                    socket.connect();
                }
            }, 1000);
        });
        
        socket.on('error', function(error) {
            console.error('Erro Socket.IO:', error);
        });
        
        socket.on('reconnect', function(attemptNumber) {
            console.log('🔄 Reconectado após', attemptNumber, 'tentativas');
            atualizarStatusConexao(true);
            if (porArea) {
                socket.emit('join_placar_area', { evento_id: EVENTO_MONITOR_ID, area_num: AREA_MONITOR_NUM });
            } else if (EVENTO_MONITOR_ID != null) {
                socket.emit('join_evento_placar', { evento_id: EVENTO_MONITOR_ID });
            }
            if (LUTA_ID) {
                socket.emit('join_luta', { luta_id: LUTA_ID });
            }
        });
        
        function atualizarStatusConexao(conectado) {
            const statusEl = document.getElementById('connection-status');
            if (statusEl) {
                if (conectado) {
                    statusEl.className = 'connection-status connected';
                    statusEl.innerHTML = '<span class="live-dot"></span>';
                    statusEl.title = 'Ao vivo';
                } else {
                    statusEl.className = 'connection-status disconnected';
                    statusEl.innerHTML = '<span class="live-dot"></span>';
                    statusEl.title = 'Reconectando...';
                }
            }
        }
        
        // Inicializar status como desconectado (será atualizado quando conectar)
        atualizarStatusConexao(false);
        
        // REMOVIDO: Não iniciar contador local - tempo vem do backend via WebSocket/polling
        
        // Função para buscar estado atual (polling HTTP como fallback)
        // Backend retorna ESTADO COMPLETO calculado - frontend apenas renderiza
        function buscarEstadoAtual() {
            if (!LUTA_ID) {
                return;
            }
            
            fetch(`/eventos-competicoes/placar-judo/${LUTA_ID}/api/estado`, {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' },
                cache: 'no-cache'
            })
            .then(r => {
                if (!r.ok) {
                    throw new Error('Erro HTTP: ' + r.status);
                }
                return r.json();
            })
            .then(data => {
                if (data && data.sucesso && data.luta) {
                    // Backend calculou tempo - apenas renderizar
                    atualizarPlacar(data.luta);
                }
            })
            .catch(err => {
                // Erro silencioso - WebSocket deve estar funcionando
            });
        }
        
        // Buscar estado inicial imediatamente
        buscarEstadoAtual();
        
        // Polling de fallback a cada 1 segundo (se WebSocket falhar)
        setInterval(function() {
            // Só fazer polling se WebSocket não estiver conectado
            if (!socket || !socket.connected) {
                buscarEstadoAtual();
            }
        }, 1000);
        
    } catch (error) {
        console.error('Erro ao inicializar monitor:', error);
    }
});

// REMOVIDO: Contador de tempo local - backend é a única fonte de verdade
// O tempo agora é calculado e enviado pelo backend via WebSocket/polling
function iniciarContador() {
    // Não fazer nada - tempo vem do backend
    if (intervalo_tempo) {
        clearInterval(intervalo_tempo);
        intervalo_tempo = null;
    }
}

function atualizarDisplayTempo() {
    const display = document.getElementById('tempo-display-monitor');
    if (!display) return;
    // Dois timers: normal (regressivo) e Golden Score (crescente em vermelho) - troca ao terminar tempo normal
    if (golden_score_ativo) {
        const minutosGS = Math.floor(tempo_golden_score / 60);
        const segundosGS = tempo_golden_score % 60;
        display.textContent = `${String(minutosGS).padStart(2, '0')}:${String(segundosGS).padStart(2, '0')}`;
        display.style.color = '#ff0000';
        display.style.textShadow = '0 0 24px rgba(255,0,0,0.8), 0 0 48px rgba(255,0,0,0.4)';
        display.style.animation = 'pulse-glow 1s ease-in-out infinite';
        return;
    }
    const minutos = Math.floor(tempo_atual / 60);
    const segundos = tempo_atual % 60;
    display.textContent = `${String(minutos).padStart(2, '0')}:${String(segundos).padStart(2, '0')}`;
    if (tempo_atual <= 30 && tempo_atual > 0) {
        display.style.color = '#ff4444';
        display.style.textShadow = '0 0 24px rgba(255,68,68,0.8), 0 0 48px rgba(255,68,68,0.4)';
        display.style.animation = 'pulse-glow 1s ease-in-out infinite';
    } else if (tempo_atual === 0) {
        display.style.color = '#ff0000';
        display.style.textShadow = '0 0 24px rgba(255,0,0,0.8)';
        display.style.animation = 'none';
    } else {
        display.style.color = '#ffd700';
        display.style.textShadow = '0 0 24px rgba(255, 215, 0, 0.8), 0 0 48px rgba(255, 215, 0, 0.4)';
        display.style.animation = 'pulse-glow 2s ease-in-out infinite';
    }
}

function atualizarDisplayGoldenScore() {
    // O timer principal (tempo-display-monitor) já exibe o tempo do Golden Score via atualizarDisplayTempo
    // Nenhuma ação adicional necessária
}

function atualizarPlacar(luta) {
    if (!luta) {
        console.warn('Dados de luta inválidos');
        return;
    }

    const nb = document.getElementById('atleta-branco-nome-monitor');
    const na = document.getElementById('atleta-azul-nome-monitor');
    const ab = document.getElementById('atleta-branco-academia-monitor');
    const aa = document.getElementById('atleta-azul-academia-monitor');
    const catEl = document.getElementById('monitor-categoria-titulo');
    const titEv = document.getElementById('monitor-evento-titulo');
    if (titEv && luta.evento_nome) titEv.textContent = '🥋 ' + luta.evento_nome;
    if (nb && luta.atleta_branco_nome != null) nb.textContent = luta.atleta_branco_nome;
    if (na && luta.atleta_azul_nome != null) na.textContent = luta.atleta_azul_nome;
    if (ab) {
        const t = (luta.atleta_branco_academia || '').trim();
        ab.textContent = t;
        ab.style.display = t ? '' : 'none';
    }
    if (aa) {
        const t = (luta.atleta_azul_academia || '').trim();
        aa.textContent = t;
        aa.style.display = t ? '' : 'none';
    }
    if (catEl && Object.prototype.hasOwnProperty.call(luta, 'categoria_nome')) {
        const t = (luta.categoria_nome || '').trim();
        catEl.textContent = t;
        catEl.style.display = t ? '' : 'none';
    }
    
    console.log('🔄 Monitor - Atualizando placar:', {
        status: luta.status,
        tempo: luta.tempo_restante_segundos,
        pontos_branco: { ippon: luta.pontos_branco_ippon, wazaari: luta.pontos_branco_wazaari, shido: luta.pontos_branco_shido },
        pontos_azul: { ippon: luta.pontos_azul_ippon, wazaari: luta.pontos_azul_wazaari, shido: luta.pontos_azul_shido }
    });
    
    // Função auxiliar para atualizar com animação
    const atualizarPonto = (elementId, valor) => {
        const el = document.getElementById(elementId);
        if (el) {
            const valorAnterior = parseInt(el.textContent) || 0;
            const novoValor = parseInt(valor) || 0;
            
            if (novoValor !== valorAnterior) {
                el.textContent = novoValor;
                
                // Animação se valor aumentou
                if (novoValor > valorAnterior) {
                    el.classList.add('ponto-animado');
                    
                    // Destacar o item pai também
                    const item = el.closest('.ponto-monitor-item');
                    if (item) {
                        item.classList.add('highlight');
                        setTimeout(() => {
                            item.classList.remove('highlight');
                        }, 600);
                    }
                    
                    setTimeout(() => {
                        el.classList.remove('ponto-animado');
                    }, 500);
                }
            }
        }
    };
    
    // Atualizar pontuação Branco
    atualizarPonto('ippon-branco-monitor', luta.pontos_branco_ippon);
    atualizarPonto('wazaari-branco-monitor', luta.pontos_branco_wazaari);
    atualizarPonto('shido-branco-monitor', luta.pontos_branco_shido);
    atualizarPonto('yoko-branco-monitor', luta.pontos_branco_yoko);
    
    // Atualizar pontuação Azul
    atualizarPonto('ippon-azul-monitor', luta.pontos_azul_ippon);
    atualizarPonto('wazaari-azul-monitor', luta.pontos_azul_wazaari);
    atualizarPonto('shido-azul-monitor', luta.pontos_azul_shido);
    atualizarPonto('yoko-azul-monitor', luta.pontos_azul_yoko);
    
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
    
    // Osaekomi: mostrar cronômetro no lado que aplica
    const osaekomiAtivo = !!luta.osaekomi_ativo;
    const osaekomiLado = (luta.osaekomi_lado || '').toLowerCase();
    const osaekomiElapsed = parseInt(luta.osaekomi_elapsed_seconds) || 0;
    const osaekomiFmt = (osaekomiElapsed >= 60 ? Math.floor(osaekomiElapsed / 60) + ':' : '0:') + (osaekomiElapsed % 60 < 10 ? '0' : '') + (osaekomiElapsed % 60);
    const brancoContainer = document.getElementById('osaekomi-branco-container-monitor');
    const brancoValor = document.getElementById('osaekomi-branco-valor-monitor');
    const azulContainer = document.getElementById('osaekomi-azul-container-monitor');
    const azulValor = document.getElementById('osaekomi-azul-valor-monitor');
    if (brancoContainer) brancoContainer.style.display = (osaekomiAtivo && osaekomiLado === 'branco') ? '' : 'none';
    if (brancoValor) brancoValor.textContent = (osaekomiAtivo && osaekomiLado === 'branco') ? osaekomiFmt : '00:00';
    if (azulContainer) azulContainer.style.display = (osaekomiAtivo && osaekomiLado === 'azul') ? '' : 'none';
    if (azulValor) azulValor.textContent = (osaekomiAtivo && osaekomiLado === 'azul') ? osaekomiFmt : '00:00';
    const osaekomiBanner = document.getElementById('osaekomi-banner-monitor');
    const osaekomiBannerTempo = document.getElementById('osaekomi-banner-tempo-monitor');
    if (osaekomiBanner) osaekomiBanner.style.display = osaekomiAtivo ? 'flex' : 'none';
    if (osaekomiBannerTempo) osaekomiBannerTempo.textContent = osaekomiFmt;
    
    // Atualizar status
    atualizarStatus(luta.status);
    
    const acoesPos = document.getElementById('monitor-pos-vitoria-acoes');
    if (acoesPos) {
        acoesPos.style.display = luta.status === 'finalizada' ? 'flex' : 'none';
    }

    // Atualizar banner de vencedor
    if (luta.status === 'finalizada' && luta.vencedor) {
        mostrarVencedor(luta.vencedor, luta.tipo_vitoria, luta.atleta_branco_nome, luta.atleta_azul_nome);
    } else {
        esconderVencedor();
    }
    
    // Atualizar indicador de hansoku-make se necessário
    atualizarHansokumake(luta);

    _monitorUltimoStatus = luta.status || null;
}

function atualizarHansokumake(luta) {
    // Atualizar indicadores de hansoku-make dinamicamente
    const brancoHansoku = document.querySelector('.atleta-branco .hansoku-indicator');
    const azulHansoku = document.querySelector('.atleta-azul .hansoku-indicator');
    
    if (luta.pontos_branco_hansokumake) {
        if (!brancoHansoku) {
            const box = document.querySelector('.atleta-branco');
            if (box) {
                const indicator = document.createElement('div');
                indicator.className = 'hansoku-indicator';
                indicator.innerHTML = '<div class="alert alert-danger mb-0"><strong>Hansoku-make</strong></div>';
                box.querySelector('.pontos-monitor').after(indicator);
            }
        }
    } else if (brancoHansoku) {
        brancoHansoku.remove();
    }
    
    if (luta.pontos_azul_hansokumake) {
        if (!azulHansoku) {
            const box = document.querySelector('.atleta-azul');
            if (box) {
                const indicator = document.createElement('div');
                indicator.className = 'hansoku-indicator';
                indicator.innerHTML = '<div class="alert alert-danger mb-0"><strong>Hansoku-make</strong></div>';
                box.querySelector('.pontos-monitor').after(indicator);
            }
        }
    } else if (azulHansoku) {
        azulHansoku.remove();
    }
}

function atualizarStatus(status) {
    const statusEl = document.getElementById('status-luta-monitor');
    if (!statusEl) return;
    
    let badgeClass = 'bg-secondary';
    let texto = 'AGUARDANDO';
    
    if (golden_score_ativo) {
        badgeClass = 'bg-danger';
        texto = 'GOLDEN SCORE';
    } else if (status === 'em_andamento') {
        badgeClass = 'bg-success';
        texto = 'EM ANDAMENTO';
    } else if (status === 'pausada') {
        badgeClass = 'bg-warning';
        texto = 'PAUSADA';
    } else if (status === 'finalizada') {
        badgeClass = 'bg-danger';
        texto = 'FINALIZADA';
    }
    
    statusEl.innerHTML = `<span class="badge ${badgeClass}" style="font-size: 1.2rem; padding: 8px 16px;">${texto}</span>`;
}

function _monitorLabelTipoVitoria(tipo) {
    if (!tipo) return '';
    const k = String(tipo).toLowerCase();
    const map = {
        ippon: 'IPPON',
        golden_score: 'GOLDEN SCORE',
        hansoku_make: 'HANSOKU-MAKE',
        wazaari: 'WAZA-ARI',
    };
    return map[k] || String(tipo).replace(/_/g, ' ').toUpperCase();
}

function mostrarVencedor(vencedor, tipo_vitoria, atletaBrancoNome, atletaAzulNome) {
    let banner = document.querySelector('.vencedor-banner');
    if (!banner) {
        banner = document.createElement('div');
        banner.className = 'vencedor-banner';
        document.querySelector('.placar-content').appendChild(banner);
    }

    let vencedorTexto;
    if (vencedor === 'empate') {
        vencedorTexto = 'EMPATE';
    } else {
        vencedorTexto =
            vencedor === 'branco' ? atletaBrancoNome || 'BRANCO' : atletaAzulNome || 'AZUL';
    }
    const tipoTexto = _monitorLabelTipoVitoria(tipo_vitoria);

    banner.innerHTML = `
        <div>🏆 VENCEDOR: ${vencedorTexto}</div>
        <div style="font-size: 1.5rem; margin-top: 10px;">${tipoTexto}</div>
    `;
    banner.style.display = 'block';
}

function esconderVencedor() {
    const banner = document.querySelector('.vencedor-banner');
    if (banner) {
        banner.style.display = 'none';
    }
}

// Tela cheia do placar (monitor)
function toggleFullscreenPlacarMonitor() {
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
        console.error('Erro ao alternar tela cheia do placar (monitor):', e);
    }
}

window.toggleFullscreenPlacarMonitor = toggleFullscreenPlacarMonitor;
