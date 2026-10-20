# -*- coding: utf-8 -*-
"""Empresas que escapavam do agrupamento mesmo na MESMA CELULA.

Dois casos reais que o padronizador deixou passar (05/10/2026), com causas
diferentes:

  1. sigla na frente - "CAIXA ECONOMICA FEDERAL" x "CEF CAIXA ECONOMICA
     FEDERAL". `compare_names` exige que o PRIMEIRO token bata (e a ancora de
     identidade pra nome de pessoa: o prenome). Em empresa, uma sigla colada
     na frente desloca todos os tokens e a comparacao morria na porta.

  2. palavra quebrada em duas - "SOL NASCENTE CONSTRUC ES ... EIRELI" x "SOL
     NASCENTE CONSTRUCOES ... LTDA". "CONSTRUÇÕES" perdeu o Ç/Õ na importacao e
     virou DOIS tokens ("CONSTRUC" + "ES"), desalinhando a comparacao token a
     token.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from matching import compare_names, find_clusters, normalize_name


def _occ(texto, row=5, part=0, column="parte_contraria"):
    return {"text": texto, "norm": normalize_name(texto), "source": "escavador",
            "row": row, "column": column, "part_index": part}


def _agrupou(a, b):
    """True quando os dois nomes caem no MESMO cluster, pelo caminho real
    (find_clusters), estando na mesma celula."""
    clusters = find_clusters([_occ(a, part=0), _occ(b, part=1)])
    alvo = {normalize_name(a), normalize_name(b)}
    return any(alvo <= set(c["members"]) for c in clusters)


# ---------- bug 1: sigla colada na frente ----------

SIGLA_NA_FRENTE = [
    ("CAIXA ECONOMICA FEDERAL", "CEF CAIXA ECONOMICA FEDERAL"),
    ("BANCO CENTRAL DO BRASIL", "BCB BANCO CENTRAL DO BRASIL"),
    ("INSTITUTO NACIONAL DO SEGURO SOCIAL", "INSS INSTITUTO NACIONAL DO SEGURO SOCIAL"),
]


@pytest.mark.parametrize("a,b", SIGLA_NA_FRENTE)
def test_sigla_na_frente_agrupa(a, b):
    assert _agrupou(a, b), f"deveriam ser a mesma entidade: {a!r} x {b!r}"


def test_sigla_na_frente_tambem_vale_fora_da_celula():
    """Nao e um conserto so pro caminho de mesma celula - a comparacao em si
    tem que passar a reconhecer."""
    assert compare_names(
        normalize_name("CAIXA ECONOMICA FEDERAL"),
        normalize_name("CEF CAIXA ECONOMICA FEDERAL"),
    ) is not None


def test_prefixo_que_nao_e_sigla_nao_agrupa():
    """A trava: so remove o token da frente quando ele e EXATAMENTE as
    iniciais do que vem depois. "SUL" nao e sigla de "AMERICA SEGUROS", entao
    "SUL AMERICA SEGUROS" nao pode virar a mesma coisa que "AMERICA SEGUROS"."""
    assert not _agrupou("AMERICA SEGUROS", "SUL AMERICA SEGUROS")


def test_sigla_nao_junta_empresas_diferentes():
    """A sigla certa de uma nao pode arrastar outra empresa junto."""
    assert not _agrupou("CEF CAIXA ECONOMICA FEDERAL", "CEF CENTRAL DE FRETES")


# ---------- bug 2: palavra quebrada em duas ----------

PALAVRA_QUEBRADA = [
    ("SOL NASCENTE CONSTRUC ES E EMPREENDIMENTOS EIRELI",
     "SOL NASCENTE CONSTRUCOES E EMPREENDIMENTOS LTDA"),
    ("SERRANIA CONSTRUC OES LTDA", "SERRANIA CONSTRUCOES LTDA"),
]


@pytest.mark.parametrize("a,b", PALAVRA_QUEBRADA)
def test_palavra_quebrada_agrupa(a, b):
    assert _agrupou(a, b), f"deveriam ser a mesma empresa: {a!r} x {b!r}"


def test_juncao_nao_inventa_match_entre_empresas_diferentes():
    """Juntar tokens adjacentes nao pode virar licenca pra casar qualquer
    coisa - "SOL NASCENTE" e "SOLBRAVO" sao empresas diferentes e aparecem na
    mesma celula no caso real."""
    assert not _agrupou(
        "SOL NASCENTE CONSTRUCOES E EMPREENDIMENTOS LTDA",
        "SOLBRAVO PARTICIPACOES E INCORPORACOES LTDA",
    )


def test_nao_junta_sobrenome_de_pessoa():
    """A juncao e pra palavra partida por erro de codificacao, nao pra somar
    sobrenomes: "ANA PAULA SOUZA" nao e "ANAPAULA SOUZA" de outra pessoa...
    mas tambem nao pode fundir "ANA SOUZA" com "ANA PAULA SOUZA" por juntar
    tokens - isso ja e papel da regra de subconjunto, com as travas dela."""
    assert not _agrupou("MARIA SILVA", "MARIANA SILVA")


# ---------- bug 3: mesma palavra em outra forma, no fim do nome ----------

def test_ultima_palavra_em_outra_forma_agrupa():
    """"ALIMENTACAO" e "ALIMENTOS" sao a mesma palavra flexionada: tudo no
    nome bate menos a ultima, que fica em 80% - abaixo do piso de 85 da
    ponta."""
    assert _agrupou("NUTRI INDUSTRIA PAULISTA DE ALIMENTACAO LTDA",
                    "NUTRI INDUSTRIA PAULISTA DE ALIMENTOS")


def test_radical_curto_no_fim_nao_agrupa():
    """A trava do radical: SESC do Ceara e SESC do Rio Grande do Norte sao
    regionais diferentes - "CE" e "RN" nao compartilham radical nenhum."""
    assert not _agrupou("SERVICO SOCIAL DO COMERCIO SESC AR CE",
                        "SERVICO SOCIAL DO COMERCIO SESC AR RN")


def test_sobrenome_parecido_no_fim_nao_agrupa():
    """"SILVA"/"SILVEIRA" e "SANTOS"/"SANTANA" param no radical de 4 letras,
    entao a regra do radical nao os aproxima.

    Aqui a checagem e em `compare_names` e nao em `_agrupou`: dentro da MESMA
    celula o motor relaxa a exigencia do ultimo token de proposito (ver
    require_last_token), e esses dois casam por outro caminho - comportamento
    que ja existia antes desta regra e que nao e assunto deste teste."""
    assert compare_names(normalize_name("JOAO CARLOS SILVA"),
                         normalize_name("JOAO CARLOS SILVEIRA")) is None
    assert compare_names(normalize_name("JOAO CARLOS SANTOS"),
                         normalize_name("JOAO CARLOS SANTANA")) is None


def test_regra_do_radical_nao_vale_pro_primeiro_token():
    """No primeiro token, "nome curto que e prefixo do longo" sao pessoas
    diferentes - LUZA/LUZANIR tem a mesma forma de MARIA/MARIANA."""
    assert not _agrupou("LUZANIR BARROSO DA MATA", "LUZA BARROSO DA MATA")
