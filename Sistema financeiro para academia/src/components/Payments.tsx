import { useState } from 'react'
import { pagamentos, nomeAluno, STATUS_COLOR, fmtMoeda, fmtMes, type Status } from '../data'

const FORMAS = ['Todos', 'PIX', 'Cartão', 'Boleto', 'Dinheiro']
const STATUS_LIST: ('Todos' | Status)[] = ['Todos', 'Pago', 'Pendente', 'Atrasado', 'Isento']

export default function Payments() {
  const [filtroStatus, setFiltroStatus] = useState<'Todos' | Status>('Todos')
  const [filtroForma, setFiltroForma] = useState('Todos')
  const [filtroMes, setFiltroMes] = useState('Todos')

  const meses = [...new Set(pagamentos.map(p => p.mes))].sort().reverse()

  const lista = pagamentos
    .filter(p => filtroStatus === 'Todos' || p.status === filtroStatus)
    .filter(p => filtroForma === 'Todos' || p.formaPagamento === filtroForma)
    .filter(p => filtroMes === 'Todos' || p.mes === filtroMes)
    .sort((a, b) => b.mes.localeCompare(a.mes))

  const totalPago = lista.filter(p => p.status === 'Pago').reduce((s, p) => s + p.valor, 0)

  return (
    <div style={{ padding: '32px 36px', maxWidth: 1000 }}>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontFamily: "'Roboto Slab', serif", fontSize: 26, fontWeight: 700, color: '#e8eaf0', margin: '0 0 4px' }}>Histórico de Pagamentos</h1>
        <p style={{ margin: 0, fontSize: 13, color: '#6b7a99' }}>{lista.length} registros encontrados · Total pago: <span style={{ fontFamily: "'JetBrains Mono', monospace", color: '#22c55e' }}>{fmtMoeda(totalPago)}</span></p>
      </div>

      {/* Filtros */}
      <div style={{ display: 'flex', gap: 24, marginBottom: 20, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 10, color: '#3d4a63', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 6 }}>Status</div>
          <div style={{ display: 'flex', gap: 4 }}>
            {STATUS_LIST.map(s => {
              const active = filtroStatus === s
              const sc = s !== 'Todos' ? STATUS_COLOR[s] : null
              return (
                <button key={s} onClick={() => setFiltroStatus(s)} style={{
                  padding: '4px 10px', fontSize: 11,
                  background: active ? (sc?.bg ?? 'rgba(255,255,255,0.1)') : '#161c27',
                  border: `1px solid ${active ? (sc?.text ?? 'rgba(255,255,255,0.2)') : 'rgba(255,255,255,0.07)'}`,
                  color: active ? (sc?.text ?? '#e8eaf0') : '#6b7a99',
                  cursor: 'pointer', borderRadius: 2, fontFamily: "'Inter', sans-serif",
                }}>{s}</button>
              )
            })}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: '#3d4a63', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 6 }}>Forma</div>
          <div style={{ display: 'flex', gap: 4 }}>
            {FORMAS.map(f => (
              <button key={f} onClick={() => setFiltroForma(f)} style={{
                padding: '4px 10px', fontSize: 11,
                background: filtroForma === f ? 'rgba(255,255,255,0.1)' : '#161c27',
                border: `1px solid ${filtroForma === f ? 'rgba(255,255,255,0.25)' : 'rgba(255,255,255,0.07)'}`,
                color: filtroForma === f ? '#e8eaf0' : '#6b7a99',
                cursor: 'pointer', borderRadius: 2, fontFamily: "'Inter', sans-serif",
              }}>{f}</button>
            ))}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: '#3d4a63', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 6 }}>Mês</div>
          <div style={{ display: 'flex', gap: 4 }}>
            <button onClick={() => setFiltroMes('Todos')} style={{
              padding: '4px 10px', fontSize: 11,
              background: filtroMes === 'Todos' ? 'rgba(255,255,255,0.1)' : '#161c27',
              border: `1px solid ${filtroMes === 'Todos' ? 'rgba(255,255,255,0.25)' : 'rgba(255,255,255,0.07)'}`,
              color: filtroMes === 'Todos' ? '#e8eaf0' : '#6b7a99',
              cursor: 'pointer', borderRadius: 2, fontFamily: "'Inter', sans-serif",
            }}>Todos</button>
            {meses.map(m => (
              <button key={m} onClick={() => setFiltroMes(m)} style={{
                padding: '4px 10px', fontSize: 11,
                background: filtroMes === m ? 'rgba(255,255,255,0.1)' : '#161c27',
                border: `1px solid ${filtroMes === m ? 'rgba(255,255,255,0.25)' : 'rgba(255,255,255,0.07)'}`,
                color: filtroMes === m ? '#e8eaf0' : '#6b7a99',
                cursor: 'pointer', borderRadius: 2, fontFamily: "'Inter', sans-serif",
              }}>{fmtMes(m)}</button>
            ))}
          </div>
        </div>
      </div>

      {/* Tabela */}
      <div style={{ background: '#161c27', border: '1px solid rgba(255,255,255,0.07)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
              {['#', 'Aluno', 'Mês', 'Vencimento', 'Pagamento', 'Forma', 'Valor', 'Status'].map(h => (
                <th key={h} style={{ padding: '12px 14px', textAlign: 'left', fontSize: 10, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#3d4a63' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lista.map(p => {
              const sc = STATUS_COLOR[p.status]
              return (
                <tr key={p.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}
                  onMouseEnter={e => (e.currentTarget as HTMLTableRowElement).style.background = 'rgba(255,255,255,0.02)'}
                  onMouseLeave={e => (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'}
                >
                  <td style={{ padding: '10px 14px', fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: '#3d4a63' }}>{String(p.id).padStart(3, '0')}</td>
                  <td style={{ padding: '10px 14px', fontSize: 13, color: '#e8eaf0', fontWeight: 500 }}>{nomeAluno(p.alunoId)}</td>
                  <td style={{ padding: '10px 14px', fontSize: 12, color: '#a0aabe' }}>{fmtMes(p.mes)}</td>
                  <td style={{ padding: '10px 14px', fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: '#6b7a99' }}>{p.vencimento}</td>
                  <td style={{ padding: '10px 14px', fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: '#6b7a99' }}>
                    {p.dataPagamento ? new Date(p.dataPagamento + 'T00:00').toLocaleDateString('pt-BR') : '—'}
                  </td>
                  <td style={{ padding: '10px 14px', fontSize: 12, color: '#6b7a99' }}>{p.formaPagamento ?? '—'}</td>
                  <td style={{ padding: '10px 14px', fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: '#e8eaf0', fontWeight: 500 }}>{fmtMoeda(p.valor)}</td>
                  <td style={{ padding: '10px 14px' }}>
                    <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 2, background: sc.bg, color: sc.text }}>{p.status}</span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>

        {lista.length === 0 && (
          <div style={{ padding: '32px 16px', textAlign: 'center', fontSize: 13, color: '#3d4a63' }}>Nenhum registro encontrado para os filtros selecionados.</div>
        )}
      </div>

      {/* Resumo por forma */}
      {filtroStatus === 'Pago' || filtroStatus === 'Todos' ? (
        <div style={{ marginTop: 20, display: 'flex', gap: 12 }}>
          {['PIX', 'Cartão', 'Boleto', 'Dinheiro'].map(f => {
            const total = lista.filter(p => p.status === 'Pago' && p.formaPagamento === f).reduce((s, p) => s + p.valor, 0)
            if (!total) return null
            return (
              <div key={f} style={{ background: '#161c27', border: '1px solid rgba(255,255,255,0.07)', padding: '14px 18px', flex: 1 }}>
                <div style={{ fontSize: 10, color: '#3d4a63', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4 }}>{f}</div>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 16, fontWeight: 600, color: '#22c55e' }}>{fmtMoeda(total)}</div>
              </div>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
