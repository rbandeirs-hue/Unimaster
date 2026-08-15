import { useState } from 'react'
import { alunos, type Aluno, FAIXA_COLOR, fmtMoeda } from '../data'
import { useTheme, tok } from '../theme'

type SortKey = 'nome' | 'faixa' | 'mensalidade' | 'ingresso'

export default function Students() {
  const { theme } = useTheme()
  const t = tok(theme)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<SortKey>('nome')
  const [mostrarInativos, setMostrarInativos] = useState(false)
  const [selected, setSelected] = useState<Aluno | null>(null)

  const lista = alunos
    .filter(a => mostrarInativos ? true : a.ativo)
    .filter(a => a.nome.toLowerCase().includes(search.toLowerCase()) || a.faixa.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      if (sort === 'nome') return a.nome.localeCompare(b.nome)
      if (sort === 'mensalidade') return b.mensalidade - a.mensalidade
      if (sort === 'ingresso') return b.ingresso.localeCompare(a.ingresso)
      return a.faixa.localeCompare(b.faixa)
    })

  const inputStyle: React.CSSProperties = {
    flex: 1, padding: '8px 12px',
    background: t.inputBg, border: `1px solid ${t.inputBorder}`,
    color: t.text, fontSize: 13, fontFamily: "'Inter', sans-serif",
    outline: 'none', borderRadius: 3,
  }

  return (
    <div style={{ padding: '32px 36px', maxWidth: 1000, color: t.text }}>
      <div style={{ marginBottom: 26 }}>
        <h1 style={{ fontFamily: "'Roboto Slab', serif", fontSize: 26, fontWeight: 700, color: t.text, margin: '0 0 4px' }}>Alunos</h1>
        <p style={{ margin: 0, fontSize: 13, color: t.textMuted }}>{alunos.filter(a => a.ativo).length} ativos · {alunos.filter(a => !a.ativo).length} inativos</p>
      </div>

      <div style={{ display: 'flex', gap: 10, marginBottom: 14, alignItems: 'center' }}>
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Buscar aluno ou faixa..." style={inputStyle} />
        <select value={sort} onChange={e => setSort(e.target.value as SortKey)} style={{ padding: '8px 10px', background: t.inputBg, border: `1px solid ${t.inputBorder}`, color: t.textSub, fontSize: 12, fontFamily: "'Inter', sans-serif", borderRadius: 3 }}>
          <option value="nome">Nome</option>
          <option value="faixa">Faixa</option>
          <option value="mensalidade">Mensalidade</option>
          <option value="ingresso">Ingresso</option>
        </select>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: t.textMuted, cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' }}>
          <input type="checkbox" checked={mostrarInativos} onChange={e => setMostrarInativos(e.target.checked)} style={{ accentColor: '#c41e3a' }} />
          Ver inativos
        </label>
      </div>

      <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 4, overflow: 'hidden', boxShadow: t.shadow }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${t.theadBorder}` }}>
              {['Aluno', 'Faixa', 'Telefone', 'Mensalidade', 'Ingresso', 'Status'].map(h => (
                <th key={h} style={{ padding: '11px 16px', textAlign: 'left', fontSize: 10, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: t.textFaint }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lista.map(a => (
              <tr key={a.id} onClick={() => setSelected(selected?.id === a.id ? null : a)}
                style={{ borderBottom: `1px solid ${t.rowBorder}`, cursor: 'pointer', background: selected?.id === a.id ? t.navActive : 'transparent', transition: 'background 0.1s' }}
                onMouseEnter={e => { if (selected?.id !== a.id) (e.currentTarget as HTMLTableRowElement).style.background = t.cardHover }}
                onMouseLeave={e => { (e.currentTarget as HTMLTableRowElement).style.background = selected?.id === a.id ? t.navActive : 'transparent' }}
              >
                <td style={{ padding: '11px 16px' }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: t.text }}>{a.nome}</div>
                  <div style={{ fontSize: 11, color: t.textMuted }}>{a.email}</div>
                </td>
                <td style={{ padding: '11px 16px' }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: t.textSub }}>
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: FAIXA_COLOR[a.faixa], display: 'inline-block', border: a.faixa === 'Branca' ? `1px solid ${t.border}` : 'none' }} />
                    {a.faixa}
                  </span>
                </td>
                <td style={{ padding: '11px 16px', fontSize: 12, color: t.textMuted, fontFamily: "'JetBrains Mono', monospace" }}>{a.telefone}</td>
                <td style={{ padding: '11px 16px', fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: t.text }}>{fmtMoeda(a.mensalidade)}</td>
                <td style={{ padding: '11px 16px', fontSize: 12, color: t.textMuted }}>{new Date(a.ingresso + 'T00:00').toLocaleDateString('pt-BR')}</td>
                <td style={{ padding: '11px 16px' }}>
                  <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 2, background: a.ativo ? 'rgba(34,197,94,0.1)' : 'rgba(107,122,153,0.1)', color: a.ativo ? '#22c55e' : '#6b7a99' }}>
                    {a.ativo ? 'Ativo' : 'Inativo'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && (
        <div style={{ marginTop: 16, background: t.card, border: `1px solid rgba(196,30,58,0.2)`, padding: '20px 24px', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 20, borderRadius: 4, boxShadow: t.shadow }}>
          <div>
            <div style={{ fontSize: 10, color: t.textFaint, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 5 }}>Aluno</div>
            <div style={{ fontFamily: "'Roboto Slab', serif", fontSize: 17, fontWeight: 600, color: t.text }}>{selected.nome}</div>
            <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>{selected.email} · {selected.telefone}</div>
          </div>
          <div>
            <div style={{ fontSize: 10, color: t.textFaint, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 5 }}>Graduação</div>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 14, color: t.text, fontWeight: 500 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: FAIXA_COLOR[selected.faixa], display: 'inline-block' }} />
              Faixa {selected.faixa}
            </span>
            <div style={{ fontSize: 11, color: t.textMuted, marginTop: 3 }}>Desde {new Date(selected.ingresso + 'T00:00').toLocaleDateString('pt-BR')}</div>
          </div>
          <div>
            <div style={{ fontSize: 10, color: t.textFaint, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 5 }}>Mensalidade</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 22, fontWeight: 700, color: '#c41e3a' }}>{fmtMoeda(selected.mensalidade)}</div>
            <div style={{ fontSize: 11, color: t.textMuted }}>Vence todo dia 10</div>
          </div>
          <button onClick={() => setSelected(null)} style={{ gridColumn: '1/-1', background: 'none', border: 'none', color: t.textFaint, fontSize: 11, cursor: 'pointer', textAlign: 'left', padding: 0 }}>Fechar ×</button>
        </div>
      )}
    </div>
  )
}
