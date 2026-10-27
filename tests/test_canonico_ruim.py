# -*- coding: utf-8 -*-
"""O nome final nao pode ser uma forma que RESTRINGE em vez de completar.

`suggest_canonical` escolhe a variante "mais completa", medindo por numero de
palavras. Isso funciona pra sobrenome que faltava, mas erra quando o token
extra nao e parte do nome:

  - marcador de cargo ou funcao colado no fim: "ROBERVAL PINTO COELHO CARGO",
    "IRACEMA BEVILAQUA ADV", "OSVALDO TADEU MARQUES CARGO PREFEITO";
  - orgao publico com sufixo societario, que orgao publico nao tem:
    "UNIAO FEDERAL S/A", "ESTADO DO CEARA LTDA", "MINISTERIO PUBLICO MPMG LTDA";
  - orgao publico com a UF colada: "MUNICIPIO DE IGUATU CE";
  - orgao publico com qualificador de LOCAL, que estreita o que era geral:
    escolher "MINISTERIO PUBLICO FEDERAL EM JUIZ DE FORA" como nome final de um
    grupo que tem tambem "MPF PR/SP" rotularia o processo de Sao Paulo como
    sendo de Juiz de Fora. O certo e a forma geral, "MINISTERIO PUBLICO
    FEDERAL".

Casos reais das contas (planilha real) (08/10/2026) e (planilha real) (21/10/2026).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from matching import normalize_name, suggest_canonical


def _occ_by_norm(textos):
    d = {}
    for t in textos:
        d.setdefault(normalize_name(t), []).append({"text": t, "norm": normalize_name(t)})
    return d


def _sugerido(textos):
    obn = _occ_by_norm(textos)
    return suggest_canonical(sorted(obn.keys()), obn)


# ---------- cargo / funcao colada no fim ----------

CARGO = [
    (["ROBERVAL PINTO COELHO", "ROBERVAL PINTO COELHO CARGO"],
     "ROBERVAL PINTO COELHO"),
    (["IRACEMA BEVILAQUA", "IRACEMA BEVILAQUA ADV"],
     "IRACEMA BEVILAQUA"),
    (["OSVALDO TADEU MARQUES", "OSVALDO TADEU MARQUES CARGO PREFEITO"],
     "OSVALDO TADEU MARQUES"),
]


@pytest.mark.parametrize("variantes,esperado", CARGO)
def test_nao_escolhe_forma_com_cargo_no_fim(variantes, esperado):
    assert _sugerido(variantes) == esperado


# ---------- orgao publico ----------

PUBLICO = [
    (["UNIAO FEDERAL", "UNIAO FEDERAL S/A"], "UNIAO FEDERAL"),
    (["ESTADO DO CEARA", "ESTADO DO CEARA LTDA"], "ESTADO DO CEARA"),
    (["MINISTERIO PUBLICO MPMG", "MINISTERIO PUBLICO MPMG LTDA"], "MINISTERIO PUBLICO MPMG"),
    (["MUNICIPIO DE IGUATU", "MUNICIPIO DE IGUATU CE"], "MUNICIPIO DE IGUATU"),
]


@pytest.mark.parametrize("variantes,esperado", PUBLICO)
def test_orgao_publico_nao_leva_sufixo_nem_uf(variantes, esperado):
    assert _sugerido(variantes) == esperado


def test_orgao_publico_prefere_a_forma_geral_a_local():
    """O caso do MPF: a forma com local nao pode virar o nome de todos."""
    assert _sugerido([
        "MINISTERIO PUBLICO FEDERAL",
        "MINISTERIO PUBLICO FEDERAL EM JUIZ DE FORA",
        "MINISTERIO PUBLICO FEDERAL PR/SP",
    ]) == "MINISTERIO PUBLICO FEDERAL"


# ---------- o que NAO pode mudar ----------

def test_sobrenome_que_faltava_continua_ganhando():
    """A regra geral segue valendo: entre duas formas boas, a mais completa."""
    assert _sugerido(["SIMONE MARQUES FERREIRA",
                      "SIMONE MARQUES FERREIRA RODRIGUES"]) == "SIMONE MARQUES FERREIRA RODRIGUES"


def test_empresa_privada_mantem_o_sufixo_societario():
    """LTDA e parte do nome de empresa privada - a regra e so pra orgao publico."""
    assert _sugerido(["ORBITAL TOUR", "ORBITAL TOUR LTDA"]) == "ORBITAL TOUR LTDA"


def test_empresa_privada_com_nome_longo_continua_ganhando():
    assert _sugerido([
        "ASPREV",
        "ASPREV ASSOCIACAO DE PROTECAO E DEFESA DOS DIREITOS DOS APOSENTADOS",
    ]) == "ASPREV ASSOCIACAO DE PROTECAO E DEFESA DOS DIREITOS DOS APOSENTADOS"


def test_quando_todas_as_formas_sao_ruins_ainda_devolve_alguma():
    """Nao pode devolver vazio so porque nenhuma candidata presta."""
    r = _sugerido(["JOSE DA SILVA CARGO", "JOSE DA SILVA ADV"])
    assert r in ("JOSE DA SILVA CARGO", "JOSE DA SILVA ADV")


def test_numero_colado_continua_sendo_penalizado():
    """Regra que ja existia: nome com numero nao vira o sugerido."""
    assert _sugerido(["MARIA AUXILIADORA GOMES",
                      "MARIA AUXILIADORA GOMES C 53"]) == "MARIA AUXILIADORA GOMES"


# ---------- artigo na frente e estado por extenso ----------

def test_artigo_na_frente_nao_esconde_o_orgao_publico():
    """"O ESTADO DE MINAS GERAIS S/A" tem que cair na mesma regra que
    "ESTADO DO CEARA LTDA". Sem tirar o artigo, o startswith falhava e a forma
    com S/A ganhava por ser mais longa - 45 celulas da conta (planilha real)."""
    assert _sugerido(["O ESTADO DE MINAS GERAIS",
                      "O ESTADO DE MINAS GERAIS S/A"]) == "O ESTADO DE MINAS GERAIS"


def test_estado_por_extenso_no_fim_de_orgao_publico():
    """Mesmo caso da UF abreviada, so escrito inteiro."""
    assert _sugerido(["MUNICIPIO DE UBA",
                      "MUNICIPIO DE UBA MINAS GERAIS"]) == "MUNICIPIO DE UBA"


def test_cidade_com_nome_de_estado_nao_e_confundida():
    """A regra olha o FIM do nome de orgao publico. Empresa privada nao entra,
    mesmo terminando com nome de estado."""
    assert _sugerido(["TRANSPORTES MINAS GERAIS",
                      "TRANSPORTES MINAS GERAIS LTDA"]) == "TRANSPORTES MINAS GERAIS LTDA"


def test_situacao_juridica_colada_nao_vira_nome_final():
    """"FALIDO" e estado processual da empresa, nao razao social: muda com o
    tempo e nao identifica a parte. Caso real da conta (planilha real)."""
    assert _sugerido(["BANCO CRUZEIRO DO SUL S/A",
                      "BANCO CRUZEIRO DO SUL S/A FALIDO"]) == "BANCO CRUZEIRO DO SUL S/A"
    assert _sugerido(["COMERCIAL XYZ LTDA",
                      "COMERCIAL XYZ LTDA EM RECUPERACAO"]) == "COMERCIAL XYZ LTDA"
