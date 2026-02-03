#!/usr/bin/env python3
"""
Script para substituir TODOS os botões voltar existentes pelo componente padrão.
"""

import re
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
COMPONENTE = """{% set back_url = back_url or get_back_url_default() %}
{% include 'components/botao_voltar.html' %}"""

def substituir_botoes_voltar(conteudo):
    """Substitui qualquer botão voltar pelo componente padrão."""
    # Padrão muito abrangente para capturar qualquer botão voltar
    # Procura por links com "Voltar" e ícone de seta
    padroes = [
        # Padrão 1: Link com back_url ou voltar_url
        (r'<a\s+[^>]*href=["\']{{[^}]*?(?:back_url|voltar_url)[^}]*}}["\'][^>]*>.*?(?:arrow-left|chevron-left|arrow-left-circle)[^<]*Voltar[^<]*</a>', COMPONENTE),
        # Padrão 2: Qualquer link com classe btn e texto Voltar
        (r'<a\s+[^>]*href=["\']{{[^}]*}}["\'][^>]*class=["\'][^"\']*btn[^"\']*["\'][^>]*>.*?Voltar[^<]*</a>', COMPONENTE),
        # Padrão 3: Link com Voltar e arrow-left em qualquer ordem
        (r'<a\s+[^>]*href=["\']{{[^}]*}}["\'][^>]*>.*?(?:arrow-left|chevron-left)[^<]*Voltar[^<]*</a>', COMPONENTE),
        (r'<a\s+[^>]*href=["\']{{[^}]*}}["\'][^>]*>.*?Voltar[^<]*(?:arrow-left|chevron-left)[^<]*</a>', COMPONENTE),
    ]
    
    novo_conteudo = conteudo
    for padrao, substituicao in padroes:
        novo_conteudo = re.sub(padrao, substituicao, novo_conteudo, flags=re.IGNORECASE | re.DOTALL)
    
    return novo_conteudo

def processar_arquivo(caminho):
    """Processa um arquivo."""
    try:
        with open(caminho, 'r', encoding='utf-8') as f:
            conteudo = f.read()
    except Exception as e:
        return {'erro': str(e)}
    
    # Ignorar se já usa componente
    if 'components/botao_voltar.html' in conteudo:
        return {'arquivo': str(caminho.relative_to(TEMPLATES_DIR)), 'modificado': False}
    
    conteudo_original = conteudo
    conteudo = substituir_botoes_voltar(conteudo)
    
    modificado = conteudo != conteudo_original
    
    if modificado:
        try:
            with open(caminho, 'w', encoding='utf-8') as f:
                f.write(conteudo)
        except Exception as e:
            return {'erro': f'Erro ao salvar: {e}'}
    
    return {
        'arquivo': str(caminho.relative_to(TEMPLATES_DIR)),
        'modificado': modificado
    }

def main():
    """Função principal."""
    modificados = []
    
    for arquivo in TEMPLATES_DIR.rglob('*.html'):
        if 'components' in str(arquivo) or 'base.html' in str(arquivo) or 'login.html' in str(arquivo):
            continue
        
        resultado = processar_arquivo(arquivo)
        if resultado.get('modificado'):
            modificados.append(resultado)
    
    print(f"Templates modificados: {len(modificados)}")
    for r in modificados:
        print(f"  ✓ {r['arquivo']}")

if __name__ == '__main__':
    main()
