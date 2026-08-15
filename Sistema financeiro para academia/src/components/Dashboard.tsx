import { alunos, pagamentos, fmtMoeda, fmtMes, nomeAluno, STATUS_COLOR, FAIXA_COLOR } from '../data'
import { useTheme, tok } from '../theme'

const MES_ATUAL = '2026-08'
const MES_ANTERIOR = '2026-07'

function KpiCard({ label, value, sub, accent, t }: { label: string; value: string; sub?: string; accent?: boolean; t: ReturnType<typeof tok> }) {
  return (
    <div style={{ background: t.card, border: `1px solid ${t.border}`, padding: '20px 22px', display: 'flex', flexDirection: 'column', gap: 5, borderRadius: 4, boxShadow: t.shadow }}>
      <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase', color: t.textMuted }}>{label}</div>
      <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 26, fontWeight: 700, color: accent ? '#c41e3a' : t.text, lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: t.textFaint }}>{sub}</div>}
    </div>
  )
}

export default function Dashboard() {
  const { theme } = useTheme()
  const t = tok(theme)

  const pgAtual = pagamentos.filter(p => p.mes === MES_ATUAL)
  const pgAnterior = pagamentos.filter(p => p.mes === MES_ANTERIOR)

  const receitaAtual = pgAtual.filter(p => p.status === 'Pago').reduce((s, p) => s + p.valor, 0)
  const receitaAnterior = pgAnterior.filter(p => p.status === 'Pago').reduce((s, p) => s + p.valor, 0)
  const inadimplentes = pgAtual.filter(p => p.status === 'Atrasado' || p.status === 'Pendente').length
  const alunosAtivos = alunos.filter(a => a.ativo).length
  const adimplentesCount = pgAtual.filter(p => p.status === 'Pago').length
  const naoisentos = pgAtual.filter(p => p.status !== 'Isento').length
  const taxaAdimplencia = Math.round((adimplentesCount / naoisentos) * 100)
  const receitaPotencial = alunos.filter(a => a.ativo).reduce((s, a) => s + a.mensalidade, 0)

  const faixaCounts = alunos.filter(a => a.ativo).reduce((acc, a) => {
    acc[a.faixa] = (acc[a.faixa] || 0) + 1
    return acc
  }, {} as Record<string, number>)

  const atrasados = pgAtual.filter(p => p.status === 'Atrasado' || p.status === 'Pendente')

  return (
    <div style={{ padding: '32px 36px', maxWidth: 1100, color: t.text }}>
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4 }}>
          <h1 style={{ fontFamily: "'Roboto Slab', serif", fontSize: 26, fontWeight: 700, color: t.text, margin: 0 }}>Dashboard</h1>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: '#c41e3a', background: 'rgba(196,30,58,0.1)', padding: '2px 8px', border: '1px solid rgba(196,30,58,0.2)', borderRadius: 2 }}>Ago 2026</span>
        </div>
        <p style={{ margin: 0, fontSize: 13, color: t.textMuted }}>Visão geral financeira da academia</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
        <KpiCard t={t} label="Receita do Mês" value={fmtMoeda(receitaAtual)} sub={`Anterior: ${fmtMoeda(receitaAnterior)}`} />
        <KpiCard t={t} label="Receita Potencial" value={fmtMoeda(receitaPotencial)} sub="Se todos pagarem" />
        <KpiCard t={t} label="Inadimplentes" value={String(inadimplentes)} sub="Pendentes + Atrasados" accent={inadimplentes > 0} />
        <KpiCard t={t} label="Adimplência" value={`${taxaAdimplencia}%`} sub={`${alunosAtivos} alunos ativos`} />
      </div>

      {/* Barra de progresso */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
          <span style={{ fontSize: 11, color: t.textMuted }}>Taxa de arrecadação — {fmtMes(MES_ATUAL)}</span>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: t.textSub }}>{adimplentesCount}/{naoisentos}</span>
        </div>
        <div style={{ height: 6, background: t.border, borderRadius: 3 }}>
          <div style={{ width: `${taxaAdimplencia}%`, height: '100%', borderRadius: 3, background: 'linear-gradient(90deg,#22c55e,#16a34a)', transition: 'width 0.5s' }} />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 270px', gap: 16 }}>
        {/* Pendências */}
        <div style={{ background: t.card, border: `1px solid ${t.border}`, padding: '20px 22px', borderRadius: 4, boxShadow: t.shadow }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <h2 style={{ fontFamily: "'Roboto Slab', serif", fontSize: 14, fontWeight: 600, color: t.text, margin: 0 }}>Pendências — {fmtMes(MES_ATUAL)}</h2>
            <span style={{ fontSize: 11, color: t.textMuted }}>{atrasados.length} registros</span>
          </div>
          {atrasados.length === 0 && <div style={{ fontSize: 13, color: t.textFaint, padding: '16px 0' }}>Nenhuma pendência.</div>}
          {atrasados.map(p => {
            const aluno = alunos.find(a => a.id === p.alunoId)
            const sc = STATUS_COLOR[p.status]
            return (
              <div key={p.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '9px 0', borderBottom: `1px solid ${t.rowBorder}` }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{ width: 6, height: 6, borderRadius: '50%', background: aluno ? FAIXA_COLOR[aluno.faixa] : '#6b7a99', flexShrink: 0 }} />
                  <div>
                    <div style={{ fontSize: 13, color: t.text, fontWeight: 500 }}>{nomeAluno(p.alunoId)}</div>
                    <div style={{ fontSize: 11, color: t.textMuted }}>{aluno?.faixa}</div>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: t.text }}>{fmtMoeda(p.valor)}</span>
                  <span style={{ fontSize: 11, padding: '2px 7px', background: sc.bg, color: sc.text, borderRadius: 2 }}>{p.status}</span>
                </div>
              </div>
            )
          })}
        </div>

        {/* Faixas */}
        <div style={{ background: t.card, border: `1px solid ${t.border}`, padding: '20px 22px', borderRadius: 4, boxShadow: t.shadow }}>
          <h2 style={{ fontFamily: "'Roboto Slab', serif", fontSize: 14, fontWeight: 600, color: t.text, margin: '0 0 14px' }}>Alunos por Faixa</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
            {Object.entries(faixaCounts).map(([faixa, count]) => {
              const pct = Math.round((count / alunosAtivos) * 100)
              const color = FAIXA_COLOR[faixa as keyof typeof FAIXA_COLOR]
              const barColor = color === '#e8eaf0' ? '#aaa' : color === '#444' ? '#666' : color
              return (
                <div key={faixa}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                    <span style={{ fontSize: 12, color: t.textSub }}>{faixa}</span>
                    <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: t.textMuted }}>{count}</span>
                  </div>
                  <div style={{ height: 4, background: t.border, borderRadius: 2 }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: barColor, borderRadius: 2 }} />
                  </div>
                </div>
              )
            })}
          </div>
          <div style={{ paddingTop: 14, borderTop: `1px solid ${t.rowBorder}` }}>
            <div style={{ fontSize: 10, color: t.textFaint, marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Receita esperada</div>
            {alunos.filter(a => a.ativo).map(a => (
              <div key={a.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0' }}>
                <span style={{ fontSize: 11, color: t.textSub, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 120 }}>{a.nome.split(' ')[0]}</span>
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: t.textMuted }}>{fmtMoeda(a.mensalidade)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
