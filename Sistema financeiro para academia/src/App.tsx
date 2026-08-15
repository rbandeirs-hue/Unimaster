import { useState } from 'react'
import { useTheme, tok } from './theme'
import Dashboard from './components/Dashboard'
import Students from './components/Students'
import Payments from './components/Payments'
import Mensalidades from './components/Mensalidades'
import CadastroMensalidade from './components/CadastroMensalidade'
import Descontos from './components/Descontos'
import GerarCobranca from './components/GerarCobranca'

type View = 'dashboard' | 'alunos' | 'pagamentos' | 'mensalidades' | 'planos' | 'descontos' | 'cobrancas'

const NAV_GROUPS = [
  {
    label: 'Visão Geral',
    items: [
      { id: 'dashboard', label: 'Dashboard', icon: IconDash },
    ],
  },
  {
    label: 'Gestão',
    items: [
      { id: 'alunos', label: 'Alunos', icon: IconUsers },
      { id: 'planos', label: 'Planos', icon: IconList },
      { id: 'descontos', label: 'Descontos', icon: IconTag },
    ],
  },
  {
    label: 'Financeiro',
    items: [
      { id: 'cobrancas', label: 'Gerar Cobranças', icon: IconBolt },
      { id: 'mensalidades', label: 'Mensalidades', icon: IconCalendar },
      { id: 'pagamentos', label: 'Histórico', icon: IconCoin },
    ],
  },
] as const

function IconDash({ c }: { c: string }) {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="14" y="14" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /></svg>
}
function IconUsers({ c }: { c: string }) {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></svg>
}
function IconCalendar({ c }: { c: string }) {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" /></svg>
}
function IconCoin({ c }: { c: string }) {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M14.8 9A2 2 0 0 0 13 8h-2a2 2 0 0 0 0 4h2a2 2 0 0 1 0 4h-2a2 2 0 0 1-1.8-1" /><line x1="12" y1="6" x2="12" y2="8" /><line x1="12" y1="16" x2="12" y2="18" /></svg>
}
function IconList({ c }: { c: string }) {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" /><line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" /></svg>
}
function IconTag({ c }: { c: string }) {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" /><line x1="7" y1="7" x2="7.01" y2="7" /></svg>
}
function IconBolt({ c }: { c: string }) {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" /></svg>
}
function IconSun({ c }: { c: string }) {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="5" /><line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" /><line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" /><line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" /><line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" /></svg>
}
function IconMoon({ c }: { c: string }) {
  return <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" /></svg>
}

export default function App() {
  const [view, setView] = useState<View>('dashboard')
  const { theme, toggle } = useTheme()
  const t = tok(theme)

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', background: t.bg }}>
      {/* Sidebar */}
      <aside style={{
        width: 220, flexShrink: 0,
        background: t.bgSide,
        borderRight: `1px solid ${t.borderSide}`,
        display: 'flex', flexDirection: 'column',
      }}>
        {/* Logo */}
        <div style={{ padding: '24px 22px 20px', borderBottom: `1px solid ${t.borderSide}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              width: 32, height: 32, background: '#c41e3a',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontFamily: "'Roboto Slab', serif", fontWeight: 700, fontSize: 16, color: '#fff', flexShrink: 0,
            }}>柔</div>
            <div>
              <div style={{ fontFamily: "'Roboto Slab', serif", fontWeight: 600, fontSize: 13, color: t.text, lineHeight: 1.2 }}>Judô FC</div>
              <div style={{ fontSize: 10, color: t.textFaint, letterSpacing: '0.08em', textTransform: 'uppercase', marginTop: 2 }}>Financeiro</div>
            </div>
          </div>
        </div>

        {/* Nav groups */}
        <nav style={{ flex: 1, padding: '14px 10px', overflowY: 'auto' }}>
          {NAV_GROUPS.map(group => (
            <div key={group.label} style={{ marginBottom: 18 }}>
              <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase', color: t.textFaint, padding: '0 12px', marginBottom: 4 }}>{group.label}</div>
              {group.items.map(({ id, label, icon: Icon }) => {
                const active = view === id
                return (
                  <button
                    key={id}
                    onClick={() => setView(id as View)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 9,
                      width: '100%', padding: '8px 12px',
                      background: active ? t.navActive : 'transparent',
                      border: 'none',
                      borderLeft: `2px solid ${active ? '#c41e3a' : 'transparent'}`,
                      color: active ? t.text : t.textMuted,
                      fontSize: 12.5, fontFamily: "'Inter', sans-serif", fontWeight: active ? 500 : 400,
                      cursor: 'pointer', textAlign: 'left',
                      borderRadius: '0 3px 3px 0',
                      marginBottom: 1, transition: 'all 0.12s',
                    }}
                  >
                    <Icon c={active ? '#c41e3a' : t.textMuted} />
                    {label}
                  </button>
                )
              })}
            </div>
          ))}
        </nav>

        {/* Footer: tema + info */}
        <div style={{ padding: '14px 20px', borderTop: `1px solid ${t.borderSide}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontSize: 11, color: t.textFaint }}>Ago 2026</div>
          <button
            onClick={toggle}
            title={theme === 'dark' ? 'Modo claro' : 'Modo escuro'}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 28, height: 28, borderRadius: 3,
              background: t.inputBg, border: `1px solid ${t.border}`,
              cursor: 'pointer', transition: 'all 0.15s',
            }}
          >
            {theme === 'dark' ? <IconSun c={t.textMuted} /> : <IconMoon c={t.textMuted} />}
          </button>
        </div>
      </aside>

      {/* Main */}
      <main style={{ flex: 1, overflow: 'auto', background: t.bg }}>
        {view === 'dashboard'     && <Dashboard />}
        {view === 'alunos'        && <Students />}
        {view === 'mensalidades'  && <Mensalidades />}
        {view === 'pagamentos'    && <Payments />}
        {view === 'planos'        && <CadastroMensalidade />}
        {view === 'descontos'     && <Descontos />}
        {view === 'cobrancas'     && <GerarCobranca />}
      </main>
    </div>
  )
}
