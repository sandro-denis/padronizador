# -*- coding: utf-8 -*-
"""Expansao de sigla/iniciais usando os nomes do proprio documento.

Portado de buscarNomePorSiglaV2 (limpezanomes2.gs). A ideia central: so
expande pra um nome que EXISTE na mesma planilha. E o oposto do que o
`subset_initial` fazia - casar "X Y Z" com qualquer nome longo parecido
(ele sugeria "DELEGADO DA RECEITA FEDERAL DO BRASIL..." a 92%).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matching import expandir_sigla


POOL = [
    "MARIA APARECIDA RODRIGUES FONTES",
    "CELIA MARIA DE MONÇÃO PACHECO",
    "BANCO BRADESCO FINANCIAMENTOS S/A",
    "HELENA MARTINS PACHECO DA COSTA",
]


def test_expande_pelas_iniciais_de_todas_as_palavras():
    assert expandir_sigla("MARF", POOL) == "MARIA APARECIDA RODRIGUES FONTES"


def test_expande_ignorando_particulas():
    # CELIA MARIA (de) MONÇÃO PACHECO -> CMMP
    assert expandir_sigla("CMMP", POOL) == "CELIA MARIA DE MONÇÃO PACHECO"


def test_aceita_iniciais_separadas_por_espaco_ou_ponto():
    assert expandir_sigla("M A R F", POOL) == "MARIA APARECIDA RODRIGUES FONTES"
    assert expandir_sigla("M.A.R.F.", POOL) == "MARIA APARECIDA RODRIGUES FONTES"


def test_ignora_sufixo_societario():
    # BANCO BRADESCO FINANCIAMENTOS (S/A ignorado) -> BBF
    assert expandir_sigla("BBF", POOL) == "BANCO BRADESCO FINANCIAMENTOS S/A"


def test_sem_correspondencia_devolve_original():
    """O caso que gerou o bug: iniciais de menor que NAO existem no documento.
    Tem que voltar intacto, nunca chutar um nome longo qualquer."""
    assert expandir_sigla("X Y Z", POOL) == "X Y Z"
    assert expandir_sigla("P Q R S", POOL) == "P Q R S"
    assert expandir_sigla("T U V W", POOL) == "T U V W"


def test_nao_mexe_em_nome_completo():
    assert expandir_sigla("HELENA MARTINS PACHECO DA COSTA", POOL) == \
        "HELENA MARTINS PACHECO DA COSTA"


def test_ambiguo_nao_expande():
    """Se duas pessoas do documento tem as mesmas iniciais, expandir seria
    chute - devolve o original."""
    pool = ["JOAO PEREIRA SILVA", "JOSE PAULO SANTOS"]
    assert expandir_sigla("JPS", pool) == "JPS"


def test_vazio():
    assert expandir_sigla("", POOL) == ""
    assert expandir_sigla(None, POOL) == ""
    assert expandir_sigla("AB", []) == "AB"


def test_duas_iniciais_nao_expandem():
    """Duas letras nao bastam: num acervo grande, um unico nome que bate e
    coincidencia. E boa parte desses valores sao menores com nome mascarado."""
    pool = ["NEUSA AMARAL", "FORTPEL EMBALAGENS LTDA"]
    assert expandir_sigla("N A", pool) == "N A"
    assert expandir_sigla("F E", pool) == "F E"


def test_tres_iniciais_ainda_expandem():
    assert expandir_sigla("S D A L", ["SERGIO DE ARAUJO LOPES"]) == "SERGIO DE ARAUJO LOPES"
