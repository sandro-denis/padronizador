# -*- coding: utf-8 -*-
"""O agrupamento nao pode ser refeito a cada "Comparar".

Agrupar e a parte cara: numa conta real sao 564 mil pares, perto de um minuto
e meio numa hospedagem modesta. E ele depende so dos nomes, do limiar e das
regras guardadas - nao muda quando a pessoa cola a lista oficial de
responsaveis ou de tipos de acao.

O botao "Comparar" existe em quatro secoes e chama /api/analyze de novo. Sem
cache, cada clique repetia o calculo inteiro para dar a MESMA resposta.

O que NAO pode mudar: mexer no controle de sensibilidade tem que recalcular de
verdade, senao a tela mentiria mostrando o agrupamento do limiar anterior.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
import pytest

import app as app_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr(app_module, "SESSIONS", {})
    os.makedirs(str(tmp_path / "sessions"), exist_ok=True)
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture()
def contador(monkeypatch):
    """Conta quantas vezes o agrupamento foi de fato calculado."""
    chamadas = []
    original = app_module.find_clusters

    def espiao(*a, **kw):
        chamadas.append(1)
        return original(*a, **kw)

    monkeypatch.setattr(app_module, "find_clusters", espiao)
    return chamadas


def _subir(client, tmp_path):
    p = tmp_path / "esc.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["NOME DO CLIENTE", "PARTE CONTRARIA"])
    ws.append(["FULANO DE TAL", "BANCO X"])
    ws.append(["FULANO DE TAL SILVA", "BANCO X S/A"])
    wb.save(p)
    with open(str(p), "rb") as f:
        r = client.post("/api/upload",
                        data={"escavador": (io.BytesIO(f.read()), "esc.xlsx")},
                        content_type="multipart/form-data")
    assert r.status_code == 200
    return r.get_json()["session_id"]


def test_analisar_duas_vezes_igual_agrupa_uma_vez_so(client, tmp_path, contador):
    sid = _subir(client, tmp_path)
    client.post("/api/analyze", json={"session_id": sid, "threshold": 88})
    client.post("/api/analyze", json={"session_id": sid, "threshold": 88,
                                      "responsaveis_text": "ALGUEM"})

    assert len(contador) == 1, "o segundo Comparar nao podia reagrupar tudo de novo"


def test_a_resposta_do_cache_e_a_mesma(client, tmp_path):
    """Rapido nao vale nada se vier diferente."""
    sid = _subir(client, tmp_path)
    a = client.post("/api/analyze", json={"session_id": sid, "threshold": 88}).get_json()
    b = client.post("/api/analyze", json={"session_id": sid, "threshold": 88}).get_json()
    assert a["clusters"] == b["clusters"]


def test_mudar_a_sensibilidade_recalcula(client, tmp_path, contador):
    """O que NAO pode mudar: o controle de sensibilidade tem que valer."""
    sid = _subir(client, tmp_path)
    client.post("/api/analyze", json={"session_id": sid, "threshold": 88})
    client.post("/api/analyze", json={"session_id": sid, "threshold": 75})

    assert len(contador) == 2


def test_voltar_pro_limiar_anterior_recalcula(client, tmp_path, contador):
    """O cache guarda UM limiar: voltar pra 88 depois de passar por 75 nao pode
    devolver o resultado de 75."""
    sid = _subir(client, tmp_path)
    client.post("/api/analyze", json={"session_id": sid, "threshold": 88})
    client.post("/api/analyze", json={"session_id": sid, "threshold": 75})
    r = client.post("/api/analyze", json={"session_id": sid, "threshold": 88})

    assert len(contador) == 3
    assert r.status_code == 200


def test_depois_de_aplicar_o_cache_cai(client, tmp_path, contador):
    """Aplicar pode gravar decisoes novas, e elas mudam o agrupamento."""
    sid = _subir(client, tmp_path)
    client.post("/api/analyze", json={"session_id": sid, "threshold": 88})
    client.post("/api/apply", json={"session_id": sid, "dry_run": True,
                                    "persist_rules": False, "decisions": []})
    client.post("/api/analyze", json={"session_id": sid, "threshold": 88})

    assert len(contador) == 2, "depois de aplicar, o agrupamento tem que ser refeito"
