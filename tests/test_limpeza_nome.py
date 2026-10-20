# -*- coding: utf-8 -*-
"""Limpeza de lixo colado no nome pelo Escavador.

Regras portadas de limpezanomes2.gs (Apps Script "Automações advbox"), mais
o sufixo "PRF ..." observado em uma planilha real em 09/09/2026.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from matching import limpar_nome


CASOS = [
    # (entrada, esperado)
    ("MARIA DA SILVA (REPRESENTANTE LEGAL)", "MARIA DA SILVA"),
    ("REGISTRADO(A) CIVILMENTE COMO JOAO PEREIRA", "JOAO PEREIRA"),
    ("NOME SOCIAL: ANA BEATRIZ COSTA", "ANA BEATRIZ COSTA"),
    ("NOME SOCIAL - ANA BEATRIZ COSTA", "ANA BEATRIZ COSTA"),
    # tudo a partir de "REPRESENTADO POR" e outra pessoa, nao faz parte do nome
    ("CARLOS SOUZA REPRESENTADO POR MARIA SOUZA", "CARLOS SOUZA"),
    ("CARLOS SOUZA ASSISTIDO POR DEFENSORIA PUBLICA", "CARLOS SOUZA"),
    ("JOSE LIMA DADOS DE QUALIFICAÇÃO SIGILOSOS", "JOSE LIMA"),
    # CPF/CNPJ/numero de processo colado no nome
    ("PEDRO ALVES 123.456.789-00", "PEDRO ALVES"),
    ("EMPRESA X LTDA 12.345.678/0001-99", "EMPRESA X LTDA"),
    ("- LUCIA MARTINS", "LUCIA MARTINS"),
    ("ANA   MARIA    SOUZA", "ANA MARIA SOUZA"),
    # sufixo de procurador federal grudado pelo Escavador
    ("BEATRIZ HELENA MOREIRA VILANOVA PEREIRA PRF VARA PREV",
     "BEATRIZ HELENA MOREIRA VILANOVA PEREIRA"),
    ("RICARDO VALÉRIO DE ANDRADE PRF 1 2 PREV", "RICARDO VALÉRIO DE ANDRADE"),
    ("OSVALDO BRANDINI CASTELO PRF TRF EXEC FISCAL", "OSVALDO BRANDINI CASTELO"),
    ("TARCÍSIO MONFORTE LEAL DA ROCHA PRF", "TARCÍSIO MONFORTE LEAL DA ROCHA"),
]


@pytest.mark.parametrize("entrada,esperado", CASOS)
def test_limpa(entrada, esperado):
    assert limpar_nome(entrada) == esperado


NAO_MEXER = [
    # nome limpo continua igual - a limpeza nao pode inventar mudanca
    "HELENA MARTINS PACHECO DA COSTA",
    "BANCO BRADESCO FINANCIAMENTOS S/A",
    "CASA BAHIA COMERCIAL LTDA",
    "MARIA DE LOURDES DA SILVA ANUNCIAÇÃO",
    "AGUAS DO VALE 4 SPE S/A",
    # numero curto faz parte do nome e nao pode sumir
    "7ª VARA EMPRESARIAL DA COMARCA DO RIO DE JANEIRO",
    "AGUAS DO VALE 4",
]


@pytest.mark.parametrize("texto", NAO_MEXER)
def test_nao_altera_nome_ja_limpo(texto):
    assert limpar_nome(texto) == texto


def test_vazio():
    assert limpar_nome("") == ""
    assert limpar_nome(None) == ""


def test_nao_esvazia_nome():
    """Se a limpeza comer o nome inteiro, devolve o original - melhor um nome
    sujo do que uma celula vazia."""
    assert limpar_nome("REPRESENTADO POR FULANO") == "REPRESENTADO POR FULANO"
