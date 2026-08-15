import { useState } from 'react'
import { alunos, pagamentos as pgData, type Pagamento, STATUS_COLOR, FAIXA_COLOR, fmtMoeda, fmtMes } from '../data'

const MESES = ['2026-08', '2026-07']

export default function Mensalidades() {
  const [mes, setMes] = useState('2026-08')
  const [payments, setPayments] = useState(pgData)
  const [modalId, setModalId] = useState<number | null>(null)
  const [forma, setForma] = useState('PIX')

  const pgMes = payments.filter(p => p.mes === mes)
  const totalArrecadado = pgMes.filter(p => p.status === 'Pago').reduce((s, p) => s + p.valor, 0)
  const totalPendente = pgMes.filter(p => p.status !== 'Pago' && p.status !== 'Isento').reduce((s, p) => s + p.valor, 0)

  function registrarPagamento(p: Pagamento) {
    setPayments(prev => prev.map(pp =>
      pp.id === p.id
        ? { ...pp, status: 'Pago', dataPagamento: new Date().toISOString().slice(0, 10), formaPagamento: forma }
        : pp
    ))
    setModalId(null)
  }

  const modal = modalId !== null ? payments.find(p => p.id === modalId) : null
  const modalAluno = modal ? alunos.find(a => a.id === modal.alunoId) : null

  return (
    <div style={{ padding: '32px 36px', maxWidth: 1000 }}>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontFamily: "'Roboto Slab', serif", fontSize: 26, fontWeight: 700, color: '#e8eaf0', margin: '0 0 4px' }}>Mensalidades</h1>
        <p style={{ margin: 0, fontSize: 13, color: '#6b7a99' }}>Gestão de cobranças mensais</p>
      </div>

      {/* Seletor de mês e resumo */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20, alignItems: 'center' }}>
        {MESES.map(m => (
          <button
            key={m}
            onClick={() => setMes(m)}
            style={{
              padding: '7px 18px',
              background: mes === m ? '#c41e3a' : '#161c27',
              border: `1px solid ${mes === m ? '#c41e3a' : 'rgba(255,255,255,0.08)'}`,
              color: mes === m ? '#fff' : '#6b7a99',
              fontSize: 13, fontFamily: "'Inter', sans-serif", fontWeight: mes === m ? 600 : 400,
              cursor: 'pointer', borderRadius: 3, transition: 'all 0.15s',
            }}
          >
            {fmtMes(m)}
          </button>
        ))}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 20 }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 11, color: '#6b7a99', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Arrecadado</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 18, fontWeight: 600, color: '#22c55e' }}>{fmtMoeda(totalArrecadado)}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 11, color: '#6b7a99', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Pendente</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 18, fontWeight: 600, color: '#f5c518' }}>{fmtMoeda(totalPendente)}</div>
          </div>
        </div>
      </div>

      {/* Barra de progresso */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
          <span style={{ fontSize: 11, color: '#6b7a99' }}>Taxa de arrecadação</span>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: '#a0aabe' }}>
            {pgMes.filter(p => p.status === 'Pago').length}/{pgMes.filter(p => p.status !== 'Isento').length} alunos
          </span>
        </div>
        <div style={{ height: 6, background: 'rgba(255,255,255,0.06)', borderRadius: 3 }}>
          <div style={{
            height: '100%', borderRadius: 3,
            width: `${Math.round((pgMes.filter(p => p.status === 'Pago').length / pgMes.filter(p => p.status !== 'Isento').length) * 100)}%`,
            background: 'linear-gradient(90deg, #22c55e, #16a34a)',
            transition: 'width 0.5s',
          }} />
        </div>
      </div>

      {/* Tabela */}
      <div style={{ background: '#161c27', border: '1px solid rgba(255,255,255,0.07)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
              {['Aluno', 'Faixa', 'Vencimento', 'Valor', 'Status', 'Pagamento', 'Ação'].map(h => (
                <th key={h} style={{ padding: '12px 16px', textAlign: 'left', fontSize: 10, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#3d4a63' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pgMes.map(p => {
              const aluno = alunos.find(a => a.id === p.alunoId)
              const sc = STATUS_COLOR[p.status]
              const pago = p.status === 'Pago' || p.status === 'Isento'
              return (
                <tr key={p.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                  <td style={{ padding: '12px 16px', fontSize: 13, fontWeight: 500, color: '#e8eaf0' }}>{aluno?.nome}</td>
                  <td style={{ padding: '12px 16px' }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: '#a0aabe' }}>
                      <span style={{ width: 7, height: 7, borderRadius: '50%', background: aluno ? FAIXA_COLOR[aluno.faixa] : '#6b7a99', display: 'inline-block' }} />
                      {aluno?.faixa}
                    </span>
                  </td>
                  <td style={{ padding: '12px 16px', fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: '#6b7a99' }}>{p.vencimento}</td>
                  <td style={{ padding: '12px 16px', fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: '#e8eaf0' }}>{fmtMoeda(p.valor)}</td>
                  <td style={{ padding: '12px 16px' }}>
                    <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 2, background: sc.bg, color: sc.text }}>{p.status}</span>
                  </td>
                  <td style={{ padding: '12px 16px', fontSize: 12, color: '#6b7a99' }}>
                    {p.dataPagamento ? (
                      <span>{new Date(p.dataPagamento + 'T00:00').toLocaleDateString('pt-BR')} · {p.formaPagamento}</span>
                    ) : '—'}
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    {!pago && (
                      <button
                        onClick={() => setModalId(p.id)}
                        style={{
                          padding: '5px 12px', background: 'rgba(196,30,58,0.12)', border: '1px solid rgba(196,30,58,0.3)',
                          color: '#f05070', fontSize: 11, cursor: 'pointer', borderRadius: 2,
                          fontFamily: "'Inter', sans-serif", transition: 'all 0.15s',
                        }}
                      >
                        Registrar
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Modal de pagamento */}
      {modal && modalAluno && (
        <div style={{
          position: 'fixed', inset: 0,
          background: 'rgba(0,0,0,0.7)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 1000,
        }}
          onClick={() => setModalId(null)}
        >
          <div style={{
            background: '#161c27',
            border: '1px solid rgba(196,30,58,0.25)',
            padding: '32px 36px',
            width: 400, borderRadius: 4,
          }}
            onClick={e => e.stopPropagation()}
          >
            <h2 style={{ fontFamily: "'Roboto Slab', serif", fontSize: 18, fontWeight: 700, color: '#e8eaf0', margin: '0 0 4px' }}>Registrar Pagamento</h2>
            <p style={{ fontSize: 12, color: '#6b7a99', margin: '0 0 24px' }}>{modalAluno.nome} · {fmtMes(modal.mes)}</p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginBottom: 24 }}>
              <div>
                <div style={{ fontSize: 10, color: '#6b7a99', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4 }}>Valor</div>
                <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 24, fontWeight: 700, color: '#c41e3a' }}>{fmtMoeda(modal.valor)}</div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: '#6b7a99', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 6 }}>Forma de pagamento</div>
                <div style={{ display: 'flex', gap: 8 }}>
                  {['PIX', 'Cartão', 'Boleto', 'Dinheiro'].map(f => (
                    <button
                      key={f}
                      onClick={() => setForma(f)}
                      style={{
                        padding: '6px 14px', fontSize: 12,
                        background: forma === f ? '#c41e3a' : '#0d1117',
                        border: `1px solid ${forma === f ? '#c41e3a' : 'rgba(255,255,255,0.1)'}`,
                        color: forma === f ? '#fff' : '#6b7a99',
                        cursor: 'pointer', borderRadius: 2,
                        fontFamily: "'Inter', sans-serif",
                      }}
                    >{f}</button>
                  ))}
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 10 }}>
              <button
                onClick={() => registrarPagamento(modal)}
                style={{
                  flex: 1, padding: '10px', background: '#c41e3a', border: 'none',
                  color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', borderRadius: 3,
                  fontFamily: "'Inter', sans-serif",
                }}
              >Confirmar Pagamento</button>
              <button
                onClick={() => setModalId(null)}
                style={{
                  padding: '10px 16px', background: 'none', border: '1px solid rgba(255,255,255,0.1)',
                  color: '#6b7a99', fontSize: 13, cursor: 'pointer', borderRadius: 3,
                  fontFamily: "'Inter', sans-serif",
                }}
              >Cancelar</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
