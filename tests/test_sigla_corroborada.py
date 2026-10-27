# -*- coding: utf-8 -*-
"""Expandir sigla exige o nome inteiro NO MESMO PROCESSO.

`expandir_sigla` resolve iniciais contra os nomes da propria planilha e desiste
quando ha ambiguidade. Isso basta num acervo pequeno, mas nao num grande: entre
1.484 nomes, quase toda sequencia de 3 iniciais encontra UM nome com aquelas
letras, por acaso, e a falta de ambiguidade deixa de ser evidencia.

Medido na conta (planilha real) (3.016 processos de uma pratica criminal, 21/10/2026):
das 28 siglas que o motor expandia, 27 tinham o nome sugerido em processo
NENHUM em comum com a sigla. Coincidencia de iniciais, nao identidade. As duas
que mais denunciam o mecanismo:

    'T M S'  ->  'TOKIO MARINE SEGURADORA S/A'
    'A C B'  ->  'APPLE COMPUTER BRASIL LTDA'

E as de pessoa sao o mesmo acaso, com consequencia pior: numa pratica criminal
a sigla e de vitima ou de menor com identidade selada. Se a expansao estiver
errada, troca o nome de uma parte; se estiver certa, revela o que o processo
oculta. Nos dois casos nao e pra sugerir.

A trava: so sugere quando a sigla e o nome inteiro aparecem no MESMO processo
(mesma linha) - que e a situacao pra qual a regra foi feita, o Escavador tendo
abreviado numa coluna um nome que esta inteiro na outra.

A trava fica em `find_dirty_names`, que e quem conhece as linhas.
`expandir_sigla` continua sendo um utilitario puro sobre uma lista de nomes, com
os testes dele intactos (ver test_sigla.py).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matching import find_dirty_names, normalize_name


def _occ(texto, row, column="cliente"):
    return {"text": texto, "norm": normalize_name(texto), "source": "escavador",
            "row": row, "column": column, "part_index": 0}


def _siglas(resultados):
    return {r["texto"]: r["sugerido"] for r in resultados if r["motivo"] == "sigla"}


def test_nao_expande_quando_o_nome_esta_em_outro_processo():
    """O caso real: a sigla na linha 2, o nome parecido na linha 500."""
    occ = [_occ("Z C P", 2), _occ("ZELIA CRISTINA PACHECO", 500)]
    assert _siglas(find_dirty_names(occ)) == {}


def test_expande_quando_os_dois_estao_no_mesmo_processo():
    """A situacao pra qual a regra existe: abreviado numa coluna, inteiro na
    outra, no MESMO processo."""
    occ = [_occ("E M D F", 639),
           _occ("EDMAR MOTA DE FARIAS", 639, column="parte_contraria")]
    assert _siglas(find_dirty_names(occ)) == {"E M D F": "EDMAR MOTA DE FARIAS"}


def test_nao_expande_empresa_por_coincidencia_de_iniciais():
    """'T M S' nao e a Tokio Marine so por ter as mesmas tres letras."""
    occ = [_occ("T M S", 10), _occ("TOKIO MARINE SEGURADORA S/A", 900)]
    assert _siglas(find_dirty_names(occ)) == {}


def test_varias_siglas_de_processos_diferentes_nenhuma_expande():
    occ = [
        _occ("J S P", 2), _occ("JURANDIR DOS SANTOS PINHEIRO", 300),
        _occ("A G R", 3), _occ("AMELIA GONCALVES RODRIGUES", 301),
        _occ("A C B", 4), _occ("APPLE COMPUTER BRASIL LTDA", 302),
    ]
    assert _siglas(find_dirty_names(occ)) == {}


def test_lixo_colado_continua_sendo_sinalizado():
    """A trava e so da sigla: o outro motivo de `find_dirty_names` - lixo
    colado no nome - nao depende de linha e tem que seguir funcionando."""
    occ = [_occ("CARLOS SOUZA REPRESENTADO POR MARIA SOUZA", 7)]
    r = find_dirty_names(occ)
    assert [x["motivo"] for x in r] == ["lixo"]
    assert r[0]["sugerido"] == "CARLOS SOUZA"


def test_sigla_contigua_nao_exige_mesmo_processo():
    """A trava e so pra iniciais SEPARADAS, que e a forma do mascaramento.

    "MARF" e sigla contigua - alguem abreviou o nome ao digitar, nao ha
    convencao de sigilo nisso, e a checagem de ambiguidade de `expandir_sigla`
    da conta. Comportamento que ja existia (ver test_nomes_sujos.py) e que esta
    trava nao pode ter desligado.
    """
    occ = [_occ("MARIA APARECIDA RODRIGUES FONTES", 1), _occ("MARF", 2)]
    assert _siglas(find_dirty_names(occ)) == {"MARF": "MARIA APARECIDA RODRIGUES FONTES"}
