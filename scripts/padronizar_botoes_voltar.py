#!/usr/bin/env python3
"""
Script para padronizar botões "Voltar" em todos os templates.
Verifica e padroniza o tamanho, design e URLs de retorno.
"""

import os
import re
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
COMPONENTE_VOLTAR = "{% include 'components/botao_voltar.html' %}"

# Padrões para encontrar botões voltar
PADROES_VOLTAR = [
    r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>.*?arrow-left.*?Voltar',
    r'btn.*voltar.*?Voltar',
    r'Voltar.*?arrow-left',
]

# Padrão padrão esperado
PADRAO_ESPERADO = r'{%\s*set\s+back_url\s*=\s*back_url\s+or\s+get_back_url_default\(\)\s*%}\s*{%\s*include\s+[\'"]components/botao_voltar\.html[\'"]\s*%}'

def encontrar_botoes_voltar(conteudo):
    """Encontra botões voltar no conteúdo."""
    botoes = []
    
    # Buscar por links com "Voltar"
    padrao_link = r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>.*?(?:arrow-left|Voltar)'
    matches = re.finditer(padrao_link, conteudo, re.IGNORECASE | re.DOTALL)
    for match in matches:
        botoes.append({
            'tipo': 'link',
            'match': match.group(0),
            'pos': match.start()
        })
    
    return botoes

def verificar_template(caminho):
    """Verifica um template e retorna informações sobre botões voltar."""
    try:
        with open(caminho, 'r', encoding='utf-8') as f:
            conteudo = f.read()
    except Exception as e:
        return {'erro': str(e)}
    
    botoes = encontrar_botoes_voltar(conteudo)
    tem_componente = 'components/botao_voltar.html' in conteudo
    tem_back_url = 'back_url' in conteudo
    
    return {
        'arquivo': str(caminho.relative_to(TEMPLATES_DIR)),
        'tem_botao_voltar': len(botoes) > 0,
        'tem_componente': tem_componente,
        'tem_back_url': tem_back_url,
        'num_botoes': len(botoes),
        'botoes': botoes
    }

def main():
    """Função principal."""
    resultados = []
    
    # Ignorar arquivos específicos
    ignorar = ['base.html', 'login.html', 'components']
    
    for arquivo in TEMPLATES_DIR.rglob('*.html'):
        # Ignorar arquivos na lista
        if any(ign in str(arquivo) for ign in ignorar):
            continue
        
        resultado = verificar_template(arquivo)
        resultados.append(resultado)
    
    # Relatório
    print("=" * 80)
    print("RELATÓRIO DE BOTÕES VOLTAR")
    print("=" * 80)
    print()
    
    sem_botao = [r for r in resultados if not r.get('tem_botao_voltar') and 'erro' not in r]
    com_botao = [r for r in resultados if r.get('tem_botao_voltar') and 'erro' not in r]
    com_componente = [r for r in resultados if r.get('tem_componente') and 'erro' not in r]
    
    print(f"Total de templates verificados: {len(resultados)}")
    print(f"Templates COM botão voltar: {len(com_botao)}")
    print(f"Templates SEM botão voltar: {len(sem_botao)}")
    print(f"Templates usando componente padrão: {len(com_componente)}")
    print()
    
    if sem_botao:
        print("TEMPLATES SEM BOTÃO VOLTAR:")
        print("-" * 80)
        for r in sem_botao[:20]:  # Mostrar apenas os primeiros 20
            print(f"  - {r['arquivo']}")
        if len(sem_botao) > 20:
            print(f"  ... e mais {len(sem_botao) - 20} arquivos")
        print()
    
    print("TEMPLATES COM BOTÃO VOLTAR (mas sem componente padrão):")
    print("-" * 80)
    sem_componente = [r for r in com_botao if not r.get('tem_componente')]
    for r in sem_componente[:20]:
        print(f"  - {r['arquivo']} ({r['num_botoes']} botão(ões))")
    if len(sem_componente) > 20:
        print(f"  ... e mais {len(sem_componente) - 20} arquivos")
    print()

if __name__ == '__main__':
    main()
