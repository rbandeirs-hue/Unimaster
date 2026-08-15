export type Faixa = 'Branca' | 'Amarela' | 'Laranja' | 'Verde' | 'Azul' | 'Marrom' | 'Preta'
export type Status = 'Pago' | 'Pendente' | 'Atrasado' | 'Isento'
export type TipoDesconto = 'Percentual' | 'Fixo'
export type StatusCobranca = 'Gerada' | 'Enviada' | 'Paga' | 'Cancelada'

export interface Aluno {
  id: number
  nome: string
  email: string
  telefone: string
  faixa: Faixa
  mensalidade: number
  ativo: boolean
  ingresso: string
}

export interface Pagamento {
  id: number
  alunoId: number
  mes: string
  valor: number
  status: Status
  dataPagamento?: string
  formaPagamento?: string
  vencimento: string
}

export interface PlanoMensalidade {
  id: number
  nome: string
  descricao: string
  valor: number
  faixas: Faixa[]
  diaVencimento: number
  ativo: boolean
  criadoEm: string
}

export interface Desconto {
  id: number
  nome: string
  tipo: TipoDesconto
  valor: number
  motivo: string
  alunoId?: number
  planoId?: number
  validade?: string
  ativo: boolean
  criadoEm: string
}

export interface Cobranca {
  id: number
  alunoId: number
  mes: string
  valorOriginal: number
  descontoId?: number
  valorFinal: number
  status: StatusCobranca
  geradaEm: string
  enviadaEm?: string
  observacao?: string
}

export const alunos: Aluno[] = [
  { id: 1, nome: 'Carlos Mendes', email: 'carlos@email.com', telefone: '(11) 98765-0001', faixa: 'Preta', mensalidade: 180, ativo: true, ingresso: '2019-03-10' },
  { id: 2, nome: 'Ana Beatriz Lima', email: 'ana@email.com', telefone: '(11) 98765-0002', faixa: 'Marrom', mensalidade: 150, ativo: true, ingresso: '2021-06-15' },
  { id: 3, nome: 'Rafael Torres', email: 'rafael@email.com', telefone: '(11) 98765-0003', faixa: 'Azul', mensalidade: 130, ativo: true, ingresso: '2022-01-20' },
  { id: 4, nome: 'Juliana Costa', email: 'juliana@email.com', telefone: '(11) 98765-0004', faixa: 'Verde', mensalidade: 120, ativo: true, ingresso: '2023-04-01' },
  { id: 5, nome: 'Thiago Alves', email: 'thiago@email.com', telefone: '(11) 98765-0005', faixa: 'Verde', mensalidade: 120, ativo: true, ingresso: '2023-05-10' },
  { id: 6, nome: 'Fernanda Rocha', email: 'fernanda@email.com', telefone: '(11) 98765-0006', faixa: 'Laranja', mensalidade: 110, ativo: true, ingresso: '2024-02-14' },
  { id: 7, nome: 'Lucas Sousa', email: 'lucas@email.com', telefone: '(11) 98765-0007', faixa: 'Amarela', mensalidade: 100, ativo: true, ingresso: '2024-08-22' },
  { id: 8, nome: 'Mariana Vieira', email: 'mariana@email.com', telefone: '(11) 98765-0008', faixa: 'Branca', mensalidade: 90, ativo: true, ingresso: '2025-01-10' },
  { id: 9, nome: 'Pedro Nunes', email: 'pedro@email.com', telefone: '(11) 98765-0009', faixa: 'Branca', mensalidade: 90, ativo: true, ingresso: '2025-03-05' },
  { id: 10, nome: 'Sofia Martins', email: 'sofia@email.com', telefone: '(11) 98765-0010', faixa: 'Amarela', mensalidade: 100, ativo: false, ingresso: '2023-09-18' },
]

export const pagamentos: Pagamento[] = [
  { id: 1, alunoId: 1, mes: '2026-07', valor: 180, status: 'Pago', dataPagamento: '2026-07-05', formaPagamento: 'PIX', vencimento: '2026-07-10' },
  { id: 2, alunoId: 2, mes: '2026-07', valor: 150, status: 'Pago', dataPagamento: '2026-07-08', formaPagamento: 'Cartão', vencimento: '2026-07-10' },
  { id: 3, alunoId: 3, mes: '2026-07', valor: 130, status: 'Pago', dataPagamento: '2026-07-10', formaPagamento: 'PIX', vencimento: '2026-07-10' },
  { id: 4, alunoId: 4, mes: '2026-07', valor: 120, status: 'Pago', dataPagamento: '2026-07-12', formaPagamento: 'Boleto', vencimento: '2026-07-10' },
  { id: 5, alunoId: 5, mes: '2026-07', valor: 120, status: 'Pago', dataPagamento: '2026-07-09', formaPagamento: 'PIX', vencimento: '2026-07-10' },
  { id: 6, alunoId: 6, mes: '2026-07', valor: 110, status: 'Atrasado', vencimento: '2026-07-10' },
  { id: 7, alunoId: 7, mes: '2026-07', valor: 100, status: 'Pago', dataPagamento: '2026-07-07', formaPagamento: 'PIX', vencimento: '2026-07-10' },
  { id: 8, alunoId: 8, mes: '2026-07', valor: 90, status: 'Pago', dataPagamento: '2026-07-11', formaPagamento: 'Cartão', vencimento: '2026-07-10' },
  { id: 9, alunoId: 9, mes: '2026-07', valor: 90, status: 'Isento', vencimento: '2026-07-10' },
  { id: 10, alunoId: 1, mes: '2026-08', valor: 180, status: 'Pago', dataPagamento: '2026-08-04', formaPagamento: 'PIX', vencimento: '2026-08-10' },
  { id: 11, alunoId: 2, mes: '2026-08', valor: 150, status: 'Pago', dataPagamento: '2026-08-07', formaPagamento: 'Cartão', vencimento: '2026-08-10' },
  { id: 12, alunoId: 3, mes: '2026-08', valor: 130, status: 'Pendente', vencimento: '2026-08-10' },
  { id: 13, alunoId: 4, mes: '2026-08', valor: 120, status: 'Pendente', vencimento: '2026-08-10' },
  { id: 14, alunoId: 5, mes: '2026-08', valor: 120, status: 'Pago', dataPagamento: '2026-08-06', formaPagamento: 'PIX', vencimento: '2026-08-10' },
  { id: 15, alunoId: 6, mes: '2026-08', valor: 110, status: 'Atrasado', vencimento: '2026-08-10' },
  { id: 16, alunoId: 7, mes: '2026-08', valor: 100, status: 'Pendente', vencimento: '2026-08-10' },
  { id: 17, alunoId: 8, mes: '2026-08', valor: 90, status: 'Pendente', vencimento: '2026-08-10' },
  { id: 18, alunoId: 9, mes: '2026-08', valor: 90, status: 'Isento', vencimento: '2026-08-10' },
]

export const planosMensalidade: PlanoMensalidade[] = [
  { id: 1, nome: 'Plano Iniciante', descricao: 'Para alunos de faixa branca e amarela', valor: 95, faixas: ['Branca', 'Amarela'], diaVencimento: 10, ativo: true, criadoEm: '2024-01-01' },
  { id: 2, nome: 'Plano Intermediário', descricao: 'Para alunos de faixa laranja, verde e azul', valor: 125, faixas: ['Laranja', 'Verde', 'Azul'], diaVencimento: 10, ativo: true, criadoEm: '2024-01-01' },
  { id: 3, nome: 'Plano Avançado', descricao: 'Para alunos de faixa marrom e preta', valor: 165, faixas: ['Marrom', 'Preta'], diaVencimento: 10, ativo: true, criadoEm: '2024-01-01' },
  { id: 4, nome: 'Plano Família', descricao: 'Para famílias com 2 ou mais membros', valor: 80, faixas: ['Branca', 'Amarela', 'Laranja', 'Verde', 'Azul', 'Marrom', 'Preta'], diaVencimento: 10, ativo: false, criadoEm: '2024-06-01' },
]

export const descontos: Desconto[] = [
  { id: 1, nome: 'Desconto Irmão', tipo: 'Percentual', valor: 15, motivo: 'Família com mais de um aluno', ativo: true, criadoEm: '2024-01-01' },
  { id: 2, nome: 'Bolsa Social', tipo: 'Percentual', valor: 100, motivo: 'Aluno em situação de vulnerabilidade social', ativo: true, criadoEm: '2024-01-01' },
  { id: 3, nome: 'Desconto Professor', tipo: 'Percentual', valor: 50, motivo: 'Professor ou instrutor da academia', ativo: true, criadoEm: '2024-03-01' },
  { id: 4, nome: 'Desconto Anual', tipo: 'Fixo', valor: 20, motivo: 'Pagamento antecipado anual', validade: '2026-12-31', ativo: true, criadoEm: '2026-01-01' },
  { id: 5, nome: 'Desconto Inauguração', tipo: 'Fixo', valor: 30, motivo: 'Alunos fundadores da academia', validade: '2026-06-30', ativo: false, criadoEm: '2023-01-01' },
]

export const cobrancas: Cobranca[] = [
  { id: 1, alunoId: 3, mes: '2026-08', valorOriginal: 130, valorFinal: 130, status: 'Gerada', geradaEm: '2026-08-01' },
  { id: 2, alunoId: 4, mes: '2026-08', valorOriginal: 120, valorFinal: 120, status: 'Enviada', geradaEm: '2026-08-01', enviadaEm: '2026-08-02' },
  { id: 3, alunoId: 7, mes: '2026-08', valorOriginal: 100, valorFinal: 85, descontoId: 1, status: 'Enviada', geradaEm: '2026-08-01', enviadaEm: '2026-08-02', observacao: 'Desconto irmão aplicado' },
  { id: 4, alunoId: 8, mes: '2026-08', valorOriginal: 90, valorFinal: 90, status: 'Gerada', geradaEm: '2026-08-01' },
]

export const FAIXA_COLOR: Record<Faixa, string> = {
  Branca: '#e8eaf0',
  Amarela: '#f5c518',
  Laranja: '#f97316',
  Verde: '#22c55e',
  Azul: '#3b82f6',
  Marrom: '#92400e',
  Preta: '#444',
}

export const STATUS_COLOR: Record<Status, { bg: string; text: string }> = {
  Pago: { bg: 'rgba(34,197,94,0.12)', text: '#22c55e' },
  Pendente: { bg: 'rgba(245,197,24,0.12)', text: '#d4a800' },
  Atrasado: { bg: 'rgba(196,30,58,0.15)', text: '#c41e3a' },
  Isento: { bg: 'rgba(107,122,153,0.12)', text: '#6b7a99' },
}

export const COBRANCA_COLOR: Record<StatusCobranca, { bg: string; text: string }> = {
  Gerada: { bg: 'rgba(59,130,246,0.12)', text: '#3b82f6' },
  Enviada: { bg: 'rgba(245,197,24,0.12)', text: '#d4a800' },
  Paga: { bg: 'rgba(34,197,94,0.12)', text: '#22c55e' },
  Cancelada: { bg: 'rgba(107,122,153,0.12)', text: '#6b7a99' },
}

export const TODAS_FAIXAS: Faixa[] = ['Branca', 'Amarela', 'Laranja', 'Verde', 'Azul', 'Marrom', 'Preta']

export function nomeAluno(id: number) {
  return alunos.find(a => a.id === id)?.nome ?? '—'
}

export function fmtMoeda(v: number) {
  return v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

export function fmtMes(mes: string) {
  const [y, m] = mes.split('-')
  const meses = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
  return `${meses[parseInt(m) - 1]} ${y}`
}
