#!/usr/bin/env python3
"""
Script melhorado para padronizar TODOS os botões voltar.
Substitui botões existentes e adiciona onde falta.
"""

import re
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

# Templates que NÃO devem ter botão voltar
SEM_BOTAO_VOLTAR = [
    'base.html', 'login.html', 'index.html', 'dashboard.html', 'turma.html',
    'painel/painel_federacao.html', 'painel/painel_associacao.html',
    'painel/painel_academia.html', 'painel/painel_aluno.html',
    'painel/gerenciamento_federacao.html', 'painel/gerenciamento_associacao.html',
    'painel/gerenciamento_admin.html', 'painel/academia_dash.html',
    'painel/escolher_modo.html', 'painel/sem_aluno_vinculado.html',
    'painel/painel_sistema.html', 'painel/painel_professor.html',
    'painel/professor_sem_vinculo.html', 'painel_aluno/meu_perfil.html',
    'painel_responsavel/meu_perfil.html', 'painel_responsavel/selecionar_aluno.html',
]

COMPONENTE_VOLTAR = """{% set back_url = back_url or get_back_url_default() %}
{% include 'components/botao_voltar.html' %}"""

def deve_ter_botao(caminho_relativo):
    """Verifica se deve ter botão voltar."""
    caminho_str = str(caminho_relativo)
    return not any(sem in caminho_str for sem in SEM_BOTAO_VOLTAR)

def substituir_botoes_existentes(conteudo):
    """Substitui botões voltar existentes pelo componente."""
    # Padrão mais abrangente para encontrar botões voltar
    padrao = r'<a\s+[^>]*href=["\']{{[^}]*?(?:back_url|voltar_url)[^}]*}}["\'][^>]*class=["\'][^"\']*btn[^"\']*(?:outline-)?(?:secondary|dark)[^"\']*["\'][^>]*>.*?(?:arrow-left|chevron-left)[^<]*Voltar[^<]*</a>'
    
    # Substituir todos os matches
    novo_conteudo = re.sub(padrao, COMPONENTE_VOLTAR, conteudo, flags=re.IGNORECASE | re.DOTALL)
    
    # Também substituir variações com btn-sm, btn-lg, etc
    padrao2 = r'<a\s+[^>]*href=["\']{{[^}]*?(?:back_url|voltar_url)[^}]*}}["\'][^>]*class=["\'][^"\']*btn[^"\']*["\'][^>]*>.*?Voltar[^<]*</a>'
    novo_conteudo = re.sub(padrao2, COMPONENTE_VOLTAR, novo_conteudo, flags=re.IGNORECASE | re.DOTALL)
    
    return novo_conteudo

def adicionar_botao_voltar(conteudo, caminho_relativo):
    """Adiciona botão voltar se necessário."""
    # Se já tem componente, não adicionar
    if 'components/botao_voltar.html' in conteudo:
        return conteudo
    
    # Se já tem algum botão voltar, não adicionar
    if re.search(r'(?:arrow-left|chevron-left).*?Voltar|Voltar.*?(?:arrow-left|chevron-left)', conteudo, re.IGNORECASE):
        return conteudo
    
    # Determinar onde adicionar
    # Opção 1: Após título h2/h3/h4 no início do content
    padrao_titulo = r'(<h[2-4][^>]*>.*?</h[2-4]>)'
    match = re.search(padrao_titulo, conteudo)
    if match:
        pos = match.end()
        # Verificar se já tem botão próximo
        proximo = conteudo[pos:pos+200]
        if 'Voltar' not in proximo and 'btn' not in proximo:
            conteudo = conteudo[:pos] + f'\n    <div class="mb-3">\n        {COMPONENTE_VOLTAR}\n    </div>' + conteudo[pos:]
            return conteudo
    
    # Opção 2: No início do container
    if '<div class="container' in conteudo:
        padrao_container = r'(<div class="container[^>]*>\s*\n)'
        match = re.search(padrao_container, conteudo)
        if match:
            pos = match.end()
            conteudo = conteudo[:pos] + f'    {COMPONENTE_VOLTAR}\n' + conteudo[pos:]
            return conteudo
    
    return conteudo

def processar_arquivo(caminho):
    """Processa um arquivo."""
    try:
        with open(caminho, 'r', encoding='utf-8') as f:
            conteudo = f.read()
    except Exception as e:
        return {'erro': str(e)}
    
    caminho_relativo = caminho.relative_to(TEMPLATES_DIR)
    conteudo_original = conteudo
    
    # Substituir botões existentes
    conteudo = substituir_botoes_existentes(conteudo)
    
    # Adicionar se necessário
    if deve_ter_botao(caminho_relativo):
        conteudo = adicionar_botao_voltar(conteudo, caminho_relativo)
    
    modificado = conteudo != conteudo_original
    
    if modificado:
        try:
            with open(caminho, 'w', encoding='utf-8') as f:
                f.write(conteudo)
        except Exception as e:
            return {'erro': f'Erro ao salvar: {e}'}
    
    return {
        'arquivo': str(caminho_relativo),
        'modificado': modificado
    }

def main():
    """Função principal."""
    resultados = []
    
    for arquivo in TEMPLATES_DIR.rglob('*.html'):
        if 'components' in str(arquivo) or 'base.html' in str(arquivo) or 'login.html' in str(arquivo):
            continue
        
        resultado = processar_arquivo(arquivo)
        if resultado.get('modificado'):
            resultados.append(resultado)
    
    print(f"Templates modificados: {len(resultados)}")
    for r in resultados[:50]:
        print(f"  ✓ {r['arquivo']}")
    if len(resultados) > 50:
        print(f"  ... e mais {len(resultados) - 50} arquivos")

if __name__ == '__main__':
    main()
