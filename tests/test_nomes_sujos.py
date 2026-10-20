# -*- coding: utf-8 -*-
"""Levantamento dos nomes com lixo colado ou abreviados por sigla."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matching import find_dirty_names, normalize_name


def occ(text, column="cliente", row=1, source="escavador"):
    return {"text": text, "norm": normalize_name(text), "column": column,
            "row": row, "source": source}


def test_acha_sufixo_prf():
    itens = find_dirty_names([
        occ("BEATRIZ HELENA MOREIRA VILANOVA PEREIRA PRF VARA PREV", row=10),
        occ("MARIA DE LOURDES DA ANUNCIACAO", row=11),
    ])
    assert len(itens) == 1
    it = itens[0]
    assert it["sugerido"] == "BEATRIZ HELENA MOREIRA VILANOVA PEREIRA"
    assert it["motivo"] == "lixo"
    assert it["cliente_rows"] == [10]


def test_acha_representado_por():
    itens = find_dirty_names([occ("CARLOS SOUZA REPRESENTADO POR MARIA SOUZA")])
    assert itens[0]["sugerido"] == "CARLOS SOUZA"


def test_expande_sigla_com_nome_do_documento():
    itens = find_dirty_names([
        occ("MARIA APARECIDA RODRIGUES FONTES", row=1),
        occ("MARF", row=2),
    ])
    assert len(itens) == 1
    assert itens[0]["texto"] == "MARF"
    assert itens[0]["sugerido"] == "MARIA APARECIDA RODRIGUES FONTES"
    assert itens[0]["motivo"] == "sigla"


def test_sigla_sem_correspondencia_nao_entra():
    """Iniciais de menor que nao existem no documento continuam como estao."""
    itens = find_dirty_names([
        occ("MARIA APARECIDA RODRIGUES FONTES"),
        occ("X Y Z"),
    ])
    assert itens == []


def test_nome_limpo_nao_entra():
    itens = find_dirty_names([
        occ("HELENA MARTINS PACHECO DA COSTA"),
        occ("BANCO BRADESCO FINANCIAMENTOS S/A"),
    ])
    assert itens == []


def test_agrupa_ocorrencias_do_mesmo_nome():
    itens = find_dirty_names([
        occ("OSVALDO BRANDINI CASTELO PRF TRF EXEC FISCAL", column="cliente", row=3),
        occ("OSVALDO BRANDINI CASTELO PRF TRF EXEC FISCAL", column="parte_contraria", row=7),
    ])
    assert len(itens) == 1
    assert itens[0]["cliente_rows"] == [3]
    assert itens[0]["parte_rows"] == [7]
    assert itens[0]["n_cliente"] == 1
    assert itens[0]["n_parte_contraria"] == 1


def test_ignora_fonte_que_nao_e_planilha():
    itens = find_dirty_names([
        occ("FULANO DE TAL PRF VARA PREV", source="advbox_pessoas"),
    ])
    assert itens == []


def test_lista_vazia():
    assert find_dirty_names([]) == []
