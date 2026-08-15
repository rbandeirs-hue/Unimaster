import { useState } from 'react'
import { alunos, descontos, cobrancas as initialCobrancas, type Cobranca, type StatusCobranca, COBRANCA_COLOR, FAIXA_COLOR, fmtMoeda, fmtMes } from '../data'
import { useTheme, tok } from '../theme'

const MESES_DISPONIVEIS = ['2026-09', '2026-08', '2026-07']

export default function GerarCobranca() {
  const { theme } = useTheme()
  const t = tok(theme)
  const [cobrancas, setCobrancas] = useState<Cobranca[]>(initialCobrancas)
  const [mesSelecionado, setMesSelecionado] = useState('2026-09')
  const [filtroStatus, setFiltroStatus] = useState<StatusCobranca | 'Todos'>('Todos')
  const [nextId, setNextId] = useState(initialCobrancas.length + 1)

  // Seleção de alunos para gerar cobranças
  const [alunosSel, setAlunosSel] = useState<number[]>([])
  const [descontoSel, setDescontoSel] = useState<number | ''>('')
  const [observacao, setObservacao] = useState('')
  const [etapa, setEtapa] = useState<'config' | 'preview' | 'done'>('config')

  const alunosAtivos = alunos.filter(a => a.ativo)
  const descontoAtivo = descontos.filter(d => d.ativo)

  // Alunos que já têm cobrança no mês selecionado
  const jaGerados = new Set(cobrancas.filter(c => c.mes === mesSelecionado).map(c => c.alunoId))

  const alunosSemCobranca = alunosAtivos.filter(a => !jaGerados.has(a.id))

  function toggleAluno(id: number) {
    setAlunosSel(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  function selecionarTodos() {
    setAlunosSel(alunosSemCobranca.map(a => a.id))
  }

  const desconto = descontoSel ? descontos.find(d => d.id === descontoSel) : null

  function calcValorFinal(mensalidade: number) {
    if (!desconto) return mensalidade
    if (desconto.tipo === 'Percentual') return Math.max(0, mensalidade - mensalidade * desconto.valor / 100)
    return Math.max(0, mensalidade - desconto.valor)
  }

  function gerarCobrancas() {
    const novas: Cobranca[] = alunosSel.map((aId, idx) => {
      const aluno = alunos.find(a => a.id === aId)!
      const valFinal = calcValorFinal(aluno.mensalidade)
      return {
        id: nextId + idx,
        alunoId: aId,
        mes: mesSelecionado,
        valorOriginal: aluno.mensalidade,
        descontoId: desconto?.id,
        valorFinal: valFinal,
        status: 'Gerada',
        geradaEm: new Date().toISOString().slice(0, 10),
        observacao: observacao || undefined,
      }
    })
    setCobrancas(prev => [...prev, ...novas])
    setNextId(n => n + novas.length)
    setAlunosSel([])
    setDescontoSel('')
    setObservacao('')
    setEtapa('done')
    setTimeout(() => setEtapa('config'), 3000)
  }

  function atualizarStatus(id: number, status: StatusCobranca) {
    setCobrancas(prev => prev.map(c => c.id === id
      ? { ...c, status, enviadaEm: status === 'Enviada' ? new Date().toISOString().slice(0, 10) : c.enviadaEm }
      : c
    ))
  }

  const cobrancasFiltradas = cobrancas
    .filter(c => c.mes === mesSelecionado)
    .filter(c => filtroStatus === 'Todos' || c.status === filtroStatus)
    .sort((a, b) => a.alunoId - b.alunoId)

  const totalGerado = cobrancasFiltradas.reduce((s, c) => s + c.valorFinal, 0)
  const totalEnviado = cobrancas.filter(c => c.mes === mesSelecionado && c.status === 'Enviada').length
  const totalPago = cobrancas.filter(c => c.mes === mesSelecionado && c.status === 'Paga').length

  const input = (extra?: object) => ({
    padding: '8px 12px', background: t.inputBg, border: `1px solid ${t.inputBorder}`,
    color: t.text, fontSize: 13, fontFamily: "'Inter', sans-serif", borderRadius: 3, width: '100%',
    ...extra,
  } as React.CSSProperties)

  return (
    <div style={{ padding: '32px 36px', maxWidth: 1050, color: t.text }}>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontFamily: "'Roboto Slab', serif", fontSize: 26, fontWeight: 700, color: t.text, margin: '0 0 4px' }}>Gerar Cobranças</h1>
        <p style={{ margin: 0, fontSize: 13, color: t.textMuted }}>Gere e gerencie cobranças mensais dos alunos</p>
      </div>

      {/* Seletor de mês */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 24, alignItems: 'center' }}>
        <span style={{ fontSize: 12, color: t.textMuted, marginRight: 4 }}>Mês:</span>
        {MESES_DISPONIVEIS.map(m => (
          <button key={m} onClick={() => { setMesSelecionado(m); setEtapa('config'); setAlunosSel([]) }} style={{
            padding: '6px 16px', fontSize: 12, cursor: 'pointer', borderRadius: 3,
            background: mesSelecionado === m ? '#c41e3a' : t.card,
            border: `1px solid ${mesSelecionado === m ? '#c41e3a' : t.border}`,
            color: mesSelecionado === m ? '#fff' : t.textSub,
            fontFamily: "'Inter', sans-serif", fontWeight: mesSelecionado === m ? 600 : 400,
            transition: 'all 0.15s',
          }}>{fmtMes(m)}</button>
        ))}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 16 }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 10, color: t.textFaint, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Cobranças</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 16, fontWeight: 600, color: t.text }}>{cobrancas.filter(c => c.mes === mesSelecionado).length}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 10, color: t.textFaint, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Enviadas</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 16, fontWeight: 600, color: '#d4a800' }}>{totalEnviado}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 10, color: t.textFaint, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Pagas</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 16, fontWeight: 600, color: '#22c55e' }}>{totalPago}</div>
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr', gap: 20 }}>
        {/* Painel de geração */}
        <div style={{ background: t.card, border: `1px solid ${t.border}`, padding: '20px 22px', borderRadius: 4, alignSelf: 'start', boxShadow: t.shadow }}>
          <h2 style={{ fontFamily: "'Roboto Slab', serif", fontSize: 14, fontWeight: 600, color: t.text, margin: '0 0 16px' }}>
            Nova Cobrança — {fmtMes(mesSelecionado)}
          </h2>

          {etapa === 'done' && (
            <div style={{ padding: '16px', background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.2)', borderRadius: 3, textAlign: 'center', marginBottom: 12 }}>
              <div style={{ fontSize: 18 }}>✓</div>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#22c55e' }}>Cobranças geradas!</div>
              <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>Aparecendo na lista ao lado.</div>
            </div>
          )}

          {alunosSemCobranca.length === 0 && etapa !== 'done' && (
            <div style={{ padding: '14px', background: 'rgba(34,197,94,0.07)', border: '1px solid rgba(34,197,94,0.15)', borderRadius: 3, fontSize: 12, color: '#22c55e', marginBottom: 12 }}>
              Todos os alunos já têm cobrança em {fmtMes(mesSelecionado)}.
            </div>
          )}

          {alunosSemCobranca.length > 0 && etapa !== 'done' && (
            <>
              {/* Lista de alunos */}
              <div style={{ marginBottom: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 7 }}>
                  <label style={{ fontSize: 11, fontWeight: 500, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Alunos ({alunosSemCobranca.length} sem cobrança)</label>
                  <button onClick={selecionarTodos} style={{ fontSize: 11, color: '#c41e3a', background: 'none', border: 'none', cursor: 'pointer', fontFamily: "'Inter', sans-serif" }}>Selecionar todos</button>
                </div>
                <div style={{ maxHeight: 220, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {alunosSemCobranca.map(a => {
                    const sel = alunosSel.includes(a.id)
                    return (
                      <label key={a.id} style={{
                        display: 'flex', alignItems: 'center', gap: 8,
                        padding: '7px 9px', cursor: 'pointer', borderRadius: 3,
                        background: sel ? 'rgba(196,30,58,0.07)' : 'transparent',
                        border: `1px solid ${sel ? 'rgba(196,30,58,0.2)' : 'transparent'}`,
                        transition: 'all 0.1s',
                      }}>
                        <input type="checkbox" checked={sel} onChange={() => toggleAluno(a.id)} style={{ accentColor: '#c41e3a' }} />
                        <span style={{ width: 7, height: 7, borderRadius: '50%', background: FAIXA_COLOR[a.faixa], flexShrink: 0, display: 'inline-block' }} />
                        <span style={{ flex: 1, fontSize: 12, color: t.text }}>{a.nome}</span>
                        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: t.textMuted }}>{fmtMoeda(calcValorFinal(a.mensalidade))}</span>
                      </label>
                    )
                  })}
                </div>
              </div>

              {/* Desconto */}
              <div style={{ marginBottom: 12 }}>
                <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>Desconto (opcional)</label>
                <select style={input()} value={descontoSel} onChange={e => setDescontoSel(e.target.value ? parseInt(e.target.value) : '')}>
                  <option value="">Sem desconto</option>
                  {descontoAtivo.map(d => (
                    <option key={d.id} value={d.id}>{d.nome} ({d.tipo === 'Percentual' ? `${d.valor}%` : fmtMoeda(d.valor)})</option>
                  ))}
                </select>
              </div>

              {/* Observação */}
              <div style={{ marginBottom: 16 }}>
                <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>Observação</label>
                <input style={input()} value={observacao} onChange={e => setObservacao(e.target.value)} placeholder="Opcional..." />
              </div>

              {/* Resumo */}
              {alunosSel.length > 0 && (
                <div style={{ padding: '10px 14px', background: 'rgba(196,30,58,0.07)', border: '1px solid rgba(196,30,58,0.15)', borderRadius: 3, marginBottom: 14 }}>
                  <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 3 }}>{alunosSel.length} aluno(s) selecionado(s)</div>
                  <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 18, fontWeight: 700, color: '#c41e3a' }}>
                    {fmtMoeda(alunosSel.reduce((s, id) => s + calcValorFinal(alunos.find(a => a.id === id)!.mensalidade), 0))}
                  </div>
                  <div style={{ fontSize: 11, color: t.textMuted }}>total a cobrar</div>
                </div>
              )}

              <button
                onClick={gerarCobrancas}
                disabled={alunosSel.length === 0}
                style={{
                  width: '100%', padding: '10px', background: alunosSel.length > 0 ? '#c41e3a' : t.inputBg,
                  border: 'none', color: alunosSel.length > 0 ? '#fff' : t.textMuted,
                  fontSize: 13, fontWeight: 600, cursor: alunosSel.length > 0 ? 'pointer' : 'not-allowed',
                  borderRadius: 3, fontFamily: "'Inter', sans-serif", transition: 'all 0.15s',
                }}
              >
                Gerar {alunosSel.length > 0 ? `${alunosSel.length} Cobrança(s)` : 'Cobranças'}
              </button>
            </>
          )}
        </div>

        {/* Lista de cobranças do mês */}
        <div>
          <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: t.textMuted }}>Filtro:</span>
            {(['Todos', 'Gerada', 'Enviada', 'Paga', 'Cancelada'] as const).map(s => {
              const sc = s !== 'Todos' ? COBRANCA_COLOR[s] : null
              return (
                <button key={s} onClick={() => setFiltroStatus(s)} style={{
                  padding: '4px 10px', fontSize: 11, cursor: 'pointer', borderRadius: 2,
                  background: filtroStatus === s ? (sc?.bg ?? 'rgba(255,255,255,0.1)') : t.card,
                  border: `1px solid ${filtroStatus === s ? (sc?.text ?? t.border) : t.border}`,
                  color: filtroStatus === s ? (sc?.text ?? t.text) : t.textMuted,
                  fontFamily: "'Inter', sans-serif",
                }}>{s}</button>
              )
            })}
            {cobrancasFiltradas.length > 0 && (
              <span style={{ marginLeft: 'auto', fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: '#c41e3a', fontWeight: 600 }}>{fmtMoeda(totalGerado)}</span>
            )}
          </div>

          <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 4, overflow: 'hidden', boxShadow: t.shadow }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${t.theadBorder}` }}>
                  {['Aluno', 'Original', 'Desconto', 'Final', 'Status', 'Gerada', 'Ação'].map(h => (
                    <th key={h} style={{ padding: '10px 13px', textAlign: 'left', fontSize: 10, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: t.textFaint }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {cobrancasFiltradas.map(c => {
                  const aluno = alunos.find(a => a.id === c.alunoId)
                  const desc = c.descontoId ? descontos.find(d => d.id === c.descontoId) : null
                  const sc = COBRANCA_COLOR[c.status]
                  return (
                    <tr key={c.id} style={{ borderBottom: `1px solid ${t.rowBorder}` }}
                      onMouseEnter={e => (e.currentTarget as HTMLTableRowElement).style.background = t.cardHover}
                      onMouseLeave={e => (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'}
                    >
                      <td style={{ padding: '10px 13px' }}>
                        <div style={{ fontSize: 13, fontWeight: 500, color: t.text }}>{aluno?.nome}</div>
                        <div style={{ fontSize: 10, color: t.textMuted, display: 'flex', alignItems: 'center', gap: 4, marginTop: 2 }}>
                          <span style={{ width: 6, height: 6, borderRadius: '50%', background: aluno ? FAIXA_COLOR[aluno.faixa] : '#999', display: 'inline-block' }} />
                          {aluno?.faixa}
                        </div>
                      </td>
                      <td style={{ padding: '10px 13px', fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: t.textSub }}>{fmtMoeda(c.valorOriginal)}</td>
                      <td style={{ padding: '10px 13px', fontSize: 11, color: desc ? '#c41e3a' : t.textFaint }}>
                        {desc ? (desc.tipo === 'Percentual' ? `−${desc.valor}%` : `−${fmtMoeda(desc.valor)}`) : '—'}
                      </td>
                      <td style={{ padding: '10px 13px', fontFamily: "'JetBrains Mono', monospace", fontSize: 14, fontWeight: 700, color: t.text }}>{fmtMoeda(c.valorFinal)}</td>
                      <td style={{ padding: '10px 13px' }}>
                        <span style={{ fontSize: 11, padding: '2px 7px', borderRadius: 2, background: sc.bg, color: sc.text }}>{c.status}</span>
                      </td>
                      <td style={{ padding: '10px 13px', fontSize: 11, color: t.textMuted }}>{c.geradaEm}</td>
                      <td style={{ padding: '10px 13px' }}>
                        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                          {c.status === 'Gerada' && (
                            <button onClick={() => atualizarStatus(c.id, 'Enviada')} style={{ padding: '3px 8px', background: 'rgba(245,197,24,0.1)', border: '1px solid rgba(245,197,24,0.25)', color: '#d4a800', fontSize: 10, cursor: 'pointer', borderRadius: 2, fontFamily: "'Inter', sans-serif" }}>Enviar</button>
                          )}
                          {(c.status === 'Gerada' || c.status === 'Enviada') && (
                            <button onClick={() => atualizarStatus(c.id, 'Paga')} style={{ padding: '3px 8px', background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.25)', color: '#22c55e', fontSize: 10, cursor: 'pointer', borderRadius: 2, fontFamily: "'Inter', sans-serif" }}>Paga</button>
                          )}
                          {c.status !== 'Cancelada' && c.status !== 'Paga' && (
                            <button onClick={() => atualizarStatus(c.id, 'Cancelada')} style={{ padding: '3px 8px', background: 'none', border: `1px solid ${t.border}`, color: t.textMuted, fontSize: 10, cursor: 'pointer', borderRadius: 2, fontFamily: "'Inter', sans-serif" }}>Cancelar</button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {cobrancasFiltradas.length === 0 && (
              <div style={{ padding: '40px', textAlign: 'center', fontSize: 13, color: t.textFaint }}>
                Nenhuma cobrança em {fmtMes(mesSelecionado)}.
                <br /><span style={{ fontSize: 12 }}>Use o painel ao lado para gerar.</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
