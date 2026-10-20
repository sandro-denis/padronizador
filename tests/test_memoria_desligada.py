# -*- coding: utf-8 -*-
"""A memoria de decisoes vem DESLIGADA, e desligada nao le nem grava nada.

O arquivo data/decisions.json e UNICO e GLOBAL - nao tem separacao por usuario
nem por conta. Numa instalacao usada por mais de uma pessoa, lembrar decisoes
significaria mostrar nome de cliente de um escritorio como sugestao no de
outro. Por isso o padrao e nao lembrar, e por isso a trava fica no servidor:
nao basta o front-end deixar de pedir.

Estes testes protegem as duas metades da promessa:
  - nao LEMBRA: mesmo com um decisions.json cheio no disco, a leitura volta vazia;
  - nao SALVA: depois de gravar, o arquivo nem chega a existir.
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import rules_store


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Aponta a persistencia pra um arquivo temporario, nunca o do usuario."""
    monkeypatch.setattr(rules_store, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(rules_store, "STORE_PATH", str(tmp_path / "decisions.json"))
    return tmp_path / "decisions.json"


def _escreve_memoria_cheia(caminho):
    """Um decisions.json com decisao de verdade em todas as gavetas que contam."""
    dados = rules_store._empty_store()
    dados["confirmed"] = [["JOAO DA SILVA", "JOAO SILVA", "JOAO DA SILVA"]]
    dados["blacklist"] = [["MARIA SILVA", "MARIANA SILVA"]]
    dados["cliente_as_parte"] = [{"norm": "BANCO X", "action": "only_parte"}]
    dados["court_judge"] = [{"norm": "JUIZO DA 1 VARA", "action": "remove"}]
    io.open(caminho, "w", encoding="utf-8").write(json.dumps(dados, ensure_ascii=False))


# ---------- padrao ----------

def test_memoria_vem_desligada_por_padrao():
    """Se este teste quebrar, uma instalacao publica passou a lembrar decisoes
    de um escritorio e a oferece-las a outro. E o padrao, nao um detalhe."""
    assert rules_store.MEMORIA is False


# ---------- nao LEMBRA ----------

def test_desligada_nao_le_arquivo_existente(store, monkeypatch):
    monkeypatch.setattr(rules_store, "MEMORIA", False)
    _escreve_memoria_cheia(store)
    assert rules_store.load_raw() == rules_store._empty_store()


def test_desligada_nao_sugere_par_confirmado(store, monkeypatch):
    """`load_sets` e o que alimenta o agrupamento: desligada, nao pode trazer
    nem o par confirmado nem o par vetado de uma planilha anterior."""
    monkeypatch.setattr(rules_store, "MEMORIA", False)
    _escreve_memoria_cheia(store)
    blacklist, confirmed = rules_store.load_sets()
    assert blacklist == set()
    assert confirmed == {}


@pytest.mark.parametrize("carregar", [
    "load_cliente_parte_overlap_decisions",
    "load_court_judge_decisions",
    "load_advbox_only_decisions",
    "load_advbox_conflict_decisions",
    "load_tipo_acao_decisions",
    "load_grupo_acao_decisions",
    "load_responsavel_decisions",
    "load_nome_validacao_decisions",
    "load_financeiro_orphan_decisions",
    "load_nome_limpeza_decisions",
])
def test_desligada_toda_gaveta_volta_vazia(store, monkeypatch, carregar):
    monkeypatch.setattr(rules_store, "MEMORIA", False)
    _escreve_memoria_cheia(store)
    assert not getattr(rules_store, carregar)()


# ---------- nao SALVA ----------

def test_desligada_nao_cria_o_arquivo(store, monkeypatch):
    monkeypatch.setattr(rules_store, "MEMORIA", False)
    rules_store.add_confirmed_pair("JOAO DA SILVA", "JOAO SILVA", "JOAO DA SILVA")
    rules_store.add_blacklist_pair("MARIA SILVA", "MARIANA SILVA")
    rules_store.save_court_judge_decision("JUIZO DA 1 VARA", "remove")
    rules_store.save_tipo_acao_decision("ACAO DE COBRANCA", "aplicar", "ACAO DE COBRANCA")
    assert not os.path.exists(str(store)), "nao devia ter criado decisions.json"


def test_desligada_nao_acrescenta_a_arquivo_que_ja_existia(store, monkeypatch):
    """Se o arquivo veio de uma instalacao que tinha memoria, desligar tem que
    congelar: nao le, e tambem nao escreve por cima."""
    monkeypatch.setattr(rules_store, "MEMORIA", False)
    _escreve_memoria_cheia(store)
    antes = io.open(str(store), encoding="utf-8").read()
    rules_store.add_confirmed_pair("PEDRO ALVES", "PEDRO A ALVES", "PEDRO ALVES")
    assert io.open(str(store), encoding="utf-8").read() == antes


# ---------- controle: ligada ainda funciona ----------

def test_ligada_ainda_lembra(store, monkeypatch):
    """O contrario do caso acima - se ligar, a memoria tem que voltar a valer,
    senao o teste de cima estaria passando por outro motivo."""
    monkeypatch.setattr(rules_store, "MEMORIA", True)
    rules_store.add_confirmed_pair("JOAO DA SILVA", "JOAO SILVA", "JOAO DA SILVA")
    assert os.path.exists(str(store))
    _, confirmed = rules_store.load_sets()
    assert confirmed[frozenset(("JOAO DA SILVA", "JOAO SILVA"))] == "JOAO DA SILVA"
