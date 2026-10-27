"""
Padronizador - app web local (Flask) para revisar e corrigir homonimos/duplicatas
de clientes nas planilhas do Escavador (Processos) e de Clientes (CPF).

Fluxo:
  1. Upload dos arquivos (POST /api/upload)
  2. Analise / clustering (POST /api/analyze) - pode ser chamado de novo com um
     limiar de similaridade diferente sem reenviar os arquivos.
  3. Revisao no navegador (o usuario decide, por cluster: aplicar canonico X,
     ignorar, ou marcar como "nao e a mesma pessoa").
  4. Aplicar (POST /api/apply) - gera os arquivos corrigidos + aba de log.
  5. Download (GET /api/download/<session_id>/<kind>)
"""
import json
import os
import shutil
import time
import uuid
from collections import defaultdict

from flask import Flask, jsonify, request, render_template, send_file, abort

import advbox_io
import excel_io
import ocr_helper
import report
import rules_store
from matching import (
    DEFAULT_THRESHOLD,
    build_occurrence_index,
    find_advbox_field_conflicts,
    find_advbox_only_candidates,
    find_clusters,
    find_cliente_parte_overlap,
    find_clientes_duplicates,
    find_court_or_judge_names,
    find_financeiro_orphans,
    find_label_clusters,
    match_against_registry,
    match_category_against_registry,
    normalize_name,
    suggest_canonical,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSIONS_DIR = os.path.join(BASE_DIR, "data", "sessions")
os.makedirs(SESSIONS_DIR, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB

# sessao em memoria: session_id -> {esc_meta, esc_path, cli_meta, cli_path, occ_by_norm, clusters}
SESSIONS = {}

# Tempo de vida de uma sessao no disco, em minutos. 0 desliga a limpeza.
#
# Cada upload cria data/sessions/<id>/ com a planilha enviada e as geradas.
# Numa instalacao usada por mais de um escritorio, esse arquivo nao pode ficar
# no servidor depois que a pessoa terminou: fica ao alcance de quem tiver acesso
# ao disco ou a um backup.
#
# O padrao de 24h e generoso de proposito - quem esta no meio de uma revisao
# nao pode ver o trabalho desaparecer. Numa instancia publica, baixe isso
# (PADRONIZADOR_SESSAO_TTL_MIN=60) e prefira hospedagem de disco efemero.
SESSAO_TTL_MIN = int(os.environ.get("PADRONIZADOR_SESSAO_TTL_MIN", "1440"))

# area de trabalho do OCR: nome fixo, recriada sozinha, nao e sessao
_OCR_TMP = "_ocr_tmp"


def _limpar_sessoes_antigas():
    """Apaga do disco, e do SESSIONS, toda sessao mais velha que o TTL.

    Roda de forma OPORTUNISTA (a cada upload) em vez de depender de agendador:
    com um worker so - que e o que o SESSIONS em memoria exige - isso basta, e
    funciona igual em qualquer hospedagem, sem servico extra.

    Tambem resolve o orfao de reinicio: o SESSIONS vive em memoria, entao
    reiniciar o servidor perde a referencia mas deixa o diretorio no disco.

    Devolve quantas sessoes foram apagadas.
    """
    if SESSAO_TTL_MIN <= 0 or not os.path.isdir(SESSIONS_DIR):
        return 0
    limite = time.time() - SESSAO_TTL_MIN * 60
    apagadas = 0
    for nome in os.listdir(SESSIONS_DIR):
        if nome == _OCR_TMP:
            continue
        caminho = os.path.join(SESSIONS_DIR, nome)
        if not os.path.isdir(caminho):
            continue  # arquivo solto ali: nao e sessao, nao mexe
        try:
            if os.path.getmtime(caminho) > limite:
                continue
            shutil.rmtree(caminho, ignore_errors=True)
        except OSError:
            continue  # sumiu no meio do caminho, ou o SO nao deixou: segue
        SESSIONS.pop(nome, None)
        apagadas += 1
    return apagadas


def _session_dir(session_id):
    d = os.path.join(SESSIONS_DIR, session_id)
    os.makedirs(d, exist_ok=True)
    return d


# Papel de cada arquivo enviado, gravado ao lado deles. O SESSIONS vive na
# memoria do processo; os arquivos, no disco. Sem esse mapa nao da pra saber,
# depois de um reinicio, qual .xlsx era o do Escavador e qual era o de
# Clientes - os dois sao so um nome de arquivo qualquer dentro de uploads/.
_META_ARQUIVO = "meta.json"


def _salvar_meta(session_id, papeis):
    caminho = os.path.join(_session_dir(session_id), _META_ARQUIVO)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(papeis, f, ensure_ascii=False)


def _tocar_sessao(session_id):
    """Marca a sessao como viva, pra varredura por TTL nao apagar ela.

    A varredura olha o mtime do diretorio, e durante a REVISAO nada e escrito
    ali: a revisao inteira acontece no navegador, sem falar com o servidor.
    Sem isso, uma revisao longa era apagada pelo upload de OUTRA pessoa - quem
    estava no meio do trabalho perdia tudo por causa de um estranho.

    Nao usa _session_dir de proposito: aquele CRIA o diretorio, e recriar um
    diretorio ja varrido seria ressuscitar uma sessao vazia.
    """
    try:
        os.utime(os.path.join(SESSIONS_DIR, session_id), None)
    except OSError:
        pass  # ja foi apagada, ou o SO nao deixou: nao e motivo pra falhar


def _rehidratar_sessao(session_id):
    """Remonta a sessao a partir dos arquivos que estao no disco.

    Tudo que o SESSIONS guarda e cache - dados ja lidos e caminhos. O que NAO
    da pra reconstruir sao os arquivos enviados, e esses estao no disco. Entao
    reiniciar o processo (deploy, worker novo, queda) nao precisa mais custar
    a revisao de quem estava no meio dela. E e tambem o que permitiria rodar
    com mais de um worker: qualquer um remonta a sessao aberta no outro.

    Devolve None quando nao ha o que remontar - diretorio ja varrido pelo TTL,
    ou hospedagem de disco efemero que reiniciou limpa. Nesse caso quem
    recupera e o navegador (ver o autossalvamento no front-end).
    """
    sdir = os.path.join(SESSIONS_DIR, session_id)
    caminho_meta = os.path.join(sdir, _META_ARQUIVO)
    if not os.path.isfile(caminho_meta):
        return None
    try:
        with open(caminho_meta, encoding="utf-8") as f:
            papeis = json.load(f)
    except (OSError, ValueError):
        return None

    uploads = os.path.join(sdir, "uploads")

    def caminho(papel):
        nome = papeis.get(papel)
        if not nome:
            return None
        p = os.path.join(uploads, nome)
        return p if os.path.isfile(p) else None

    esc_path = caminho("esc")
    cli_path = caminho("cli")
    fin_path = caminho("fin")
    ap_path = caminho("advbox_pessoas")
    apr_path = caminho("advbox_processos")
    if not esc_path and not cli_path:
        return None  # sem nenhuma das duas planilhas principais nao ha sessao

    try:
        sessao = {
            "esc_path": esc_path,
            "esc_filename": papeis.get("esc"),
            "esc_meta": excel_io.read_escavador_occurrences(esc_path) if esc_path else None,
            "cli_path": cli_path,
            "cli_filename": papeis.get("cli"),
            "cli_meta": excel_io.read_clientes_rows(cli_path) if cli_path else None,
            "fin_path": fin_path,
            "fin_filename": papeis.get("fin"),
            "fin_meta": excel_io.read_financeiro_rows(fin_path) if fin_path else None,
            "advbox_pessoas": advbox_io.read_pessoas_pdf(ap_path) if ap_path else None,
            "advbox_processos": advbox_io.read_processos_pdf(apr_path) if apr_path else None,
        }
    except Exception:
        # arquivo truncado por uma queda no meio do upload, por exemplo: melhor
        # pedir reenvio do que seguir com dado pela metade
        return None
    SESSIONS[session_id] = sessao
    return sessao


def _obter_sessao(session_id):
    """A sessao - do cache, ou remontada do disco - ja marcada como viva."""
    sessao = SESSIONS.get(session_id)
    if sessao is None:
        sessao = _rehidratar_sessao(session_id)
    if sessao is not None:
        _tocar_sessao(session_id)
    return sessao


@app.route("/api/ping/<session_id>", methods=["POST"])
def api_ping(session_id):
    """Sinal de vida da aba que esta revisando agora.

    Resolve duas coisas de uma vez:
      1. impede que a varredura por TTL apague uma sessao EM USO - durante a
         revisao o servidor nao recebe nenhuma outra requisicao daquela aba;
      2. em hospedagem que dorme por inatividade (plano gratuito), mantem a
         instancia acordada enquanto alguem trabalha - que e exatamente
         quando dormir custa o trabalho da pessoa.
    """
    return jsonify({"viva": _obter_sessao(session_id) is not None})


@app.route("/")
def index():
    return render_template("app.html")


@app.route("/api/config")
def api_config():
    """Configuracao do servidor que a tela precisa saber.

    Vai por rota, e nao injetada no HTML, pra valer igual nos DOIS pontos de
    entrada: templates/app.html (servido pelo Flask) e frontend/index.html (o
    servidor de desenvolvimento do Vite). Injetar no template faria a tela de
    desenvolvimento ficar sem o valor.
    """
    return jsonify({
        "memoria": rules_store.MEMORIA,
        # o OCR de print de tela usa a API do Windows: numa instancia Linux ele
        # nao existe, e a tela esconde a secao em vez de oferecer algo quebrado
        "ocr": ocr_helper.disponivel(),
    })


@app.route("/api/upload", methods=["POST"])
def api_upload():
    escavador_file = request.files.get("escavador")
    clientes_file = request.files.get("clientes")
    financeiro_file = request.files.get("financeiro")
    advbox_pessoas_file = request.files.get("advbox_pessoas")
    advbox_processos_file = request.files.get("advbox_processos")
    tem_escavador_file = bool(escavador_file and escavador_file.filename)
    tem_clientes_file = bool(clientes_file and clientes_file.filename)
    if not tem_escavador_file and not tem_clientes_file:
        return jsonify({"error": "Envie pelo menos a planilha do Escavador (Processos) ou a de Clientes."}), 400

    # varre o que passou do prazo ANTES de criar a nova - ver
    # _limpar_sessoes_antigas. E o unico gatilho: nao ha agendador.
    _limpar_sessoes_antigas()

    session_id = uuid.uuid4().hex[:12]
    sdir = _session_dir(session_id)
    uploads_dir = os.path.join(sdir, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    esc_path = None
    esc_data = None
    if tem_escavador_file:
        esc_path = os.path.join(uploads_dir, escavador_file.filename)
        escavador_file.save(esc_path)
        try:
            esc_data = excel_io.read_escavador_occurrences(esc_path)
        except Exception as exc:
            return jsonify({"error": f"Erro lendo a planilha do Escavador: {exc}"}), 400

    cli_path = None
    if clientes_file and clientes_file.filename:
        cli_path = os.path.join(uploads_dir, clientes_file.filename)
        clientes_file.save(cli_path)

    cli_data = None
    if cli_path:
        try:
            cli_data = excel_io.read_clientes_rows(cli_path)
        except Exception as exc:
            return jsonify({"error": f"Erro lendo a planilha de Clientes: {exc}"}), 400

    fin_path = None
    fin_data = None
    if financeiro_file and financeiro_file.filename:
        fin_path = os.path.join(uploads_dir, financeiro_file.filename)
        financeiro_file.save(fin_path)
        try:
            fin_data = excel_io.read_financeiro_rows(fin_path)
        except Exception as exc:
            return jsonify({"error": f"Erro lendo a planilha de Financeiro: {exc}"}), 400

    advbox_pessoas_data = None
    if advbox_pessoas_file and advbox_pessoas_file.filename:
        advbox_pessoas_path = os.path.join(uploads_dir, advbox_pessoas_file.filename)
        advbox_pessoas_file.save(advbox_pessoas_path)
        try:
            advbox_pessoas_data = advbox_io.read_pessoas_pdf(advbox_pessoas_path)
        except Exception as exc:
            return jsonify({"error": f"Erro lendo o PDF de pessoas do ADVBOX: {exc}"}), 400

    advbox_processos_data = None
    if advbox_processos_file and advbox_processos_file.filename:
        advbox_processos_path = os.path.join(uploads_dir, advbox_processos_file.filename)
        advbox_processos_file.save(advbox_processos_path)
        try:
            advbox_processos_data = advbox_io.read_processos_pdf(advbox_processos_path)
        except Exception as exc:
            return jsonify({"error": f"Erro lendo o PDF de processos do ADVBOX: {exc}"}), 400

    # o mapa de papeis vai pro disco junto: e o que permite remontar a
    # sessao depois de um reinicio, quando o SESSIONS em memoria ja se foi
    _salvar_meta(session_id, {
        "esc": escavador_file.filename if tem_escavador_file else None,
        "cli": clientes_file.filename if cli_path else None,
        "fin": financeiro_file.filename if fin_path else None,
        "advbox_pessoas": advbox_pessoas_file.filename if advbox_pessoas_data is not None else None,
        "advbox_processos": advbox_processos_file.filename if advbox_processos_data is not None else None,
    })

    SESSIONS[session_id] = {
        "esc_path": esc_path,
        "esc_filename": escavador_file.filename if tem_escavador_file else None,
        "esc_meta": esc_data,
        "cli_path": cli_path,
        "cli_filename": clientes_file.filename if clientes_file else None,
        "cli_meta": cli_data,
        "fin_path": fin_path,
        "fin_filename": financeiro_file.filename if fin_data else None,
        "fin_meta": fin_data,
        "advbox_pessoas": advbox_pessoas_data,
        "advbox_processos": advbox_processos_data,
    }

    return jsonify({
        "session_id": session_id,
        "escavador": ({
            "filename": escavador_file.filename,
            "sheet": esc_data["sheet_name"],
            "n_occurrences": len(esc_data["occurrences"]),
        } if esc_data else None),
        "clientes": ({
            "filename": clientes_file.filename,
            "sheet": cli_data["sheet_name"],
            "n_rows": len(cli_data["rows"]),
            "tem_cpf": cli_data["col_cpf"] is not None,
        } if cli_data else None),
        "financeiro": ({
            "filename": financeiro_file.filename,
            "sheet": fin_data["sheet_name"],
            "n_rows": len(fin_data["rows"]),
        } if fin_data else None),
        "advbox_pessoas": ({
            "filename": advbox_pessoas_file.filename,
            "n_pessoas": len(advbox_pessoas_data),
        } if advbox_pessoas_data is not None else None),
        "advbox_processos": ({
            "filename": advbox_processos_file.filename,
            "n_processos": len(advbox_processos_data),
        } if advbox_processos_data is not None else None),
    })


@app.route("/api/ocr", methods=["POST"])
def api_ocr():
    # a indisponibilidade vem ANTES da validacao da imagem: se o recurso nao
    # existe nesta maquina, pedir a imagem primeiro so faria a pessoa anexar um
    # arquivo pra receber o erro depois
    if not ocr_helper.disponivel():
        return jsonify({"error": "O OCR de print de tela so funciona no Windows. "
                                 "Cole os nomes direto na caixa de texto."}), 400

    image_file = request.files.get("image")
    if not image_file or not image_file.filename:
        return jsonify({"error": "Envie uma imagem."}), 400

    tmp_dir = os.path.join(SESSIONS_DIR, "_ocr_tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex[:8]}_{image_file.filename}")
    image_file.save(tmp_path)

    try:
        names = ocr_helper.extract_candidate_names(tmp_path)
    except Exception as exc:
        return jsonify({"error": f"OCR falhou: {exc}"}), 500
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    return jsonify({"names": names})


def _build_all_occurrences(session):
    esc_meta = session["esc_meta"]
    cli_meta = session["cli_meta"]
    all_occ = list(esc_meta["occurrences"]) if esc_meta else []
    if cli_meta:
        for r in cli_meta["rows"]:
            all_occ.append({
                "text": r["text"],
                "norm": r["norm"],
                "row": r["row"],
                "source": "clientes",
                "cpf_norm": r["cpf_norm"],
                "fields": r.get("fields") or {},
            })
    # Nomes do Financeiro entram no mesmo indice das outras planilhas pra
    # participarem do agrupamento de homonimos (assim "JOSE DA SILVA" no
    # financeiro casa com "JOSE DA SILVA JUNIOR" do cadastro e e padronizado
    # junto). Quem NAO casar com nada de Clientes/Processos sobra pra secao
    # de orfaos - ver matching.find_financeiro_orphans.
    fin_meta = session.get("fin_meta")
    if fin_meta:
        for r in fin_meta["rows"]:
            all_occ.append({
                "text": r["text"],
                "norm": r["norm"],
                "row": r["row"],
                "source": "financeiro",
                "cpf_norm": "",
                "fields": {},
            })

    advbox_pessoas = session.get("advbox_pessoas")
    if advbox_pessoas:
        for p in advbox_pessoas:
            if advbox_io.is_court_reference(p["text"]):
                continue  # contaminacao comum no cadastro (ex: pessoa "14A VARA")
            all_occ.append({
                "text": p["text"],
                "norm": p["norm"],
                "row": None,
                "source": "advbox_pessoas",
                "cpf_norm": p.get("cpf_norm") or "",
                "fields": p.get("fields") or {},
            })
    advbox_processos = session.get("advbox_processos")
    if advbox_processos:
        for proc in advbox_processos:
            for name in proc["cliente_names"]:
                if advbox_io.is_court_reference(name):
                    continue
                all_occ.append({"text": name, "norm": normalize_name(name), "row": None, "source": "advbox_processo_cliente"})
            for name in proc["parte_names"]:
                if advbox_io.is_court_reference(name):
                    continue
                all_occ.append({"text": name, "norm": normalize_name(name), "row": None, "source": "advbox_processo_parte"})
    return all_occ


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    body = request.get_json(force=True)
    session_id = body.get("session_id")
    threshold = float(body.get("threshold", DEFAULT_THRESHOLD))
    responsaveis_text = body.get("responsaveis_text", "") or ""
    tipos_acao_text = body.get("tipos_acao_text", "") or ""
    grupos_acao_text = body.get("grupos_acao_text", "") or ""
    nomes_text = body.get("nomes_text", "") or ""
    session = _obter_sessao(session_id)
    if not session:
        return jsonify({"error": "Sessao nao encontrada. Envie os arquivos de novo."}), 404

    all_occ = _build_all_occurrences(session)
    occ_by_norm = build_occurrence_index(all_occ)
    session["occ_by_norm"] = occ_by_norm

    cpf_by_norm = defaultdict(set)
    for occ in all_occ:
        cpf = occ.get("cpf_norm")
        if cpf:
            cpf_by_norm[occ["norm"]].add(cpf)

    blacklist_pairs, confirmed_pairs = rules_store.load_sets()

    clusters = find_clusters(
        all_occ,
        cpf_by_norm=cpf_by_norm,
        threshold=threshold,
        blacklist_pairs=blacklist_pairs,
        confirmed_pairs=confirmed_pairs,
    )
    session["clusters"] = clusters

    cpf_registry_name_by_cpf = {}
    if session["cli_meta"]:
        for r in session["cli_meta"]["rows"]:
            if r["cpf_norm"]:
                cpf_registry_name_by_cpf.setdefault(r["cpf_norm"], r["text"])

    response_clusters = []
    for idx, c in enumerate(clusters):
        variants = []
        has_advbox = False
        has_financeiro = False
        has_local = False
        for norm in c["members"]:
            occs = occ_by_norm.get(norm, [])
            texts = defaultdict(lambda: {"count_cliente": 0, "count_parte_contraria": 0, "count_clientes": 0, "count_advbox": 0, "count_financeiro": 0, "rows": []})
            for o in occs:
                bucket = texts[o["text"]]
                source = o["source"]
                if source == "escavador":
                    if o.get("column") == "parte_contraria":
                        bucket["count_parte_contraria"] += 1
                    else:
                        bucket["count_cliente"] += 1
                    bucket["rows"].append(o["row"])
                    has_local = True
                elif source == "clientes":
                    bucket["count_clientes"] += 1
                    bucket["rows"].append(o["row"])
                    has_local = True
                elif source == "financeiro":
                    bucket["count_financeiro"] += 1
                    bucket["rows"].append(o["row"])
                    has_financeiro = True
                else:
                    bucket["count_advbox"] += 1
                    has_advbox = True
            for text, info in texts.items():
                variants.append({
                    "text": text,
                    "norm": norm,
                    "count_escavador": info["count_cliente"] + info["count_parte_contraria"],
                    "count_cliente": info["count_cliente"],
                    "count_parte_contraria": info["count_parte_contraria"],
                    "count_clientes": info["count_clientes"],
                    "count_advbox": info["count_advbox"],
                    "count_financeiro": info["count_financeiro"],
                    "rows_financeiro": sorted({o["row"] for o in occs if o.get("text") == text and o.get("source") == "financeiro"}),
                    # separado por COLUNA: o mesmo nome pode estar na linha 1028
                    # como cliente e na 1028 como parte contraria - juntar tudo
                    # em "Processos: linha 1028" fazia dois grupos diferentes
                    # parecerem identicos na tela.
                    "rows_cliente": sorted({o["row"] for o in occs if o.get("text") == text and o.get("source") == "escavador" and o.get("column") != "parte_contraria"}),
                    "rows_parte": sorted({o["row"] for o in occs if o.get("text") == text and o.get("source") == "escavador" and o.get("column") == "parte_contraria"}),
                    "rows_clientes": sorted({o["row"] for o in occs if o.get("text") == text and o.get("source") == "clientes"}),
                })

        if (has_advbox or has_financeiro) and not has_local:
            # cluster sem nenhuma ocorrencia nas planilhas de Processos/Clientes
            # - so nomes do ADVBOX entre si, ou so do Financeiro entre si. Nao ha
            # nome "de referencia" pra padronizar contra, entao nao cabe nesta
            # secao: o do ADVBOX vira sugestao de cadastro (secao ADVBOX) e o do
            # Financeiro vira orfao (secao Financeiro), cada um com sua decisao
            # propria. Listar aqui so poluiria a revisao.
            continue

        variants.sort(key=lambda v: -(v["count_escavador"] + v["count_clientes"]))

        canonical = suggest_canonical(c["members"], occ_by_norm, cpf_registry_name_by_cpf)
        remembered_canonical = None
        members_sorted = c["members"]
        for i in range(len(members_sorted)):
            for j in range(i + 1, len(members_sorted)):
                found = confirmed_pairs.get(frozenset((members_sorted[i], members_sorted[j])))
                if found:
                    remembered_canonical = found
                    break
            if remembered_canonical:
                break
        response_clusters.append({
            "id": idx,
            "score": c["score"],
            "reasons": c["reasons"],
            "cpfs": c["cpfs"],
            "cpf_conflict": c["cpf_conflict"],
            "members": c["members"],
            "variants": variants,
            "suggested_canonical": canonical,
            "remembered_canonical": remembered_canonical,
            "has_advbox": has_advbox,
            "has_financeiro": has_financeiro,
        })

    responsavel_suggestions = _analyze_responsaveis(session, responsaveis_text, threshold)

    tipo_acao_occ = session["esc_meta"].get("tipo_acao_occurrences", []) if session.get("esc_meta") else []
    grupo_acao_occ = session["esc_meta"].get("grupo_acao_occurrences", []) if session.get("esc_meta") else []
    tipo_acao_suggestions = _analyze_acao_field(
        tipo_acao_occ, tipos_acao_text, threshold, rules_store.load_tipo_acao_decisions()
    )
    grupo_acao_suggestions = _analyze_acao_field(
        grupo_acao_occ, grupos_acao_text, threshold, rules_store.load_grupo_acao_decisions()
    )

    def _build_label_clusters(occurrences, kind):
        """Homonimos de TIPO DE ACAO / GRUPO DE ACAO comparados ENTRE SI
        (diferente de _analyze_acao_field, que compara contra a lista colada
        pelo usuario) - ver matching.find_label_clusters pra entender por que
        o limiar e mais alto e por que grupo de 3+ so junta quando e clique de
        verdade."""
        bl, cf = rules_store.load_label_cluster_sets(kind)
        clusters = find_label_clusters(occurrences, blacklist_pairs=bl, confirmed_pairs=cf)
        out = []
        for idx, c in enumerate(clusters):
            out.append({**c, "id": idx})
        return out

    tipo_acao_clusters = _build_label_clusters(tipo_acao_occ, "tipo_acao")
    grupo_acao_clusters = _build_label_clusters(grupo_acao_occ, "grupo_acao")

    # Conferencia de NOMES contra uma lista colada - alternativa ao PDF de
    # pessoas do ADVBOX pra quando so se quer bater os nomes. Compara os
    # nomes que estao na planilha (coluna NOME DO CLIENTE + cadastro de
    # Clientes) com a lista oficial que o usuario colou.
    nome_occ = [
        o for o in all_occ
        if o.get("source") == "clientes"
        or (o.get("source") == "escavador" and o.get("column") == "cliente")
    ]
    nome_validacao_suggestions = _analyze_acao_field(
        nome_occ, nomes_text, threshold, rules_store.load_nome_validacao_decisions(),
        matcher=lambda norm, registry: match_against_registry(norm, registry, threshold=threshold),
    )

    esc_occurrences = session["esc_meta"]["occurrences"] if session.get("esc_meta") else []
    remembered_overlap = rules_store.load_cliente_parte_overlap_decisions()
    cliente_parte_overlap = find_cliente_parte_overlap(esc_occurrences)
    for idx, item in enumerate(cliente_parte_overlap):
        item["id"] = idx
        item["remembered"] = remembered_overlap.get(item["norm"])

    remembered_court_judge = rules_store.load_court_judge_decisions()
    court_judge_items = find_court_or_judge_names(esc_occurrences)
    for idx, item in enumerate(court_judge_items):
        item["id"] = idx
        item["remembered"] = remembered_court_judge.get(item["norm"])

    remembered_advbox_only = rules_store.load_advbox_only_decisions()
    advbox_only = find_advbox_only_candidates(all_occ, clusters)
    for idx, item in enumerate(advbox_only):
        item["id"] = idx
        item["remembered"] = remembered_advbox_only.get(item["norm"])

    remembered_fin_orphans = rules_store.load_financeiro_orphan_decisions()
    financeiro_orphans = find_financeiro_orphans(all_occ, clusters) if session.get("fin_meta") else []
    fin_desc_by_row = {}
    if session.get("fin_meta"):
        fin_desc_by_row = {r["row"]: r["descricao"] for r in session["fin_meta"]["rows"]}
    for idx, item in enumerate(financeiro_orphans):
        item["id"] = idx
        item["remembered"] = remembered_fin_orphans.get(item["norm"])
        # previa do que a DESCRICAO vira se o nome for movido - deixa o efeito
        # explicito na tela em vez de so descrito em texto.
        primeira_linha = item["rows"][0] if item["rows"] else None
        desc_atual = fin_desc_by_row.get(primeira_linha, "") if primeira_linha else ""
        item["descricao_atual"] = desc_atual
        item["descricao_preview"] = f"{item['text']};{desc_atual}" if desc_atual else item["text"]

    remembered_conflicts = rules_store.load_advbox_conflict_decisions()
    advbox_field_conflicts = find_advbox_field_conflicts(occ_by_norm)
    for idx, item in enumerate(advbox_field_conflicts):
        item["id"] = idx
        item["key"] = f"{item['norm']}|{item['field']}"
        item["remembered"] = remembered_conflicts.get(item["key"])

    clientes_duplicates_exact = []
    clientes_duplicates_fuzzy = []
    if session["cli_meta"]:
        clientes_duplicates_exact, clientes_duplicates_fuzzy = find_clientes_duplicates(
            session["cli_meta"]["rows"], threshold=threshold
        )
        for idx, item in enumerate(clientes_duplicates_exact):
            item["id"] = idx
        for idx, item in enumerate(clientes_duplicates_fuzzy):
            item["id"] = idx

    return jsonify({
        "session_id": session_id,
        "threshold": threshold,
        "clusters": response_clusters,
        "stats": {
            "total_clusters": len(response_clusters),
            "cpf_conflicts": sum(1 for c in response_clusters if c["cpf_conflict"]),
        },
        "responsavel_suggestions": responsavel_suggestions,
        "tem_coluna_responsavel": bool(session.get("esc_meta") and session["esc_meta"].get("col_responsavel")),
        "tipo_acao_suggestions": tipo_acao_suggestions,
        "tipo_acao_clusters": tipo_acao_clusters,
        "tem_coluna_tipo_acao": bool(session.get("esc_meta") and session["esc_meta"].get("col_tipo_acao")),
        "grupo_acao_suggestions": grupo_acao_suggestions,
        "grupo_acao_clusters": grupo_acao_clusters,
        "tem_coluna_grupo_acao": bool(session.get("esc_meta") and session["esc_meta"].get("col_grupo_acao")),
        "nome_validacao_suggestions": nome_validacao_suggestions,
        "cliente_parte_overlap": cliente_parte_overlap,
        "tem_coluna_parte_contraria": bool(session.get("esc_meta") and session["esc_meta"].get("col_parte_contraria")),
        "court_judge_items": court_judge_items,
        "advbox_only": advbox_only,
        "advbox_field_conflicts": advbox_field_conflicts,
        "tem_advbox": bool(session.get("advbox_pessoas") or session.get("advbox_processos")),
        "financeiro_orphans": financeiro_orphans,
        "tem_financeiro": bool(session.get("fin_meta")),
        "tem_planilha_clientes": bool(session["cli_meta"]),
        "tem_escavador": bool(session.get("esc_meta")),
        "clientes_duplicates_exact": clientes_duplicates_exact,
        "clientes_duplicates_fuzzy": clientes_duplicates_fuzzy,
    })


def _analyze_responsaveis(session, responsaveis_text, threshold):
    """Compara os valores da coluna RESPONSAVEL (Escavador) contra uma lista
    oficial de nomes (colada pelo usuario ou extraida via OCR de um print).
    So retorna itens que NAO batem exatamente com algum nome oficial."""
    if not session.get("esc_meta") or not session["esc_meta"].get("col_responsavel"):
        return []
    return _analyze_acao_field(
        session["esc_meta"].get("responsavel_occurrences", []),
        responsaveis_text,
        threshold,
        rules_store.load_responsavel_decisions(),
        matcher=lambda norm, registry: match_against_registry(norm, registry, threshold=threshold),
    )


def _analyze_acao_field(occurrences, registry_text, threshold, remembered, matcher=None):
    """Generico pra TIPO DE ACAO / GRUPO DE ACAO: compara os valores da
    coluna (Escavador) contra uma lista oficial da conta ADVBOX colada pelo
    usuario, igual a validacao de Responsaveis, mas essa AQUI lembra a
    decisao entre uma aplicacao e outra (Responsaveis nao lembra, porque a
    lista oficial de usuarios muda pouco e e sempre colada de novo; ja
    aqui a decisao de "esse valor da planilha corresponde a esse valor
    oficial" e o que se quer fixar de vez, ver rules_store.py)."""
    registry = [l.strip() for l in registry_text.splitlines() if l.strip()]
    if not registry:
        return []

    by_norm = defaultdict(lambda: {"text": None, "rows": []})
    for o in occurrences:
        entry = by_norm[o["norm"]]
        entry["text"] = entry["text"] or o["text"]
        entry["rows"].append(o["row"])

    registry_norms = {normalize_name(r) for r in registry}

    suggestions = []
    for norm, info in by_norm.items():
        if norm in registry_norms:
            continue  # ja bate exatamente com um valor oficial
        # `matcher` decide a regra de comparacao: pra TIPO/GRUPO DE ACAO vem
        # o de CATEGORIA (onde "um rotulo conter o outro" significa mesma
        # coisa), pra RESPONSAVEL/NOME vem o de pessoa (onde conter NAO pode
        # virar match) - ver matching.match_category_against_registry.
        match = matcher(norm, registry) if matcher else match_category_against_registry(norm, registry)
        rem = remembered.get(norm)
        suggestions.append({
            "norm": norm,
            "text": info["text"],
            "count": len(info["rows"]),
            "rows": sorted(info["rows"]),
            "suggested_official": match["official_text"] if match else None,
            "score": match["score"] if match else None,
            "reason": match["reason"] if match else None,
            "remembered_action": rem["action"] if rem else None,
            "remembered_canonical": rem["canonical"] if rem else None,
        })

    suggestions.sort(key=lambda s: (s["suggested_official"] is None, -(s["score"] or 0)))
    return suggestions


@app.route("/api/apply", methods=["POST"])
def api_apply():
    body = request.get_json(force=True)
    session_id = body.get("session_id")
    decisions = body.get("decisions", [])
    responsavel_decisions = body.get("responsavel_decisions", [])
    cliente_parte_overlap_decisions_in = body.get("cliente_parte_overlap_decisions", [])
    court_judge_decisions_in = body.get("court_judge_decisions", [])
    advbox_only_decisions_in = body.get("advbox_only_decisions", [])
    advbox_conflict_decisions_in = body.get("advbox_conflict_decisions", [])
    clientes_duplicate_decisions_in = body.get("clientes_duplicate_decisions", [])
    tipo_acao_decisions_in = body.get("tipo_acao_decisions", [])
    grupo_acao_decisions_in = body.get("grupo_acao_decisions", [])
    tipo_acao_cluster_decisions_in = body.get("tipo_acao_cluster_decisions", [])
    grupo_acao_cluster_decisions_in = body.get("grupo_acao_cluster_decisions", [])
    nome_validacao_decisions_in = body.get("nome_validacao_decisions", [])
    financeiro_orphan_decisions_in = body.get("financeiro_orphan_decisions", [])
    dry_run = bool(body.get("dry_run", False))
    # previa nunca grava decisao nenhuma - so quando o usuario confirma de
    # verdade (dry_run=False) e que o "lembrar pra proxima vez" vale.
    persist_rules = bool(body.get("persist_rules", True)) and not dry_run

    session = _obter_sessao(session_id)
    if not session:
        return jsonify({"error": "Sessao nao encontrada. Envie os arquivos de novo."}), 404

    occ_by_norm = session.get("occ_by_norm", {})

    def _display_text(norm):
        occs = occ_by_norm.get(norm) or []
        return occs[0]["text"] if occs else norm

    def _advbox_fields_for_norms(norms):
        """Junta os campos extras (CPF, RG, telefone, endereco...) de todas
        as ocorrencias vindas da conta do ADVBOX (advbox_pessoas) entre os
        norms dados - usado tanto pra nome identico (1 norm so) quanto pra
        grupo de homonimos confirmado (varios norms)."""
        fields = {}
        for norm in norms:
            for occ in occ_by_norm.get(norm, []):
                if occ.get("source") == "advbox_pessoas":
                    for k, v in (occ.get("fields") or {}).items():
                        if v and k not in fields:
                            fields[k] = v
        return fields

    resp_text_by_norm = {}
    tipo_acao_text_by_norm = {}
    grupo_acao_text_by_norm = {}
    if session.get("esc_meta"):
        for o in session["esc_meta"].get("responsavel_occurrences", []):
            resp_text_by_norm.setdefault(o["norm"], o["text"])
        for o in session["esc_meta"].get("tipo_acao_occurrences", []):
            tipo_acao_text_by_norm.setdefault(o["norm"], o["text"])
        for o in session["esc_meta"].get("grupo_acao_occurrences", []):
            grupo_acao_text_by_norm.setdefault(o["norm"], o["text"])

    _nome_text_by_norm = {norm: (occs[0]["text"] if occs else norm)
                          for norm, occs in occ_by_norm.items()}

    mapping = {}
    merged_groups = []

    for d in decisions:
        action = d.get("action")
        members = d.get("members", [])
        excluded_members = d.get("excluded_members", [])
        canonical = (d.get("canonical") or "").strip()
        if action == "merge" and canonical:
            for norm in members:
                mapping[norm] = canonical
            merged_groups.append({
                "canonical": canonical,
                "variants": [_display_text(n) for n in members],
                "excluded": [_display_text(n) for n in excluded_members],
            })
            # So vira regra guardada ("confirmado antes") o grupo em que o
            # usuario REALMENTE mexeu. Sem esse filtro, todo grupo que ele
            # apenas deixou passar era gravado como confirmado e voltava
            # marcado assim pra sempre - uma decisao que ele nunca tomou.
            if persist_rules and d.get("touched"):
                rules_store.add_confirmed_group(members, canonical)
                # nomes marcados como "nao faz parte deste grupo" - lembra que
                # esse par especifico nao deve ser sugerido junto de novo.
                for excluded_norm in excluded_members:
                    for kept_norm in members:
                        rules_store.add_blacklist_pair(excluded_norm, kept_norm)
        elif action == "ignore" and persist_rules and d.get("touched"):
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    rules_store.add_blacklist_pair(members[i], members[j])

    def _apply_label_cluster_decisions(decisions_in, mapping_out, items_by_norm, text_by_norm, kind):
        """Mesma logica do loop de cima (merge/ignore/excluded_members), so
        que gravando no namespace proprio de TIPO/GRUPO DE ACAO - ver
        rules_store.add_label_cluster_confirmed_group. `items_by_norm`
        (dict norm->item) em vez de lista, pra depois ser facil saber - sem
        depender de ordem de iteracao - quais norms ja tiveram esse merge
        substituido pela validacao contra a lista oficial (mais abaixo)."""
        for d in decisions_in:
            action = d.get("action")
            members = d.get("members", [])
            excluded_members = d.get("excluded_members", [])
            canonical = (d.get("canonical") or "").strip()
            if action == "merge" and canonical:
                for norm in members:
                    mapping_out[norm] = canonical
                    items_by_norm[norm] = {"text": text_by_norm.get(norm, norm), "canonical": canonical}
                if persist_rules and d.get("touched"):
                    rules_store.add_label_cluster_confirmed_group(kind, members, canonical)
                    for excluded_norm in excluded_members:
                        for kept_norm in members:
                            rules_store.add_label_cluster_blacklist_pair(kind, excluded_norm, kept_norm)
            elif action == "ignore" and persist_rules and d.get("touched"):
                for i in range(len(members)):
                    for j in range(i + 1, len(members)):
                        rules_store.add_label_cluster_blacklist_pair(kind, members[i], members[j])

    # os homonimos DENTRO da planilha (find_label_clusters) sao aplicados
    # ANTES da validacao contra a lista colada (tipo_acao_mapping/
    # grupo_acao_mapping mais abaixo) - se o mesmo rotulo tiver as duas
    # decisoes, a validacao contra a lista oficial e mais especifica e deve
    # vencer, por isso ela sobrescreve por cima logo em seguida.
    tipo_acao_cluster_mapping = {}
    grupo_acao_cluster_mapping = {}
    tipo_acao_cluster_items_by_norm = {}
    grupo_acao_cluster_items_by_norm = {}
    _apply_label_cluster_decisions(
        tipo_acao_cluster_decisions_in, tipo_acao_cluster_mapping, tipo_acao_cluster_items_by_norm,
        tipo_acao_text_by_norm, "tipo_acao",
    )
    _apply_label_cluster_decisions(
        grupo_acao_cluster_decisions_in, grupo_acao_cluster_mapping, grupo_acao_cluster_items_by_norm,
        grupo_acao_text_by_norm, "grupo_acao",
    )

    # Enriquecimento da planilha de Clientes com dados da conta do ADVBOX
    # pro MESMO cliente - nunca mexe no ADVBOX, so preenche campo vazio
    # aqui. Dois casos: (a) nome identico dos dois lados (mesma norma, sem
    # ambiguidade nenhuma) e (b) grupo de homonimos que o usuario confirmou
    # ser a mesma pessoa (decisao de fusao acima) misturando clientes +
    # advbox_pessoas.
    field_updates = {}
    for norm, occs in occ_by_norm.items():
        sources = {o.get("source") for o in occs}
        if "clientes" in sources and "advbox_pessoas" in sources:
            fields = _advbox_fields_for_norms([norm])
            if fields:
                field_updates[norm] = fields

    for d in decisions:
        if d.get("action") != "merge":
            continue
        members = d.get("members", [])
        clientes_members = [n for n in members if any(o.get("source") == "clientes" for o in occ_by_norm.get(n, []))]
        has_advbox = any(o.get("source") == "advbox_pessoas" for n in members for o in occ_by_norm.get(n, []))
        if not clientes_members or not has_advbox:
            continue
        fields = _advbox_fields_for_norms(members)
        if not fields:
            continue
        for cliente_norm in clientes_members:
            existing = field_updates.setdefault(cliente_norm, {})
            for k, v in fields.items():
                existing.setdefault(k, v)

    def _build_acao_mapping(decisions_in, text_by_norm, save_decision):
        """Monta o mapa norm->valor final pras validacoes de coluna contra
        lista oficial (RESPONSAVEL, TIPO/GRUPO DE ACAO, NOME) e, quando o
        usuario pediu pra lembrar, persiste a decisao (inclusive o 'manter',
        pra nao voltar a perguntar sobre um valor que ele ja disse que esta
        certo do jeito que esta). So entra no mapa o que foi marcado
        explicitamente como 'aplicar' - o resto nao encosta na planilha."""
        mapping_out = {}
        items_out = []
        for d in decisions_in:
            norm = d.get("norm")
            action = d.get("action")
            # "apply" e o nome antigo do mesmo estado, aceito pra nao quebrar
            # uma tela que ainda nao tenha recarregado.
            if action == "apply":
                action = "aplicar"
            canonical = (d.get("canonical") or "").strip()
            if not norm:
                continue
            if action == "aplicar" and canonical:
                mapping_out[norm] = canonical
                items_out.append({"text": text_by_norm.get(norm, norm), "canonical": canonical})
            # So guarda o que o usuario REALMENTE decidiu (mexeu no item).
            # Sem esse filtro, todo item que ele simplesmente ignorou seria
            # salvo como "manter" e voltaria marcado como "decisao lembrada"
            # na proxima planilha - uma decisao que ele nunca tomou.
            if persist_rules and d.get("touched") and action in ("aplicar", "manter"):
                save_decision(norm, action, canonical if action == "aplicar" else None)
        return mapping_out, items_out

    responsavel_mapping, responsavel_items = _build_acao_mapping(
        responsavel_decisions, resp_text_by_norm, rules_store.save_responsavel_decision
    )
    tipo_acao_mapping, tipo_acao_items = _build_acao_mapping(
        tipo_acao_decisions_in, tipo_acao_text_by_norm, rules_store.save_tipo_acao_decision
    )
    grupo_acao_mapping, grupo_acao_items = _build_acao_mapping(
        grupo_acao_decisions_in, grupo_acao_text_by_norm, rules_store.save_grupo_acao_decision
    )
    # homonimo dentro da planilha primeiro, validacao contra a lista oficial
    # por cima - ver comentario acima de _apply_label_cluster_decisions.
    tipo_acao_mapping = {**tipo_acao_cluster_mapping, **tipo_acao_mapping}
    grupo_acao_mapping = {**grupo_acao_cluster_mapping, **grupo_acao_mapping}
    # itens que so vieram do homonimo (nao tiveram tambem decisao contra a
    # lista oficial pra esse MESMO norm) entram no resumo tambem - senao a
    # fusao acontece na planilha mas nao aparece no texto que vai pro cliente.
    # Depois do merge acima, `tipo_acao_mapping[norm]` so continua igual ao
    # valor do cluster quando a lista oficial NAO decidiu nada pra esse norm
    # (senao o valor da lista, mais especifico, ja tomou o lugar) - por isso
    # da pra usar essa igualdade como o filtro de "ainda nao apareceu".
    tipo_acao_items = tipo_acao_items + [
        item for norm, item in tipo_acao_cluster_items_by_norm.items()
        if tipo_acao_mapping.get(norm) == tipo_acao_cluster_mapping.get(norm)
    ]
    grupo_acao_items = grupo_acao_items + [
        item for norm, item in grupo_acao_cluster_items_by_norm.items()
        if grupo_acao_mapping.get(norm) == grupo_acao_cluster_mapping.get(norm)
    ]

    # Conferencia de nomes contra lista colada: o valor final escolhido entra
    # no MESMO mapa dos homonimos (`mapping`), que e o que renomeia a coluna
    # NOME DO CLIENTE e o cadastro de Clientes.
    nome_validacao_mapping, nome_validacao_items = _build_acao_mapping(
        nome_validacao_decisions_in, _nome_text_by_norm, rules_store.save_nome_validacao_decision
    )
    # Precedencia: quando o usuario marcou "Aplicar" aqui, ele escolheu um
    # valor DA LISTA OFICIAL pra esse nome - isso vale mais do que o nome
    # canonico que o agrupamento de homonimos tinha sugerido sozinho, entao
    # sobrescreve. (Se ele deixou "Nao alterar", nada entra nesse mapa e o
    # agrupamento segue mandando.)
    mapping.update(nome_validacao_mapping)

    remove_from_cliente_norms = set()
    remove_from_parte_norms = set()
    cliente_parte_items = []
    for d in cliente_parte_overlap_decisions_in:
        norm = d.get("norm")
        action = d.get("action")
        if action == "only_parte" and norm:
            remove_from_cliente_norms.add(norm)
            cliente_parte_items.append({"text": _display_text(norm), "action": action})
        elif action == "only_cliente" and norm:
            remove_from_parte_norms.add(norm)
            cliente_parte_items.append({"text": _display_text(norm), "action": action})
        if persist_rules and d.get("touched") and norm and action in ("only_parte", "only_cliente", "skip"):
            rules_store.save_cliente_parte_overlap_decision(norm, action)

    court_judge_items = []
    for d in court_judge_decisions_in:
        norm = d.get("norm")
        action = d.get("action")
        if action == "remove" and norm:
            # nome de tribunal/vara/comarca/juiz nao e cliente nem parte de
            # verdade em nenhuma das duas colunas - remove dos dois lados.
            remove_from_cliente_norms.add(norm)
            remove_from_parte_norms.add(norm)
            court_judge_items.append({"text": _display_text(norm)})
        if persist_rules and d.get("touched") and norm and action in ("remove", "skip"):
            rules_store.save_court_judge_decision(norm, action)

    extra_clientes_rows = []
    advbox_added_items = []
    for d in advbox_only_decisions_in:
        norm = d.get("norm")
        action = d.get("action")
        if action == "adicionar" and norm:
            text = _display_text(norm)
            extra_clientes_rows.append({"nome": text, "fields": _advbox_fields_for_norms([norm])})
            advbox_added_items.append({"text": text})
        if persist_rules and norm and action in ("adicionar", "ignorar"):
            rules_store.save_advbox_only_decision(norm, action)

    field_overrides = {}
    for d in advbox_conflict_decisions_in:
        key = d.get("key")
        action = d.get("action")
        if not key or "|" not in key:
            continue
        norm, field = key.split("|", 1)
        if action == "usar_advbox":
            advbox_value = d.get("advbox_value")
            if advbox_value:
                field_overrides.setdefault(norm, {})[field] = advbox_value
        if persist_rules and action in ("usar_advbox", "manter"):
            rules_store.save_advbox_conflict_decision(key, action)

    move_to_descricao_norms = set()
    financeiro_moved_items = []
    for d in financeiro_orphan_decisions_in:
        norm = d.get("norm")
        action = d.get("action")
        if action == "mover" and norm:
            move_to_descricao_norms.add(norm)
            financeiro_moved_items.append({"text": _display_text(norm)})
        if persist_rules and d.get("touched") and norm and action in ("mover", "manter"):
            rules_store.save_financeiro_orphan_decision(norm, action)

    rows_to_delete = set()
    clientes_duplicates_removed = []
    # Quem sai e quem fica, POR GRUPO. A linha removida costuma ser o unico
    # lugar onde existe um telefone ou um RG; antes disso ela era apagada e
    # levava esse dado junto, em silencio. Ver fundir_linhas_duplicadas.
    por_grupo = defaultdict(lambda: {"sai": [], "fica": []})
    for d in clientes_duplicate_decisions_in:
        row = d.get("row")
        if not row:
            continue
        chave = d.get("grupo") or ("linha-%s" % row)
        lado = "sai" if d.get("action") == "remover" else "fica"
        por_grupo[chave][lado].append(row)
    merge_rows = {}
    for info in por_grupo.values():
        if not info["sai"] or not info["fica"]:
            continue  # grupo inteiro removido, ou nenhum: nao ha destino
        destino = min(info["fica"])
        for row in info["sai"]:
            merge_rows[row] = destino

    for d in clientes_duplicate_decisions_in:
        row = d.get("row")
        action = d.get("action")
        if action == "remover" and row:
            rows_to_delete.add(row)
            clientes_duplicates_removed.append({"text": d.get("text") or f"linha {row}"})

    out_dir = os.path.join(_session_dir(session_id), "outputs")
    os.makedirs(out_dir, exist_ok=True)

    result = {}

    esc_changes = []
    if session.get("esc_meta"):
        esc_meta = session["esc_meta"]
        esc_out_path = excel_io.make_output_path(session["esc_filename"], out_dir)
        esc_changes = excel_io.apply_escavador(
            session["esc_path"], esc_meta, mapping, esc_out_path,
            responsavel_mapping=responsavel_mapping,
            tipo_acao_mapping=tipo_acao_mapping,
            grupo_acao_mapping=grupo_acao_mapping,
            remove_from_cliente_norms=remove_from_cliente_norms,
            remove_from_parte_norms=remove_from_parte_norms,
            dry_run=dry_run,
        )
        result["escavador"] = {
            "filename": os.path.basename(esc_out_path),
            "n_changes": len(esc_changes),
            "changes": esc_changes,
        }

    n_changes_clientes = None
    if session["cli_meta"]:
        cli_meta = session["cli_meta"]
        cli_out_path = excel_io.make_output_path(session["cli_filename"], out_dir)
        cli_changes = excel_io.apply_clientes(
            session["cli_path"], cli_meta, mapping, cli_out_path,
            rows_to_delete=rows_to_delete,
            merge_rows=merge_rows,
            extra_rows=extra_clientes_rows,
            field_updates=field_updates,
            field_overrides=field_overrides,
            dry_run=dry_run,
        )
        n_changes_clientes = len(cli_changes)
        result["clientes"] = {
            "filename": os.path.basename(cli_out_path),
            "n_changes": len(cli_changes),
            "changes": cli_changes,
        }
    else:
        advbox_added_items = []  # sem planilha de clientes nao ha onde adicionar

    n_changes_financeiro = None
    if session.get("fin_meta"):
        fin_meta = session["fin_meta"]
        fin_out_path = excel_io.make_output_path(session["fin_filename"], out_dir)
        fin_changes = excel_io.apply_financeiro(
            session["fin_path"], fin_meta, mapping, fin_out_path,
            move_to_descricao_norms=move_to_descricao_norms,
            dry_run=dry_run,
        )
        n_changes_financeiro = len(fin_changes)
        result["financeiro"] = {
            "filename": os.path.basename(fin_out_path),
            "n_changes": len(fin_changes),
            "changes": fin_changes,
        }
    else:
        financeiro_moved_items = []  # sem planilha de financeiro nao ha o que mover

    advbox_enriched_items = [
        {"text": _display_text(norm), "campos": sorted(fields.keys())}
        for norm, fields in field_updates.items()
    ] if session["cli_meta"] else []

    summary_text = report.build_summary_text(
        session.get("esc_filename") or session.get("cli_filename") or "planilha",
        merged_groups,
        cliente_parte_items,
        court_judge_items,
        responsavel_items,
        len(esc_changes) if session.get("esc_meta") else None,
        n_changes_clientes,
        advbox_added_items,
        advbox_enriched_items,
        clientes_duplicates_removed,
        tipo_acao_items,
        grupo_acao_items,
        nome_validacao_items,
        financeiro_moved_items,
        n_changes_financeiro,
    )
    if not dry_run:
        summary_path = os.path.join(out_dir, "resumo_padronizacao.txt")
        with open(summary_path, "w", encoding="utf-8", newline="") as f:
            f.write(summary_text)
        result["resumo"] = {"filename": os.path.basename(summary_path)}
        session["out_dir"] = out_dir

    return jsonify({"session_id": session_id, "result": result, "summary_text": summary_text, "dry_run": dry_run})


@app.route("/api/download/<session_id>/<kind>")
def api_download(session_id, kind):
    session = _obter_sessao(session_id)
    if not session or "out_dir" not in session:
        abort(404)
    if kind == "escavador" and session.get("esc_meta"):
        path = excel_io.make_output_path(session["esc_filename"], session["out_dir"])
    elif kind == "clientes" and session["cli_meta"]:
        path = excel_io.make_output_path(session["cli_filename"], session["out_dir"])
    elif kind == "financeiro" and session.get("fin_meta"):
        path = excel_io.make_output_path(session["fin_filename"], session["out_dir"])
    elif kind == "resumo":
        path = os.path.join(session["out_dir"], "resumo_padronizacao.txt")
    else:
        abort(404)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True)


if __name__ == "__main__":
    import webbrowser
    import threading

    # Porta e host podem ser trocados por variavel de ambiente (ver .env.example).
    # Padrao: 127.0.0.1:5057, igual ao comportamento original.
    port = int(os.environ.get("PADRONIZADOR_PORT", "5057"))
    host = os.environ.get("PADRONIZADOR_HOST", "127.0.0.1")
    url = f"http://127.0.0.1:{port}"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=False)
