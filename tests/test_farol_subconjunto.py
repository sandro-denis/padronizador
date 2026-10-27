# -*- coding: utf-8 -*-
"""Nome curto ambiguo nao pode servir de ponte entre pessoas diferentes.

Caso real (conta (planilha real), pratica criminal em Uba/MG, 21/10/2026): a planilha
tinha "MARIA DAS DORES" sozinha e mais 16 "MARIA DAS DORES <sobrenomes>".
Nenhuma das 16 casa com qualquer outra das 16 - zero de 120 pares. Mas a forma
curta casa com TODAS por subconjunto/abreviacao, e o union-find fundiu as 17
numa pessoa so.

Esse e o "efeito farol": o nome curto nao e um membro a mais do grupo, e a
unica ponte que liga tudo. O mesmo aconteceu com "L P" (ligando J A C, J B C,
J C M N, J D M C, J F C...), "MINISTERIO PUBLICO" (ligando MP Federal, MP do
Trabalho e MP de MG, que sao orgaos diferentes) e "AUTORIDADE POLICIAL".

A regra: quando um nome casa com 2+ outros que em sua maioria NAO casam entre
si, ele e ambiguo - poderia ser qualquer um deles - e nao se junta a nenhum.
E a mesma disciplina que `expandir_sigla` ja tinha pra sigla ("se duas pessoas
do documento tem as mesmas iniciais, expandir seria chute"); faltava pra
subconjunto.

O que NAO pode ser afetado: uma cadeia de variantes de verdade, em que as
pontas casam entre si ("X LTDA" / "X COMERCIO LTDA" / "X COMERCIO DE ALIMENTOS
LTDA" sao a mesma empresa). E par confirmado a mao ou ancorado em CPF, que sao
autoridade e passam por cima da trava.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from matching import find_clusters, normalize_name


def _occ(texto, row=1, part=0, column="cliente"):
    return {"text": texto, "norm": normalize_name(texto), "source": "escavador",
            "row": row, "column": column, "part_index": part}


def _occs(nomes):
    """Uma ocorrencia por nome, cada uma em sua propria LINHA.

    Linhas diferentes de proposito: na mesma celula o motor relaxa a exigencia
    do ultimo token (ver test_empresa_mesma_celula.py) e isso e outro caminho,
    que nao e o assunto deste arquivo.
    """
    return [_occ(n, row=i + 2) for i, n in enumerate(nomes)]


def _grupo_de(clusters, nome):
    """O conjunto de membros do cluster que contem `nome` (vazio se sozinho)."""
    alvo = normalize_name(nome)
    for c in clusters:
        if alvo in c["members"]:
            return set(c["members"])
    return set()


# ---------- o caso que gerou a regra ----------

GRACAS = [
    "MARIA DAS DORES",
    "MARIA DAS DORES ALVES CARDOSO",
    "MARIA DAS DORES CASTRO MOURA",
    "MARIA DAS DORES DE OLIVEIRA",
    "MARIA DAS DORES GOMES SOARES",
]


def test_nome_curto_ambiguo_nao_funde_pessoas_diferentes():
    clusters = find_clusters(_occs(GRACAS))
    for nome in GRACAS[1:]:
        g = _grupo_de(clusters, nome)
        outros = g - {normalize_name(nome)}
        assert not outros, (
            f"{nome!r} foi agrupado com {sorted(outros)} - sao pessoas diferentes, "
            "ligadas so pela forma curta 'MARIA DAS DORES'"
        )


def test_a_forma_curta_tambem_fica_sozinha():
    """Nao basta soltar as 16: a propria forma curta nao pode ser colada em
    nenhuma delas, porque nao da pra saber em qual."""
    clusters = find_clusters(_occs(GRACAS))
    assert not _grupo_de(clusters, "MARIA DAS DORES")


def test_iniciais_mascaradas_nao_se_fundem():
    """Nome mascarado de processo criminal: "L P" casa por subconjunto com
    varias iniciais diferentes. Fundir seria afirmar identidade de vitima ou
    de reu."""
    clusters = find_clusters(_occs(["L P", "L A P", "L B P", "L P M N", "L F P"]))
    for nome in ("L A P", "L B P", "L P M N", "L F P"):
        g = _grupo_de(clusters, nome)
        assert g - {normalize_name(nome)} == set(), f"{nome!r} nao devia agrupar"


def test_orgaos_publicos_diferentes_nao_se_fundem():
    """MP Federal, MP do Trabalho e MP de Minas Gerais sao orgaos distintos; o
    que os ligava era "MINISTERIO PUBLICO" nu."""
    nomes = ["MINISTERIO PUBLICO", "MINISTERIO PUBLICO FEDERAL",
             "MINISTERIO PUBLICO DO TRABALHO", "MINISTERIO PUBLICO DO ESTADO DE MINAS GERAIS"]
    clusters = find_clusters(_occs(nomes))
    g = _grupo_de(clusters, "MINISTERIO PUBLICO FEDERAL")
    assert normalize_name("MINISTERIO PUBLICO DO TRABALHO") not in g


# ---------- a trava nao pode estragar o que funcionava ----------

def test_cadeia_de_variantes_de_verdade_continua_unida():
    """Aqui as pontas casam ENTRE SI, entao nao ha farol: e a mesma empresa
    escrita com mais ou menos qualificador. Tem que continuar um grupo so."""
    nomes = ["PANIFICADORA AURORA LTDA",
             "PANIFICADORA AURORA COMERCIO LTDA",
             "PANIFICADORA AURORA COMERCIO DE ALIMENTOS LTDA"]
    clusters = find_clusters(_occs(nomes))
    g = _grupo_de(clusters, nomes[0])
    assert len(g) == 3, f"deviam seguir juntas, veio {sorted(g)}"


def test_par_simples_continua_agrupando():
    """Dois nomes, um subconjunto do outro, sem terceiro pra criar ambiguidade:
    nada de farol, agrupa como sempre."""
    clusters = find_clusters(_occs(["JOAO PEREIRA SILVA", "JOAO PEREIRA DA SILVA"]))
    assert len(_grupo_de(clusters, "JOAO PEREIRA SILVA")) == 2


def test_decisao_confirmada_passa_por_cima_da_trava():
    """Se o usuario ja disse que sao a mesma pessoa, a trava nao desfaz."""
    par = frozenset((normalize_name("MARIA DAS DORES"),
                     normalize_name("MARIA DAS DORES DE OLIVEIRA")))
    clusters = find_clusters(_occs(GRACAS), confirmed_pairs={par})
    g = _grupo_de(clusters, "MARIA DAS DORES DE OLIVEIRA")
    assert normalize_name("MARIA DAS DORES") in g


def test_mesmo_cpf_passa_por_cima_da_trava():
    """CPF igual e autoridade: mesmo parecendo farol, junta."""
    cpf_by_norm = {
        normalize_name("MARIA DAS DORES"): {"11111111111"},
        normalize_name("MARIA DAS DORES DE OLIVEIRA"): {"11111111111"},
    }
    clusters = find_clusters(_occs(GRACAS), cpf_by_norm=cpf_by_norm)
    g = _grupo_de(clusters, "MARIA DAS DORES DE OLIVEIRA")
    assert normalize_name("MARIA DAS DORES") in g
