# -*- coding: utf-8 -*-
"""A revisao de uma pessoa nao pode morrer por causa do servidor nem de outra.

Dois modos de perder o trabalho que existiam antes, os dois reais (um deles
derrubou uma revisao de 158 itens numa instancia hospedada):

  1. REINICIO - o SESSIONS vive na memoria do processo. Qualquer reinicio
     (deploy, worker novo, queda) apagava a referencia, mesmo com os arquivos
     ainda no disco. Agora a sessao e REMONTADA do disco (_rehidratar_sessao),
     porque tudo que o SESSIONS guarda e cache: dados ja lidos e caminhos.

  2. VIZINHO - a varredura por TTL olha o mtime do diretorio, e durante a
     revisao nada e escrito nele (a revisao inteira acontece no navegador).
     Entao uma revisao longa era apagada pelo UPLOAD DE OUTRA PESSOA. Agora a
     aba manda sinal de vida (/api/ping) e isso marca a sessao como ativa.

O que NAO pode mudar: a varredura tem que continuar apagando sessao de
verdade abandonada - o motivo dela existir e nao deixar planilha de cliente
parada no disco de um servidor compartilhado.
"""
import io
import os
import shutil
import sys
import time

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


def _planilha(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["NOME DO CLIENTE", "PARTE CONTRARIA"])
    ws.append(["FULANO DE TAL", "BANCO X"])
    ws.append(["FULANO DE TAL SILVA", "BANCO X S/A"])
    wb.save(path)


def _subir(client, tmp_path, nome="esc.xlsx"):
    p = tmp_path / nome
    _planilha(p)
    with open(str(p), "rb") as f:
        r = client.post("/api/upload",
                        data={"escavador": (io.BytesIO(f.read()), nome)},
                        content_type="multipart/form-data")
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()["session_id"]


def _envelhecer(sid, minutos):
    d = os.path.join(app_module.SESSIONS_DIR, sid)
    quando = time.time() - minutos * 60
    os.utime(d, (quando, quando))


# ---------- 1. sobreviver ao reinicio do processo ----------

def test_remonta_a_sessao_depois_de_perder_a_memoria(client, tmp_path):
    sid = _subir(client, tmp_path)
    app_module.SESSIONS.clear()  # e isso que um reinicio faz

    r = client.post("/api/analyze", json={"session_id": sid, "threshold": 88})

    assert r.status_code == 200, "a sessao devia ter sido remontada do disco"
    assert r.get_json()["clusters"], "e com os mesmos dados de antes"


def test_aplicar_funciona_depois_de_perder_a_memoria(client, tmp_path):
    """O caso que doi: a pessoa revisou tudo e so entao o servidor reiniciou."""
    sid = _subir(client, tmp_path)
    analise = client.post("/api/analyze", json={"session_id": sid, "threshold": 88}).get_json()
    decisao = [{"cluster_id": c["id"], "members": c["members"], "excluded_members": [],
                "action": "merge", "canonical": c["suggested_canonical"], "touched": True}
               for c in analise["clusters"]]

    app_module.SESSIONS.clear()

    r = client.post("/api/apply", json={"session_id": sid, "decisions": decisao,
                                        "dry_run": True, "persist_rules": False})
    assert r.status_code == 200, r.get_data(as_text=True)


def test_nao_remonta_quando_os_arquivos_sumiram(client, tmp_path):
    """Disco efemero que reiniciou limpo: ai nao da pra remontar mesmo, e a
    resposta tem que ser clara pra tela saber que precisa reenviar."""
    sid = _subir(client, tmp_path)
    app_module.SESSIONS.clear()
    shutil.rmtree(os.path.join(app_module.SESSIONS_DIR, sid))

    r = client.post("/api/analyze", json={"session_id": sid, "threshold": 88})
    assert r.status_code == 404


# ---------- 2. nao ser apagada pelo upload de outra pessoa ----------

def test_sinal_de_vida_protege_revisao_longa_do_upload_alheio(client, tmp_path, monkeypatch):
    """O bug de convivencia: A revisa ha mais de uma hora, B sobe um arquivo,
    e a varredura de B apagava a sessao de A."""
    monkeypatch.setattr(app_module, "SESSAO_TTL_MIN", 60)
    a = _subir(client, tmp_path, "a.xlsx")
    _envelhecer(a, 120)

    r = client.post("/api/ping/" + a)
    assert r.get_json()["viva"] is True

    _subir(client, tmp_path, "b.xlsx")  # o upload de B dispara a varredura

    assert os.path.isdir(os.path.join(app_module.SESSIONS_DIR, a)), \
        "a sessao de A estava em uso e nao podia ser apagada pelo upload de B"
    assert client.post("/api/analyze", json={"session_id": a, "threshold": 88}).status_code == 200


def test_sem_sinal_de_vida_a_varredura_continua_limpando(client, tmp_path, monkeypatch):
    """O que NAO pode mudar: sessao de verdade abandonada tem que sumir do
    disco - e pra isso que a varredura existe."""
    monkeypatch.setattr(app_module, "SESSAO_TTL_MIN", 60)
    a = _subir(client, tmp_path, "a.xlsx")
    _envelhecer(a, 120)

    _subir(client, tmp_path, "b.xlsx")

    assert not os.path.isdir(os.path.join(app_module.SESSIONS_DIR, a))


def test_ping_de_sessao_inexistente_responde_que_nao_esta_viva(client):
    r = client.post("/api/ping/naoexiste123")
    assert r.status_code == 200
    assert r.get_json()["viva"] is False


def test_ping_nao_ressuscita_diretorio_apagado(client, tmp_path):
    """_tocar_sessao nao pode usar _session_dir: aquele CRIA o diretorio, e
    recriar um ja varrido deixaria uma sessao vazia e inutil no disco - que a
    varredura teria que limpar de novo, por tempo indeterminado."""
    sid = _subir(client, tmp_path)
    app_module.SESSIONS.clear()
    shutil.rmtree(os.path.join(app_module.SESSIONS_DIR, sid))

    client.post("/api/ping/" + sid)

    assert not os.path.isdir(os.path.join(app_module.SESSIONS_DIR, sid))


# ---------- o mapa de papeis ----------

def test_meta_guarda_qual_arquivo_era_qual(client, tmp_path):
    """Sem isso a remontagem nao sabe se o .xlsx era do Escavador ou de
    Clientes - no disco os dois sao so um nome de arquivo dentro de uploads/."""
    sid = _subir(client, tmp_path, "planilha_qualquer.xlsx")
    import json
    caminho = os.path.join(app_module.SESSIONS_DIR, sid, "meta.json")
    assert os.path.isfile(caminho)
    with io.open(caminho, encoding="utf-8") as f:
        papeis = json.load(f)
    assert papeis["esc"] == "planilha_qualquer.xlsx"
    assert papeis["cli"] is None
