import { useState } from 'react'
import { descontos as initialDescontos, type Desconto, type TipoDesconto, alunos, fmtMoeda } from '../data'
import { useTheme, tok } from '../theme'

const EMPTY: Omit<Desconto, 'id' | 'criadoEm'> = {
  nome: '',
  tipo: 'Percentual',
  valor: 0,
  motivo: '',
  alunoId: undefined,
  validade: undefined,
  ativo: true,
}

export default function Descontos() {
  const { theme } = useTheme()
  const t = tok(theme)
  const [lista, setLista] = useState(initialDescontos)
  const [form, setForm] = useState<Omit<Desconto, 'id' | 'criadoEm'>>({ ...EMPTY })
  const [editId, setEditId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [nextId, setNextId] = useState(initialDescontos.length + 1)
  const [filtro, setFiltro] = useState<'todos' | 'ativo' | 'inativo'>('todos')

  function openNew() { setForm({ ...EMPTY }); setEditId(null); setShowForm(true) }
  function openEdit(d: Desconto) {
    setForm({ nome: d.nome, tipo: d.tipo, valor: d.valor, motivo: d.motivo, alunoId: d.alunoId, validade: d.validade, ativo: d.ativo })
    setEditId(d.id); setShowForm(true)
  }
  function salvar() {
    if (!form.nome || form.valor <= 0) return
    if (editId !== null) {
      setLista(prev => prev.map(d => d.id === editId ? { ...d, ...form } : d))
    } else {
      setLista(prev => [...prev, { ...form, id: nextId, criadoEm: new Date().toISOString().slice(0, 10) }])
      setNextId(n => n + 1)
    }
    setShowForm(false)
  }
  function toggleAtivo(id: number) {
    setLista(prev => prev.map(d => d.id === id ? { ...d, ativo: !d.ativo } : d))
  }
  function excluir(id: number) { setLista(prev => prev.filter(d => d.id !== id)) }

  const visiveis = lista.filter(d =>
    filtro === 'todos' ? true : filtro === 'ativo' ? d.ativo : !d.ativo
  )

  const input = (extra?: object) => ({
    padding: '9px 12px', background: t.inputBg, border: `1px solid ${t.inputBorder}`,
    color: t.text, fontSize: 13, fontFamily: "'Inter', sans-serif", borderRadius: 3, width: '100%',
    ...extra,
  } as React.CSSProperties)

  function previewDesconto(d: typeof form) {
    const base = 150
    if (d.tipo === 'Percentual') return base - (base * d.valor / 100)
    return base - d.valor
  }

  return (
    <div style={{ padding: '32px 36px', maxWidth: 960, color: t.text }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28 }}>
        <div>
          <h1 style={{ fontFamily: "'Roboto Slab', serif", fontSize: 26, fontWeight: 700, color: t.text, margin: '0 0 4px' }}>Descontos</h1>
          <p style={{ margin: 0, fontSize: 13, color: t.textMuted }}>{lista.filter(d => d.ativo).length} ativos · {lista.filter(d => !d.ativo).length} inativos</p>
        </div>
        <button
          onClick={openNew}
          style={{ padding: '9px 20px', background: '#c41e3a', border: 'none', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', borderRadius: 3, fontFamily: "'Inter', sans-serif" }}
        >+ Novo Desconto</button>
      </div>

      {/* Formulário */}
      {showForm && (
        <div style={{ background: t.card, border: `1px solid ${t.border}`, padding: '24px 28px', marginBottom: 24, borderRadius: 4, boxShadow: t.shadow }}>
          <h2 style={{ fontFamily: "'Roboto Slab', serif", fontSize: 16, fontWeight: 600, color: t.text, margin: '0 0 20px' }}>
            {editId ? 'Editar Desconto' : 'Novo Desconto'}
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
            <div>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>Nome *</label>
              <input style={input()} value={form.nome} onChange={e => setForm(p => ({ ...p, nome: e.target.value }))} placeholder="Ex: Desconto Irmão" />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>Tipo *</label>
              <select style={input()} value={form.tipo} onChange={e => setForm(p => ({ ...p, tipo: e.target.value as TipoDesconto }))}>
                <option value="Percentual">Percentual (%)</option>
                <option value="Fixo">Valor Fixo (R$)</option>
              </select>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>
                {form.tipo === 'Percentual' ? 'Percentual (%)' : 'Valor (R$)'} *
              </label>
              <input type="number" min={0} max={form.tipo === 'Percentual' ? 100 : undefined} step={form.tipo === 'Percentual' ? 5 : 1} style={input()} value={form.valor || ''} onChange={e => setForm(p => ({ ...p, valor: parseFloat(e.target.value) || 0 }))} placeholder={form.tipo === 'Percentual' ? 'Ex: 15' : 'Ex: 20,00'} />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>Aluno específico (opcional)</label>
              <select style={input()} value={form.alunoId ?? ''} onChange={e => setForm(p => ({ ...p, alunoId: e.target.value ? parseInt(e.target.value) : undefined }))}>
                <option value="">Todos os alunos</option>
                {alunos.filter(a => a.ativo).map(a => <option key={a.id} value={a.id}>{a.nome}</option>)}
              </select>
            </div>
            <div style={{ gridColumn: '1/-1' }}>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>Motivo / Observação</label>
              <input style={input()} value={form.motivo} onChange={e => setForm(p => ({ ...p, motivo: e.target.value }))} placeholder="Descreva o motivo do desconto" />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>Validade (opcional)</label>
              <input type="date" style={input()} value={form.validade ?? ''} onChange={e => setForm(p => ({ ...p, validade: e.target.value || undefined }))} />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>Status</label>
              <select style={input()} value={form.ativo ? 'ativo' : 'inativo'} onChange={e => setForm(p => ({ ...p, ativo: e.target.value === 'ativo' }))}>
                <option value="ativo">Ativo</option>
                <option value="inativo">Inativo</option>
              </select>
            </div>
          </div>

          {/* Preview */}
          {form.valor > 0 && (
            <div style={{ padding: '12px 16px', background: 'rgba(196,30,58,0.07)', border: '1px solid rgba(196,30,58,0.15)', borderRadius: 3, marginBottom: 16 }}>
              <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>Simulação sobre mensalidade de {fmtMoeda(150)}:</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: t.textSub, textDecoration: 'line-through' }}>{fmtMoeda(150)}</span>
                <span style={{ fontSize: 12, color: '#c41e3a' }}>
                  {form.tipo === 'Percentual' ? `−${form.valor}%` : `−${fmtMoeda(form.valor)}`}
                </span>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 18, fontWeight: 700, color: '#22c55e' }}>{fmtMoeda(Math.max(0, previewDesconto(form)))}</span>
              </div>
            </div>
          )}

          <div style={{ display: 'flex', gap: 10 }}>
            <button onClick={salvar} style={{ padding: '9px 22px', background: '#c41e3a', border: 'none', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', borderRadius: 3, fontFamily: "'Inter', sans-serif" }}>
              {editId ? 'Salvar' : 'Cadastrar'}
            </button>
            <button onClick={() => setShowForm(false)} style={{ padding: '9px 16px', background: 'none', border: `1px solid ${t.border}`, color: t.textMuted, fontSize: 13, cursor: 'pointer', borderRadius: 3, fontFamily: "'Inter', sans-serif" }}>Cancelar</button>
          </div>
        </div>
      )}

      {/* Filtro */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
        {(['todos', 'ativo', 'inativo'] as const).map(f => (
          <button key={f} onClick={() => setFiltro(f)} style={{
            padding: '5px 14px', fontSize: 11, cursor: 'pointer', borderRadius: 2,
            background: filtro === f ? 'rgba(255,255,255,0.1)' : t.card,
            border: `1px solid ${filtro === f ? 'rgba(255,255,255,0.25)' : t.border}`,
            color: filtro === f ? t.text : t.textMuted,
            fontFamily: "'Inter', sans-serif", textTransform: 'capitalize',
          }}>{f === 'todos' ? 'Todos' : f === 'ativo' ? 'Ativos' : 'Inativos'}</button>
        ))}
      </div>

      {/* Tabela */}
      <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 4, overflow: 'hidden', boxShadow: t.shadow }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${t.theadBorder}` }}>
              {['Nome', 'Tipo', 'Desconto', 'Motivo', 'Aluno', 'Validade', 'Status', ''].map(h => (
                <th key={h} style={{ padding: '11px 14px', textAlign: 'left', fontSize: 10, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: t.textFaint }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visiveis.map(d => {
              const aluno = d.alunoId ? alunos.find(a => a.id === d.alunoId) : null
              const vencido = d.validade && new Date(d.validade) < new Date()
              return (
                <tr key={d.id} style={{ borderBottom: `1px solid ${t.rowBorder}`, opacity: d.ativo ? 1 : 0.5 }}
                  onMouseEnter={e => (e.currentTarget as HTMLTableRowElement).style.background = t.cardHover}
                  onMouseLeave={e => (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'}
                >
                  <td style={{ padding: '11px 14px', fontSize: 13, fontWeight: 500, color: t.text }}>{d.nome}</td>
                  <td style={{ padding: '11px 14px' }}>
                    <span style={{ fontSize: 11, padding: '2px 7px', borderRadius: 2, background: d.tipo === 'Percentual' ? 'rgba(59,130,246,0.12)' : 'rgba(168,85,247,0.12)', color: d.tipo === 'Percentual' ? '#3b82f6' : '#a855f7' }}>{d.tipo}</span>
                  </td>
                  <td style={{ padding: '11px 14px', fontFamily: "'JetBrains Mono', monospace", fontSize: 14, fontWeight: 600, color: '#c41e3a' }}>
                    {d.tipo === 'Percentual' ? `${d.valor}%` : fmtMoeda(d.valor)}
                  </td>
                  <td style={{ padding: '11px 14px', fontSize: 12, color: t.textSub, maxWidth: 200 }}>{d.motivo || '—'}</td>
                  <td style={{ padding: '11px 14px', fontSize: 12, color: t.textMuted }}>{aluno ? aluno.nome.split(' ')[0] : 'Geral'}</td>
                  <td style={{ padding: '11px 14px', fontSize: 12, color: vencido ? '#c41e3a' : t.textMuted }}>
                    {d.validade ? new Date(d.validade + 'T00:00').toLocaleDateString('pt-BR') : '—'}
                    {vencido && <span style={{ marginLeft: 4, fontSize: 10, color: '#c41e3a' }}>vencido</span>}
                  </td>
                  <td style={{ padding: '11px 14px' }}>
                    <span style={{ fontSize: 11, padding: '2px 7px', borderRadius: 2, background: d.ativo ? 'rgba(34,197,94,0.1)' : 'rgba(107,122,153,0.1)', color: d.ativo ? '#22c55e' : '#6b7a99' }}>{d.ativo ? 'Ativo' : 'Inativo'}</span>
                  </td>
                  <td style={{ padding: '11px 14px' }}>
                    <div style={{ display: 'flex', gap: 5 }}>
                      <button onClick={() => openEdit(d)} style={{ padding: '3px 8px', background: 'none', border: `1px solid ${t.border}`, color: t.textMuted, fontSize: 10, cursor: 'pointer', borderRadius: 2, fontFamily: "'Inter', sans-serif" }}>Editar</button>
                      <button onClick={() => toggleAtivo(d.id)} style={{ padding: '3px 8px', background: 'none', border: `1px solid ${t.border}`, color: t.textMuted, fontSize: 10, cursor: 'pointer', borderRadius: 2, fontFamily: "'Inter', sans-serif" }}>{d.ativo ? 'Desativar' : 'Ativar'}</button>
                      <button onClick={() => excluir(d.id)} style={{ padding: '3px 8px', background: 'rgba(196,30,58,0.08)', border: '1px solid rgba(196,30,58,0.2)', color: '#c41e3a', fontSize: 10, cursor: 'pointer', borderRadius: 2, fontFamily: "'Inter', sans-serif" }}>×</button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {visiveis.length === 0 && (
          <div style={{ padding: '32px', textAlign: 'center', fontSize: 13, color: t.textFaint }}>Nenhum desconto encontrado.</div>
        )}
      </div>
    </div>
  )
}
