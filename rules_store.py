"""
Persistencia simples (arquivo JSON local) das decisoes que o usuario ja tomou,
pra nao perguntar de novo da proxima vez que a mesma planilha (ou uma parecida)
for reprocessada.

IMPORTANTE: essa memoria vem DESLIGADA por padrao - ver MEMORIA abaixo. Com ela
desligada, todas as funcoes deste modulo continuam existindo e podem ser
chamadas normalmente, mas as de leitura devolvem vazio e as de escrita nao
fazem nada. O app funciona igual; so nao lembra de nada entre sessoes.

As gavetas:
  - "blacklist": pares de nomes que o usuario disse que NAO sao a mesma pessoa.
  - "confirmed": pares que o usuario confirmou como sendo a mesma pessoa, com o
    nome canonico escolhido.
  - "cliente_as_parte": decisoes da secao "Cliente e Parte Contraria ao mesmo
    tempo" (manter so em parte contraria / so em cliente / nao alterar).
"""
import json
import os
import threading

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
STORE_PATH = os.path.join(DATA_DIR, "decisions.json")

# Memoria de decisoes entre planilhas. DESLIGADA por padrao.
#
# Desligada, o app nao le nem grava decisao nenhuma: cada planilha e revisada
# do zero e nada do que o usuario decidiu sobrevive ao fim da sessao. O arquivo
# decisions.json nem chega a ser criado.
#
# Esse e o padrao porque o arquivo e UNICO e GLOBAL - nao ha separacao por
# usuario nem por conta. Numa instalacao usada por mais de uma pessoa, ou com
# planilhas de mais de um escritorio, com a memoria ligada as decisoes e os
# nomes de clientes de um apareceriam como sugestao no do outro.
#
# So ligue (PADRONIZADOR_MEMORIA=1) numa instalacao de uso pessoal, na sua
# propria maquina, com os dados de um unico escritorio.
#
# A trava fica aqui de proposito, e nao no cliente: todas as 16 gavetas passam
# por load_raw/save_raw, entao com a memoria desligada nem um pedido vindo de
# um front-end antigo (mandando persist_rules=true) consegue gravar.
MEMORIA = os.environ.get("PADRONIZADOR_MEMORIA", "0").strip().lower() in (
    "1", "true", "sim", "yes", "on",
)

_lock = threading.Lock()


def _empty_store():
    return {"blacklist": [], "confirmed": [], "cliente_as_parte": [], "court_judge": [], "nome_limpeza": [],
            "advbox_only": [], "advbox_conflicts": [], "tipo_acao": [], "grupo_acao": [],
            "responsavel": [], "nome_validacao": [], "financeiro_orphan": [],
            "tipo_acao_cluster_blacklist": [], "tipo_acao_cluster_confirmed": [],
            "grupo_acao_cluster_blacklist": [], "grupo_acao_cluster_confirmed": []}


def load_raw():
    if not MEMORIA or not os.path.exists(STORE_PATH):
        return _empty_store()
    with open(STORE_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return _empty_store()
    data.setdefault("blacklist", [])
    data.setdefault("confirmed", [])
    data.setdefault("cliente_as_parte", [])
    data.setdefault("court_judge", [])
    data.setdefault("nome_limpeza", [])
    data.setdefault("advbox_only", [])
    data.setdefault("advbox_conflicts", [])
    data.setdefault("tipo_acao", [])
    data.setdefault("grupo_acao", [])
    data.setdefault("responsavel", [])
    data.setdefault("nome_validacao", [])
    data.setdefault("financeiro_orphan", [])
    data.setdefault("tipo_acao_cluster_blacklist", [])
    data.setdefault("tipo_acao_cluster_confirmed", [])
    data.setdefault("grupo_acao_cluster_blacklist", [])
    data.setdefault("grupo_acao_cluster_confirmed", [])
    return data


def save_raw(data):
    if not MEMORIA:
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_sets():
    """Retorna (blacklist_pairs: set[frozenset], confirmed_pairs: dict[frozenset, str])."""
    data = load_raw()
    blacklist = {frozenset((p[0], p[1])) for p in data["blacklist"]}
    confirmed = {}
    for entry in data["confirmed"]:
        a, b, canonical = entry[0], entry[1], entry[2]
        confirmed[frozenset((a, b))] = canonical
    return blacklist, confirmed


def add_blacklist_pair(norm_a, norm_b):
    with _lock:
        data = load_raw()
        pair = sorted([norm_a, norm_b])
        if pair not in data["blacklist"]:
            data["blacklist"].append(pair)
        data["confirmed"] = [
            e for e in data["confirmed"] if sorted([e[0], e[1]]) != pair
        ]
        save_raw(data)


def add_confirmed_pair(norm_a, norm_b, canonical):
    with _lock:
        data = load_raw()
        pair = sorted([norm_a, norm_b])
        data["confirmed"] = [
            e for e in data["confirmed"] if sorted([e[0], e[1]]) != pair
        ]
        data["confirmed"].append([pair[0], pair[1], canonical])
        data["blacklist"] = [b for b in data["blacklist"] if b != pair]
        save_raw(data)


def add_confirmed_group(norm_members, canonical):
    """Marca todo par dentro de um grupo de nomes como confirmado com o mesmo
    canonico. Se o par JA estava confirmado antes (decisao lembrada) mas o
    usuario escolheu um nome final diferente agora, o canonico e ATUALIZADO -
    antes o par existente era ignorado e a nova escolha se perdia, fazendo a
    tela continuar sugerindo o nome antigo pra sempre."""
    with _lock:
        data = load_raw()
        members = sorted(set(norm_members))
        pair_keys = {tuple(sorted([members[i], members[j]]))
                     for i in range(len(members)) for j in range(i + 1, len(members))}
        # tira as versoes antigas desses pares e regrava com o canonico atual
        data["confirmed"] = [
            e for e in data["confirmed"] if tuple(sorted([e[0], e[1]])) not in pair_keys
        ]
        for pair in sorted(pair_keys):
            data["confirmed"].append([pair[0], pair[1], canonical])
        pair_set = {frozenset((members[i], members[j]))
                    for i in range(len(members)) for j in range(i + 1, len(members))}
        data["blacklist"] = [
            b for b in data["blacklist"] if frozenset((b[0], b[1])) not in pair_set
        ]
        save_raw(data)


def load_cliente_parte_overlap_decisions():
    """dict norm -> action ('only_parte'|'only_cliente'|'skip') lembrado de uma
    aplicacao anterior (secao 'Cliente e Parte Contraria ao mesmo tempo')."""
    data = load_raw()
    return {e["norm"]: e["action"] for e in data["cliente_as_parte"]}


def save_cliente_parte_overlap_decision(norm, action):
    with _lock:
        data = load_raw()
        data["cliente_as_parte"] = [e for e in data["cliente_as_parte"] if e["norm"] != norm]
        data["cliente_as_parte"].append({"norm": norm, "action": action})
        save_raw(data)


def load_court_judge_decisions():
    """dict norm -> action ('remove'|'skip') lembrado de uma aplicacao anterior
    (secao 'Tribunais/Varas/Comarcas/Juizes')."""
    data = load_raw()
    return {e["norm"]: e["action"] for e in data["court_judge"]}


def save_court_judge_decision(norm, action):
    with _lock:
        data = load_raw()
        data["court_judge"] = [e for e in data["court_judge"] if e["norm"] != norm]
        data["court_judge"].append({"norm": norm, "action": action})
        save_raw(data)


def load_advbox_only_decisions():
    """dict norm -> action ('adicionar'|'ignorar') lembrado de uma aplicacao
    anterior (secao 'so existe no ADVBOX')."""
    data = load_raw()
    return {e["norm"]: e["action"] for e in data["advbox_only"]}


def save_advbox_only_decision(norm, action):
    with _lock:
        data = load_raw()
        data["advbox_only"] = [e for e in data["advbox_only"] if e["norm"] != norm]
        data["advbox_only"].append({"norm": norm, "action": action})
        save_raw(data)


def load_advbox_conflict_decisions():
    """dict chave ('{norm}|{campo}') -> action ('usar_advbox'|'manter')
    lembrado de uma aplicacao anterior (conflitos de campo com o ADVBOX)."""
    data = load_raw()
    return {e["key"]: e["action"] for e in data["advbox_conflicts"]}


def save_advbox_conflict_decision(key, action):
    with _lock:
        data = load_raw()
        data["advbox_conflicts"] = [e for e in data["advbox_conflicts"] if e["key"] != key]
        data["advbox_conflicts"].append({"key": key, "action": action})
        save_raw(data)


def _load_field_decisions(bucket):
    """dict norm -> {"action": "aplicar"|"manter", "canonical": str|None}
    lembrado de uma aplicacao anterior. Usado por todas as validacoes de
    coluna contra uma lista oficial (RESPONSAVEL, TIPO DE ACAO, GRUPO DE
    ACAO, NOME DO CLIENTE) - todas guardam a decisao do mesmo jeito."""
    data = load_raw()
    return {e["norm"]: {"action": e["action"], "canonical": e.get("canonical")} for e in data[bucket]}


def _save_field_decision(bucket, norm, action, canonical=None):
    with _lock:
        data = load_raw()
        data[bucket] = [e for e in data[bucket] if e["norm"] != norm]
        data[bucket].append({"norm": norm, "action": action, "canonical": canonical})
        save_raw(data)


def load_tipo_acao_decisions():
    return _load_field_decisions("tipo_acao")


def save_tipo_acao_decision(norm, action, canonical=None):
    _save_field_decision("tipo_acao", norm, action, canonical)


def load_grupo_acao_decisions():
    return _load_field_decisions("grupo_acao")


def save_grupo_acao_decision(norm, action, canonical=None):
    _save_field_decision("grupo_acao", norm, action, canonical)


def load_responsavel_decisions():
    return _load_field_decisions("responsavel")


def save_responsavel_decision(norm, action, canonical=None):
    _save_field_decision("responsavel", norm, action, canonical)


def load_financeiro_orphan_decisions():
    """dict norm -> action ('mover'|'manter') lembrado de uma aplicacao
    anterior (secao 'Financeiro sem cadastro')."""
    data = load_raw()
    return {e["norm"]: e["action"] for e in data["financeiro_orphan"]}


def save_financeiro_orphan_decision(norm, action):
    with _lock:
        data = load_raw()
        data["financeiro_orphan"] = [e for e in data["financeiro_orphan"] if e["norm"] != norm]
        data["financeiro_orphan"].append({"norm": norm, "action": action})
        save_raw(data)


def load_nome_validacao_decisions():
    return _load_field_decisions("nome_validacao")


def save_nome_validacao_decision(norm, action, canonical=None):
    _save_field_decision("nome_validacao", norm, action, canonical)


def load_nome_limpeza_decisions():
    """dict norm -> action ('limpar'|'skip') lembrado de uma aplicacao anterior
    (secao 'Nomes com lixo colado')."""
    data = load_raw()
    return {e["norm"]: e["action"] for e in data["nome_limpeza"]}


def save_nome_limpeza_decision(norm, action):
    with _lock:
        data = load_raw()
        data["nome_limpeza"] = [e for e in data["nome_limpeza"] if e["norm"] != norm]
        data["nome_limpeza"].append({"norm": norm, "action": action})
        save_raw(data)


def _label_cluster_bucket_names(kind):
    if kind not in ("tipo_acao", "grupo_acao"):
        raise ValueError(f"kind invalido para homonimos de categoria: {kind!r}")
    return f"{kind}_cluster_blacklist", f"{kind}_cluster_confirmed"


def load_label_cluster_sets(kind):
    """Retorna (blacklist_pairs: set[frozenset], confirmed_pairs: dict[frozenset,
    str]) para homonimos de TIPO DE ACAO ou GRUPO DE ACAO (kind = 'tipo_acao' |
    'grupo_acao'). Namespace proprio por campo - de proposito: confirmar que
    'COBRANCA' e 'ACAO DE COBRANCA' sao a mesma coisa em TIPO DE ACAO nao pode
    virar regra tambem pra GRUPO DE ACAO, sao vocabularios diferentes."""
    bl_key, cf_key = _label_cluster_bucket_names(kind)
    data = load_raw()
    blacklist = {frozenset((p[0], p[1])) for p in data[bl_key]}
    confirmed = {}
    for entry in data[cf_key]:
        a, b, canonical = entry
        confirmed[frozenset((a, b))] = canonical
    return blacklist, confirmed


def add_label_cluster_blacklist_pair(kind, norm_a, norm_b):
    bl_key, cf_key = _label_cluster_bucket_names(kind)
    with _lock:
        data = load_raw()
        pair = sorted([norm_a, norm_b])
        if pair not in data[bl_key]:
            data[bl_key].append(pair)
        data[cf_key] = [e for e in data[cf_key] if sorted([e[0], e[1]]) != pair]
        save_raw(data)


def add_label_cluster_confirmed_group(kind, norm_members, canonical):
    """Mesma logica de add_confirmed_group, num namespace proprio por campo."""
    bl_key, cf_key = _label_cluster_bucket_names(kind)
    with _lock:
        data = load_raw()
        members = sorted(set(norm_members))
        pair_keys = {tuple(sorted([members[i], members[j]]))
                     for i in range(len(members)) for j in range(i + 1, len(members))}
        data[cf_key] = [
            e for e in data[cf_key] if tuple(sorted([e[0], e[1]])) not in pair_keys
        ]
        for pair in sorted(pair_keys):
            data[cf_key].append([pair[0], pair[1], canonical])
        pair_set = {frozenset((members[i], members[j]))
                    for i in range(len(members)) for j in range(i + 1, len(members))}
        data[bl_key] = [
            b for b in data[bl_key] if frozenset((b[0], b[1])) not in pair_set
        ]
        save_raw(data)
