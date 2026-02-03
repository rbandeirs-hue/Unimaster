-- ======================================================
-- Script de Migração: Adicionar campos de endereço nas tabelas academias e associacoes
-- Data: 2026-01-28
-- ======================================================

-- Adicionar campos de endereço na tabela academias
ALTER TABLE academias 
ADD COLUMN IF NOT EXISTS cep VARCHAR(10) NULL DEFAULT NULL COMMENT 'CEP no formato 00000-000' AFTER telefone,
ADD COLUMN IF NOT EXISTS rua VARCHAR(255) NULL DEFAULT NULL COMMENT 'Logradouro/Rua' AFTER cep,
ADD COLUMN IF NOT EXISTS numero VARCHAR(20) NULL DEFAULT NULL COMMENT 'Número do endereço' AFTER rua,
ADD COLUMN IF NOT EXISTS complemento VARCHAR(100) NULL DEFAULT NULL COMMENT 'Complemento' AFTER numero,
ADD COLUMN IF NOT EXISTS bairro VARCHAR(100) NULL DEFAULT NULL COMMENT 'Bairro' AFTER complemento;

-- Adicionar campos de endereço na tabela associacoes
ALTER TABLE associacoes 
ADD COLUMN IF NOT EXISTS cep VARCHAR(10) NULL DEFAULT NULL COMMENT 'CEP no formato 00000-000' AFTER telefone,
ADD COLUMN IF NOT EXISTS rua VARCHAR(255) NULL DEFAULT NULL COMMENT 'Logradouro/Rua' AFTER cep,
ADD COLUMN IF NOT EXISTS numero VARCHAR(20) NULL DEFAULT NULL COMMENT 'Número do endereço' AFTER rua,
ADD COLUMN IF NOT EXISTS complemento VARCHAR(100) NULL DEFAULT NULL COMMENT 'Complemento' AFTER numero,
ADD COLUMN IF NOT EXISTS bairro VARCHAR(100) NULL DEFAULT NULL COMMENT 'Bairro' AFTER complemento,
ADD COLUMN IF NOT EXISTS cidade VARCHAR(100) NULL DEFAULT NULL COMMENT 'Cidade' AFTER bairro,
ADD COLUMN IF NOT EXISTS uf VARCHAR(2) NULL DEFAULT NULL COMMENT 'Estado (UF)' AFTER cidade;

-- Verificar estrutura final
DESCRIBE academias;
DESCRIBE associacoes;
