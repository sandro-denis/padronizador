# -*- coding: utf-8 -*-
"""Sessao antiga sai do disco sozinha.

Cada upload cria `data/sessions/<id>/` com a planilha enviada e as geradas.
Nada apagava isso: numa instalacao usada por mais de um escritorio, o arquivo
de um ficava no servidor indefinidamente, ao alcance de quem tivesse acesso ao
disco ou a um backup.

A varredura e OPORTUNISTA - roda a cada upload, em vez de depender de
agendador. Com um worker so (que e o que o `SESSIONS` em memoria exige)
isso basta, e funciona igual em qualquer hospedagem, sem servico extra.

Ela tambem resolve o orfao de reinicio: `SESSIONS` vive em memoria, entao
reiniciar o servidor perde a referencia mas deixa o diretorio no disco.
"""
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import app as app_module


@pytest.fixture()
def sessoes(tmp_path, monkeypatch):
    """Aponta o diretorio de sessoes pra um temporario."""
    d = tmp_path / "sessions"
    d.mkdir()
    monkeypatch.setattr(app_module, "SESSIONS_DIR", str(d))
    monkeypatch.setattr(app_module, "SESSIONS", {})
    return d


def _cria_sessao(raiz, nome, idade_minutos=0):
    sdir = raiz / nome
    (sdir / "uploads").mkdir(parents=True)
    io.open(sdir / "uploads" / "esc.xlsx", "w").write("conteudo")
    if idade_minutos:
        quando = time.time() - idade_minutos * 60
        os.utime(str(sdir), (quando, quando))
    return sdir


# ---------- apaga o que passou do prazo ----------

def test_apaga_sessao_mais_velha_que_o_ttl(sessoes, monkeypatch):
    monkeypatch.setattr(app_module, "SESSAO_TTL_MIN", 60)
    velha = _cria_sessao(sessoes, "aaaaaaaaaaaa", idade_minutos=120)
    app_module.SESSIONS["aaaaaaaaaaaa"] = {"out_dir": str(velha)}

    app_module._limpar_sessoes_antigas()

    assert not velha.exists(), "o diretorio devia ter sido apagado"
    assert "aaaaaaaaaaaa" not in app_module.SESSIONS, "e a referencia em memoria tambem"


def test_mantem_sessao_dentro_do_prazo(sessoes, monkeypatch):
    monkeypatch.setattr(app_module, "SESSAO_TTL_MIN", 60)
    nova = _cria_sessao(sessoes, "bbbbbbbbbbbb", idade_minutos=5)
    app_module.SESSIONS["bbbbbbbbbbbb"] = {"out_dir": str(nova)}

    app_module._limpar_sessoes_antigas()

    assert nova.exists(), "sessao em uso nao pode ser apagada no meio do trabalho"
    assert "bbbbbbbbbbbb" in app_module.SESSIONS


def test_apaga_orfao_de_reinicio(sessoes, monkeypatch):
    """Diretorio no disco sem entrada no SESSIONS: sobrou de um reinicio."""
    monkeypatch.setattr(app_module, "SESSAO_TTL_MIN", 60)
    orfao = _cria_sessao(sessoes, "cccccccccccc", idade_minutos=200)
    assert "cccccccccccc" not in app_module.SESSIONS

    app_module._limpar_sessoes_antigas()

    assert not orfao.exists()


def test_apaga_varias_e_devolve_a_contagem(sessoes, monkeypatch):
    monkeypatch.setattr(app_module, "SESSAO_TTL_MIN", 30)
    for i in range(3):
        _cria_sessao(sessoes, f"velha{i}aaaaaa", idade_minutos=90)
    _cria_sessao(sessoes, "recenteaaaaa", idade_minutos=1)

    n = app_module._limpar_sessoes_antigas()

    assert n == 3
    assert (sessoes / "recenteaaaaa").exists()


# ---------- desligado ----------

def test_ttl_zero_desliga_a_limpeza(sessoes, monkeypatch):
    """Quem roda na propria maquina pode querer manter os arquivos."""
    monkeypatch.setattr(app_module, "SESSAO_TTL_MIN", 0)
    velha = _cria_sessao(sessoes, "dddddddddddd", idade_minutos=99999)

    assert app_module._limpar_sessoes_antigas() == 0
    assert velha.exists()


# ---------- robustez ----------

def test_nao_quebra_com_arquivo_solto_no_diretorio(sessoes, monkeypatch):
    """Se houver um arquivo (nao diretorio) ali, a varredura ignora e segue."""
    monkeypatch.setattr(app_module, "SESSAO_TTL_MIN", 60)
    io.open(sessoes / "solto.txt", "w").write("x")
    velha = _cria_sessao(sessoes, "eeeeeeeeeeee", idade_minutos=120)

    app_module._limpar_sessoes_antigas()

    assert not velha.exists()
    assert (sessoes / "solto.txt").exists()


def test_nao_quebra_se_o_diretorio_de_sessoes_nao_existe(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "SESSIONS_DIR", str(tmp_path / "nao_existe"))
    monkeypatch.setattr(app_module, "SESSAO_TTL_MIN", 60)
    assert app_module._limpar_sessoes_antigas() == 0


def test_ignora_o_temporario_do_ocr(sessoes, monkeypatch):
    """`_ocr_tmp` e area de trabalho do OCR, nao sessao - tem nome fixo e e
    recriada sozinha, entao a varredura nao precisa se meter com ela."""
    monkeypatch.setattr(app_module, "SESSAO_TTL_MIN", 60)
    tmp = sessoes / "_ocr_tmp"
    tmp.mkdir()
    quando = time.time() - 9999 * 60
    os.utime(str(tmp), (quando, quando))

    app_module._limpar_sessoes_antigas()

    assert tmp.exists()


# ---------- o OCR tem que se declarar indisponivel fora do Windows ----------

def test_ocr_indisponivel_fora_do_windows(monkeypatch):
    """A instancia hospedada roda em Linux. `disponivel()` precisa devolver
    False la, porque /api/config leva esse valor pra tela e ela esconde a
    secao do print - melhor ausente do que presente e sempre falhando."""
    import ocr_helper
    monkeypatch.setattr(ocr_helper.os, "name", "posix")
    assert ocr_helper.disponivel() is False


def test_ocr_indisponivel_se_o_powershell_nao_existe(monkeypatch):
    import ocr_helper
    monkeypatch.setattr(ocr_helper.os, "name", "nt")
    monkeypatch.setattr(ocr_helper.os.path, "exists", lambda p: False)
    assert ocr_helper.disponivel() is False


def test_rota_de_ocr_recusa_com_mensagem_clara(monkeypatch):
    """Em vez de estourar 500, explica o que fazer."""
    import ocr_helper
    monkeypatch.setattr(ocr_helper, "disponivel", lambda: False)
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        r = c.post("/api/ocr", data={})
        assert r.status_code == 400
        assert "Windows" in r.get_json()["error"]
