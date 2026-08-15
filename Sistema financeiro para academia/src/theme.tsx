import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'

type Theme = 'dark' | 'light'

interface ThemeCtx { theme: Theme; toggle: () => void }
const Ctx = createContext<ThemeCtx>({ theme: 'dark', toggle: () => {} })

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem('theme') as Theme) ?? 'dark')

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])

  return (
    <Ctx.Provider value={{ theme, toggle: () => setTheme(t => t === 'dark' ? 'light' : 'dark') }}>
      {children}
    </Ctx.Provider>
  )
}

export function useTheme() { return useContext(Ctx) }

// Tokens por tema
export function tok(theme: Theme) {
  const d = theme === 'dark'
  return {
    bg:          d ? '#0d1117' : '#f0f2f7',
    bgSide:      d ? '#0a0e17' : '#e8ebf2',
    card:        d ? '#161c27' : '#ffffff',
    cardHover:   d ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)',
    border:      d ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.09)',
    borderSide:  d ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.08)',
    text:        d ? '#e8eaf0' : '#111827',
    textSub:     d ? '#a0aabe' : '#4b5563',
    textMuted:   d ? '#6b7a99' : '#9ca3af',
    textFaint:   d ? '#3d4a63' : '#cbd5e1',
    inputBg:     d ? '#161c27' : '#ffffff',
    inputBorder: d ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.15)',
    accent:      '#c41e3a',
    accentHover: '#a01830',
    navActive:   d ? 'rgba(196,30,58,0.10)' : 'rgba(196,30,58,0.07)',
    shadow:      d ? 'none' : '0 1px 4px rgba(0,0,0,0.08)',
    theadBorder: d ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.07)',
    rowBorder:   d ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.05)',
  }
}
