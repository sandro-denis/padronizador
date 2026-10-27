# -*- coding: utf-8 -*-
"""Nome feito so de iniciais nao se compara com nada.

Numa pratica criminal a planilha vem cheia de nome mascarado: vitima, menor,
segredo de justica. A conta (planilha real) (21/10/2026) tinha 116 desses em 3.016
processos - "A", "Z A P", "Q K", "L P M N".

Duas sequencias de inicial parecidas nao dizem NADA sobre identidade. E a regra
de erro de digitacao, que existe pra pegar GUTIERREZ/GUTIERRES, tratava iniciais
diferentes como quase iguais:

    R C B L  x  R C S A   ->  casava (B/S e L/A, uma letra cada)
    R C F S  x  R C S A   ->  casava

Com isso cinco pessoas anonimizadas viraram uma. Pior: a trava do efeito farol
(ver test_farol_subconjunto.py) nao salvava, porque esses casamentos entre os
vizinhos davam coesao 0,5 - exatamente na fronteira.

Calibrar limiar nao resolve isso, porque o problema nao e de grau. Nome
mascarado nao tem o que padronizar: fica como esta.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from matching import compare_names, find_clusters, normalize_name


def _cmp(a, b, **kw):
    return compare_names(normalize_name(a), normalize_name(b), **kw)


def _occ(texto, row=1, part=0, column="cliente"):
    return {"text": texto, "norm": normalize_name(texto), "source": "escavador",
            "row": row, "column": column, "part_index": part}


# ---------- nao compara ----------

PARES_MASCARADOS = [
    ("Q K B L", "Q K S A"),   # o caso real: uma letra de diferenca em dois tokens
    ("Q K F S", "Q K S A"),
    ("L A P", "L B P"),
    ("K K", "K F"),           # mesmo caso ja visto na conta (planilha real)
    ("N A S", "N C S"),
    ("Z A P", "Z C P"),
]


@pytest.mark.parametrize("a,b", PARES_MASCARADOS)
def test_duas_sequencias_de_iniciais_nunca_casam(a, b):
    assert _cmp(a, b) is None, f"{a!r} e {b!r} sao pessoas mascaradas distintas"


@pytest.mark.parametrize("a,b", PARES_MASCARADOS)
def test_nem_com_a_exigencia_relaxada_da_mesma_celula(a, b):
    """Na mesma celula o motor relaxa a exigencia do ultimo token. Pra nome
    mascarado isso nao pode abrir brecha - e justamente na mesma celula que os
    co-reus e co-vitimas de um processo aparecem."""
    assert _cmp(a, b, require_last_token=False) is None


def test_inicial_solta_nao_casa_com_nome_inteiro():
    """"Q K" nao pode ser colado em "ROBERTO CARLOS": a inicial pode ser de
    qualquer um, e escolher um seria inventar identidade."""
    assert _cmp("Q K", "ROBERTO CARLOS") is None
    assert _cmp("A", "ANTONIO SOUZA") is None


def test_sigla_curta_de_iniciais_nao_vira_ponte_no_agrupamento():
    """O caminho de verdade: find_clusters nao pode juntar o conjunto."""
    nomes = ["Q K", "Q K B L", "Q K F S", "Q K P R", "Q K S A"]
    clusters = find_clusters([_occ(n, row=i + 2) for i, n in enumerate(nomes)])
    for c in clusters:
        assert len(c["members"]) <= 1, f"nao devia agrupar mascarados: {c['members']}"


def test_mesma_celula_tambem_nao_junta():
    """Co-reus na mesma celula, que e como o dado real vem."""
    nomes = ["Z C P", "E O P", "Z A P"]
    clusters = find_clusters([_occ(n, row=4, part=i) for i, n in enumerate(nomes)])
    for c in clusters:
        assert len(c["members"]) <= 1, f"nao devia agrupar mascarados: {c['members']}"


# ---------- o que NAO pode mudar ----------

def test_nome_normal_com_uma_inicial_no_meio_continua_casando():
    """A regra e pra nome feito SO de iniciais. Abreviar o nome do meio e
    comum e tem que continuar funcionando (ex: "GILMAR O ROCHA")."""
    assert _cmp("GILMAR O ROCHA", "GILMAR OTAVIO ROCHA") is not None


def test_erro_de_digitacao_em_nome_de_verdade_continua_casando():
    """A trava nao pode ter desligado a regra de erro de digitacao."""
    assert _cmp("GUTIERREZ SOUZA", "GUTIERRES SOUZA") is not None


def test_empresa_com_sigla_na_frente_continua_casando():
    """Sigla + nome nao e "so iniciais": tem palavra de verdade depois."""
    assert _cmp("CAIXA ECONOMICA FEDERAL", "CEF CAIXA ECONOMICA FEDERAL") is not None
