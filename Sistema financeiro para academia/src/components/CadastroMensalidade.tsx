import { useState } from 'react'
import { planosMensalidade as initialPlanos, type PlanoMensalidade, FAIXA_COLOR, TODAS_FAIXAS, type Faixa, fmtMoeda } from '../data'
import { useTheme, tok } from '../theme'

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      fontSize: 11, padding: '2px 8px', borderRadius: 2,
      background: color === '#e8eaf0' || color === '#444'
        ? 'rgba(128,128,128,0.12)'
        : `${color}22`,
      color,
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: color, display: 'inline-block' }} />
      {label}
    </span>
  )
}

const EMPTY: Omit<PlanoMensalidade, 'id' | 'criadoEm'> = {
  nome: '',
  descricao: '',
  valor: 0,
  faixas: [],
  diaVencimento: 10,
  ativo: true,
}

export default function CadastroMensalidade() {
  const { theme } = useTheme()
  const t = tok(theme)
  const [planos, setPlanos] = useState(initialPlanos)
  const [form, setForm] = useState({ ...EMPTY })
  const [editId, setEditId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [nextId, setNextId] = useState(initialPlanos.length + 1)

  function openNew() {
    setForm({ ...EMPTY })
    setEditId(null)
    setShowForm(true)
  }

  function openEdit(p: PlanoMensalidade) {
    setForm({ nome: p.nome, descricao: p.descricao, valor: p.valor, faixas: [...p.faixas], diaVencimento: p.diaVencimento, ativo: p.ativo })
    setEditId(p.id)
    setShowForm(true)
  }

  function toggleFaixa(f: Faixa) {
    setForm(prev => ({
      ...prev,
      faixas: prev.faixas.includes(f) ? prev.faixas.filter(x => x !== f) : [...prev.faixas, f],
    }))
  }

  function salvar() {
    if (!form.nome || form.valor <= 0) return
    if (editId !== null) {
      setPlanos(prev => prev.map(p => p.id === editId ? { ...p, ...form } : p))
    } else {
      setPlanos(prev => [...prev, { ...form, id: nextId, criadoEm: new Date().toISOString().slice(0, 10) }])
      setNextId(n => n + 1)
    }
    setShowForm(false)
  }

  function toggleAtivo(id: number) {
    setPlanos(prev => prev.map(p => p.id === id ? { ...p, ativo: !p.ativo } : p))
  }

  function excluir(id: number) {
    setPlanos(prev => prev.filter(p => p.id !== id))
  }

  const input = (extra?: object) => ({
    padding: '9px 12px',
    background: t.inputBg,
    border: `1px solid ${t.inputBorder}`,
    color: t.text,
    fontSize: 13,
    fontFamily: "'Inter', sans-serif",
    borderRadius: 3,
    width: '100%',
    ...extra,
  } as React.CSSProperties)

  return (
    <div style={{ padding: '32px 36px', maxWidth: 960, color: t.text }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28 }}>
        <div>
          <h1 style={{ fontFamily: "'Roboto Slab', serif", fontSize: 26, fontWeight: 700, color: t.text, margin: '0 0 4px' }}>Planos de Mensalidade</h1>
          <p style={{ margin: 0, fontSize: 13, color: t.textMuted }}>{planos.filter(p => p.ativo).length} planos ativos · {planos.filter(p => !p.ativo).length} inativos</p>
        </div>
        <button
          onClick={openNew}
          style={{
            padding: '9px 20px', background: '#c41e3a', border: 'none',
            color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', borderRadius: 3,
            fontFamily: "'Inter', sans-serif",
          }}
        >+ Novo Plano</button>
      </div>

      {/* Formulário */}
      {showForm && (
        <div style={{
          background: t.card, border: `1px solid ${t.border}`,
          padding: '24px 28px', marginBottom: 24, borderRadius: 4,
          boxShadow: t.shadow,
        }}>
          <h2 style={{ fontFamily: "'Roboto Slab', serif", fontSize: 16, fontWeight: 600, color: t.text, margin: '0 0 20px' }}>
            {editId ? 'Editar Plano' : 'Novo Plano de Mensalidade'}
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
            <div>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>Nome do Plano *</label>
              <input style={input()} value={form.nome} onChange={e => setForm(p => ({ ...p, nome: e.target.value }))} placeholder="Ex: Plano Iniciante" />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>Valor Mensal (R$) *</label>
              <input type="number" min={0} step={5} style={input()} value={form.valor || ''} onChange={e => setForm(p => ({ ...p, valor: parseFloat(e.target.value) || 0 }))} placeholder="0,00" />
            </div>
            <div style={{ gridColumn: '1/-1' }}>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>Descrição</label>
              <input style={input()} value={form.descricao} onChange={e => setForm(p => ({ ...p, descricao: e.target.value }))} placeholder="Descrição do plano" />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>Dia de Vencimento</label>
              <input type="number" min={1} max={28} style={input()} value={form.diaVencimento} onChange={e => setForm(p => ({ ...p, diaVencimento: parseInt(e.target.value) || 10 }))} />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>Status</label>
              <select style={input()} value={form.ativo ? 'ativo' : 'inativo'} onChange={e => setForm(p => ({ ...p, ativo: e.target.value === 'ativo' }))}>
                <option value="ativo">Ativo</option>
                <option value="inativo">Inativo</option>
              </select>
            </div>
          </div>

          <div style={{ marginBottom: 20 }}>
            <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: t.textMuted, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Faixas Contempladas</label>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {TODAS_FAIXAS.map(f => {
                const sel = form.faixas.includes(f)
                const color = FAIXA_COLOR[f]
                return (
                  <button
                    key={f}
                    onClick={() => toggleFaixa(f)}
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: 5,
                      padding: '5px 12px', fontSize: 12, cursor: 'pointer', borderRadius: 2,
                      fontFamily: "'Inter', sans-serif",
                      background: sel ? (color === '#e8eaf0' || color === '#444' ? 'rgba(128,128,128,0.15)' : `${color}22`) : t.inputBg,
                      border: `1px solid ${sel ? color : t.inputBorder}`,
                      color: sel ? (color === '#e8eaf0' ? '#555' : color) : t.textMuted,
                    }}
                  >
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, display: 'inline-block', border: f === 'Branca' ? `1px solid ${t.inputBorder}` : 'none' }} />
                    {f}
                  </button>
                )
              })}
            </div>
          </div>

          {form.valor > 0 && (
            <div style={{ padding: '12px 16px', background: 'rgba(196,30,58,0.07)', border: '1px solid rgba(196,30,58,0.15)', borderRadius: 3, marginBottom: 16 }}>
              <span style={{ fontSize: 12, color: t.textSub }}>Valor do plano: </span>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, fontSize: 16, color: '#c41e3a' }}>{fmtMoeda(form.valor)}</span>
              <span style={{ fontSize: 12, color: t.textMuted }}> · Vence todo dia {form.diaVencimento}</span>
            </div>
          )}

          <div style={{ display: 'flex', gap: 10 }}>
            <button onClick={salvar} style={{ padding: '9px 22px', background: '#c41e3a', border: 'none', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', borderRadius: 3, fontFamily: "'Inter', sans-serif" }}>
              {editId ? 'Salvar Alterações' : 'Cadastrar Plano'}
            </button>
            <button onClick={() => setShowForm(false)} style={{ padding: '9px 16px', background: 'none', border: `1px solid ${t.border}`, color: t.textMuted, fontSize: 13, cursor: 'pointer', borderRadius: 3, fontFamily: "'Inter', sans-serif" }}>
              Cancelar
            </button>
          </div>
        </div>
      )}

      {/* Lista de planos */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {planos.map(p => (
          <div key={p.id} style={{
            background: t.card, border: `1px solid ${t.border}`,
            padding: '18px 22px', borderRadius: 4,
            opacity: p.ativo ? 1 : 0.55,
            boxShadow: t.shadow,
          }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                  <span style={{ fontFamily: "'Roboto Slab', serif", fontSize: 15, fontWeight: 600, color: t.text }}>{p.nome}</span>
                  <span style={{
                    fontSize: 10, padding: '2px 7px', borderRadius: 2,
                    background: p.ativo ? 'rgba(34,197,94,0.1)' : 'rgba(107,122,153,0.1)',
                    color: p.ativo ? '#22c55e' : '#6b7a99',
                  }}>{p.ativo ? 'Ativo' : 'Inativo'}</span>
                </div>
                <p style={{ margin: '0 0 10px', fontSize: 12, color: t.textMuted }}>{p.descricao}</p>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {p.faixas.map(f => <Badge key={f} label={f} color={FAIXA_COLOR[f]} />)}
                </div>
              </div>
              <div style={{ textAlign: 'right', flexShrink: 0 }}>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 22, fontWeight: 700, color: '#c41e3a' }}>{fmtMoeda(p.valor)}</div>
                <div style={{ fontSize: 11, color: t.textMuted }}>Vence dia {p.diaVencimento}</div>
                <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', marginTop: 10 }}>
                  <button onClick={() => openEdit(p)} style={{ padding: '4px 10px', background: 'none', border: `1px solid ${t.border}`, color: t.textMuted, fontSize: 11, cursor: 'pointer', borderRadius: 2, fontFamily: "'Inter', sans-serif" }}>Editar</button>
                  <button onClick={() => toggleAtivo(p.id)} style={{ padding: '4px 10px', background: 'none', border: `1px solid ${t.border}`, color: t.textMuted, fontSize: 11, cursor: 'pointer', borderRadius: 2, fontFamily: "'Inter', sans-serif" }}>{p.ativo ? 'Desativar' : 'Ativar'}</button>
                  <button onClick={() => excluir(p.id)} style={{ padding: '4px 10px', background: 'rgba(196,30,58,0.08)', border: '1px solid rgba(196,30,58,0.2)', color: '#c41e3a', fontSize: 11, cursor: 'pointer', borderRadius: 2, fontFamily: "'Inter', sans-serif" }}>Excluir</button>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
