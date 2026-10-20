# -*- coding: utf-8 -*-
"""Deteccao de tribunal/vara/juiz.

Casos tirados de uma planilha real, padronizada em
09/09/2026. A regra antiga disparava com UMA palavra-chave e por isso marcou
uma procuradora federal como se fosse vara - o nome dela so tem "VARA" porque
o Escavador cola o sufixo "PRF VARA PREV" no fim.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from matching import classify_court_or_judge


# Orgaos de verdade - tem que sair da planilha
TRIBUNAIS = [
    "JUÍZO FEDERAL DA 2ª VF DE DUQUE DE CAXIAS",
    "JUÍZO",
    "JUÍZO DE DIREITO DA 4 VARA CÍVEL DA COMARCA DE DUQUE DE CAXIAS",
    "1A VARA FEDERAL DE DUQUE DE CAXIAS RJ",
    "CARTORIO DE REGISTRO DE PESSOAS NATURAIS DA COMARCA DA INHAUMA",
    "12º JUIZADO ESPECIAL CIVEL MÉIER",
    "3ª VARA DE ÓRFÃOS E SUCESSÕES DA COMARCA DA CAPITAL/RJ",
    "6 VARA DE ORFAOS E SUCESSOES",
    "7ª VARA EMPRESARIAL DA COMARCA DO RIO DE JANEIRO",
    "JUÍZO DA 3A VARA DO TRABALHO DE NOVA IGUAÇU RJ",
    "SUBSECAO JUDICIARIA DE SAO PAULO/SP 8 VARA FEDERAL PREVIDENCIARIA",
    "JUIZO FEDERAL DISTRIBUIDOR DE SUBSECAO JUDICIARIA JUAZEIRO DO NORTE SJCE",
    "DES FEDERAL RELATOR A DA 2A TURMA ESPECIALIZADA DO TRIBUNAL REGIONAL FEDERAL DA 2 REGIAO",
    "TRIBUNAL DE JUSTIÇA DO DISTRITO FEDERAL E DOS TERRITÓRIOS",
]

# Pessoas e empresas de verdade - NAO podem ser removidas
PESSOAS = [
    # procuradores federais: o sufixo "PRF ..." e lixo colado pelo Escavador.
    # "VARA" aparece uma vez so, e nao basta pra condenar o nome.
    "BEATRIZ HELENA MOREIRA VILANOVA PEREIRA PRF VARA PREV",
    "BEATRIZ HELENA MOREIRA VILANOVA PEREIRA PRF TRF NMA NAP",
    "RICARDO VALÉRIO DE ANDRADE PRF 1 2 PREV",
    "OSVALDO BRANDINI CASTELO PRF TRF EXEC FISCAL",
    "HELENA MARTINS PACHECO DA COSTA",
    "MARIA DE LOURDES DA ANUNCIACAO",
    # "FAZENDA" sozinho e parte de verdade (Uniao), nao orgao julgador
    "FAZENDA NACIONAL",
    # MINISTERIO PUBLICO e parte no processo, nao vara - segue fora da regra
    "MINISTÉRIO PÚBLICO FEDERAL",
    "BANCO BRADESCO FINANCIAMENTOS S/A",
    "CASA BAHIA COMERCIAL LTDA",
    # bug real (uma planilha real, 10/09/2026): "REGIONAL" + "FEDERAL" batiam as
    # duas palavras fracas sem nenhuma ser especifica de Judiciario - o SENAI
    # nao e vara nem tribunal, e um orgao de ensino profissionalizante.
    "SERVICO NACIONAL DE APRENDIZAGEM INDUSTRIAL DEPARTAMENTO REGIONAL DO DISTRITO FEDERAL",
    "SERVIÇO NACIONAL DE APRENDIZAGEM INDUSTRIAL DEPARTAMENTO REGIONAL DO DISTRITO FEDERAL",
]

JUIZES = [
    "JUIZ DA 11 VARA FEDERAL DO RIO DE JANEIRO SJRJ",
    "JUIZ FEDERAL DA 32 VARA DA SECAO JUDICIARIA DO RIO DE JANEIRO",
]


@pytest.mark.parametrize("texto", TRIBUNAIS)
def test_reconhece_orgao(texto):
    assert classify_court_or_judge(texto) is not None, (
        f"deveria ser reconhecido como orgao: {texto!r}"
    )


@pytest.mark.parametrize("texto", PESSOAS)
def test_nao_confunde_pessoa_com_orgao(texto):
    assert classify_court_or_judge(texto) is None, (
        f"nome de verdade marcado como orgao: {texto!r}"
    )


@pytest.mark.parametrize("texto", JUIZES)
def test_reconhece_juiz(texto):
    assert classify_court_or_judge(texto) == "juiz", (
        f"deveria ser reconhecido como juiz: {texto!r}"
    )


def test_justica_publica_continua_institucional():
    assert classify_court_or_judge("JUSTIÇA PÚBLICA") == "institucional"
    assert classify_court_or_judge("JUÍZO DA JUSTIÇA PÚBLICA") is not None


def test_vazio():
    assert classify_court_or_judge("") is None
    assert classify_court_or_judge(None) is None
