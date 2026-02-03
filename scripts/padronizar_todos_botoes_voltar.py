#!/usr/bin/env python3
"""
Script para padronizar TODOS os botões voltar em todos os templates.
Substitui botões existentes pelo componente padrão e adiciona onde falta.
"""

import os
import re
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
COMPONENTE_VOLTAR = """{% set back_url = back_url or get_back_url_default() %}
{% include 'components/botao_voltar.html' %}"""

# Templates que NÃO devem ter botão voltar (painéis principais)
SEM_BOTAO_VOLTAR = [
    'base.html',
    'login.html',
    'index.html',
    'dashboard.html',
    'turma.html',
    'painel/painel_federacao.html',
    'painel/painel_associacao.html',
    'painel/painel_academia.html',
    'painel/painel_aluno.html',
    'painel/gerenciamento_federacao.html',
    'painel/gerenciamento_associacao.html',
    'painel/gerenciamento_admin.html',
    'painel/academia_dash.html',
    'painel/escolher_modo.html',
    'painel/sem_aluno_vinculado.html',
    'painel/painel_sistema.html',
    'painel/painel_professor.html',
    'painel/professor_sem_vinculo.html',
    'painel_aluno/meu_perfil.html',
    'painel_responsavel/meu_perfil.html',
    'painel_responsavel/selecionar_aluno.html',
]

# Padrões de botão voltar para substituir
PADROES_BOTAO_VOLTAR = [
    # Padrão 1: <a href="{{ back_url }}" class="btn btn-outline-secondary...">...Voltar
    (r'<a\s+href=["\']{{.*?back_url.*?}}["\'][^>]*class=["\'][^"\']*btn[^"\']*outline-secondary[^"\']*["\'][^>]*>.*?arrow-left.*?Voltar.*?</a>', COMPONENTE_VOLTAR),
    # Padrão 2: <a href="{{ back_url }}" class="btn btn-secondary...">...Voltar
    (r'<a\s+href=["\']{{.*?back_url.*?}}["\'][^>]*class=["\'][^"\']*btn[^"\']*secondary[^"\']*["\'][^>]*>.*?arrow-left.*?Voltar.*?</a>', COMPONENTE_VOLTAR),
    # Padrão 3: voltar_url|default
    (r'<a\s+href=["\']{{.*?voltar_url.*?}}["\'][^>]*class=["\'][^"\']*btn[^"\']*outline-secondary[^"\']*["\'][^>]*>.*?arrow-left.*?Voltar.*?</a>', COMPONENTE_VOLTAR),
]

def deve_ter_botao_voltar(caminho_relativo):
    """Verifica se o template deve ter botão voltar."""
    caminho_str = str(caminho_relativo)
    return not any(sem in caminho_str for sem in SEM_BOTAO_VOLTAR)

def substituir_botao_voltar(conteudo):
    """Substitui botões voltar existentes pelo componente padrão."""
    novo_conteudo = conteudo
    
    # Remover botões voltar existentes (vários padrões)
    padroes_remover = [
        r'<a\s+href=["\']{{[^}]*back_url[^}]*}}["\'][^>]*class=["\'][^"\']*btn[^"\']*(?:outline-)?secondary[^"\']*["\'][^>]*>.*?arrow-left[^<]*Voltar[^<]*</a>',
        r'<a\s+href=["\']{{[^}]*voltar_url[^}]*}}["\'][^>]*class=["\'][^"\']*btn[^"\']*(?:outline-)?secondary[^"\']*["\'][^>]*>.*?arrow-left[^<]*Voltar[^<]*</a>',
    ]
    
    for padrao in padroes_remover:
        novo_conteudo = re.sub(padrao, '', novo_conteudo, flags=re.IGNORECASE | re.DOTALL)
    
    return novo_conteudo

def adicionar_botao_voltar_se_necessario(conteudo, caminho_relativo):
    """Adiciona botão voltar se necessário."""
    if not deve_ter_botao_voltar(caminho_relativo):
        return conteudo
    
    # Verificar se já tem componente
    if 'components/botao_voltar.html' in conteudo:
        return conteudo
    
    # Verificar se já tem algum botão voltar
    if re.search(r'arrow-left.*?Voltar|Voltar.*?arrow-left', conteudo, re.IGNORECASE):
        return conteudo
    
    # Adicionar antes do fechamento do formulário ou no início do content
    # Procurar por formulários primeiro
    if '<form' in conteudo and '</form>' in conteudo:
        # Adicionar antes do fechamento do form
        padrao_form = r'(</form>)'
        substituicao = f'        {COMPONENTE_VOLTAR}\n    \\1'
        conteudo = re.sub(padrao_form, substituicao, conteudo, count=1)
    elif '<div class="container' in conteudo:
        # Adicionar após abertura do container
        padrao_container = r'(<div class="container[^>]*>)'
        substituicao = f'\\1\n    {COMPONENTE_VOLTAR}\n'
        conteudo = re.sub(padrao_container, substituicao, conteudo, count=1)
    
    return conteudo

def processar_template(caminho):
    """Processa um template individual."""
    try:
        with open(caminho, 'r', encoding='utf-8') as f:
            conteudo_original = f.read()
    except Exception as e:
        return {'erro': str(e), 'modificado': False}
    
    conteudo_novo = conteudo_original
    caminho_relativo = caminho.relative_to(TEMPLATES_DIR)
    
    # Substituir botões existentes
    conteudo_novo = substituir_botao_voltar(conteudo_novo)
    
    # Adicionar se necessário
    if deve_ter_botao_voltar(caminho_relativo):
        conteudo_novo = adicionar_botao_voltar_se_necessario(conteudo_novo, caminho_relativo)
    
    modificado = conteudo_novo != conteudo_original
    
    if modificado:
        try:
            with open(caminho, 'w', encoding='utf-8') as f:
                f.write(conteudo_novo)
        except Exception as e:
            return {'erro': f'Erro ao salvar: {e}', 'modificado': False}
    
    return {
        'arquivo': str(caminho_relativo),
        'modificado': modificado,
        'tem_componente': 'components/botao_voltar.html' in conteudo_novo
    }

def main():
    """Função principal."""
    resultados = []
    modificados = []
    erros = []
    
    # Ignorar componentes e base
    ignorar = ['components', 'base.html', 'login.html']
    
    for arquivo in TEMPLATES_DIR.rglob('*.html'):
        if any(ign in str(arquivo) for ign in ignorar):
            continue
        
        resultado = processar_template(arquivo)
        resultados.append(resultado)
        
        if 'erro' in resultado:
            erros.append(resultado)
        elif resultado.get('modificado'):
            modificados.append(resultado)
    
    # Relatório
    print("=" * 80)
    print("PADRONIZAÇÃO DE BOTÕES VOLTAR - RELATÓRIO")
    print("=" * 80)
    print()
    print(f"Total de templates processados: {len(resultados)}")
    print(f"Templates modificados: {len(modificados)}")
    print(f"Erros encontrados: {len(erros)}")
    print()
    
    if modificados:
        print("TEMPLATES MODIFICADOS:")
        print("-" * 80)
        for r in modificados[:30]:
            print(f"  ✓ {r['arquivo']}")
        if len(modificados) > 30:
            print(f"  ... e mais {len(modificados) - 30} arquivos")
        print()
    
    if erros:
        print("ERROS:")
        print("-" * 80)
        for r in erros[:10]:
            print(f"  ✗ {r['arquivo']}: {r['erro']}")
        print()

if __name__ == '__main__':
    main()
