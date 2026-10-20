"""
Leitura e escrita das planilhas (Escavador / Processos e Clientes).

Autodetecta a aba e as colunas relevantes pelo texto do cabecalho (tolerando
acento/caixa), para funcionar mesmo se o layout mudar um pouco entre planilhas
de escritorios diferentes.
"""
import datetime
import os
import re

import openpyxl

from matching import is_junk_name, normalize_cpf, normalize_name, split_names

NOME_CLIENTE_HEADER_CANDIDATES = ["NOME DO CLIENTE", "NOME CLIENTE", "CLIENTE"]
NOME_HEADER_CANDIDATES = ["NOME"]
CPF_HEADER_CANDIDATES = ["CPF CNPJ", "CPF/CNPJ", "CPF", "CNPJ"]
RESPONSAVEL_HEADER_CANDIDATES = ["RESPONSAVEL", "RESPONSAVEL PELO PROCESSO"]
PARTE_CONTRARIA_HEADER_CANDIDATES = ["PARTE CONTRARIA"]
TIPO_ACAO_HEADER_CANDIDATES = ["TIPO DE ACAO", "TIPO DE AÇÃO"]
GRUPO_ACAO_HEADER_CANDIDATES = ["GRUPO DE ACAO", "GRUPO DE AÇÃO"]
DESCRICAO_HEADER_CANDIDATES = ["DESCRICAO", "DESCRIÇÃO"]
VALOR_HEADER_CANDIDATES = ["VALOR"]
NAO_INFORMADO = "NÃO INFORMADO"

# Formatacao das colunas no arquivo gerado. A planilha vai ser reimportada
# (Sheets/ADVBOX) e, sem formato explicito, o importador "adivinha" o tipo e
# estraga dado que so parece numero: CPF/CNPJ "12.345.678/0001-99", CEP
# "01234-567" e datas "01/10/2025" viram numero/data e perdem zeros a
# esquerda ou mudam de ordem. Entao TODA coluna vira TEXTO SIMPLES ('@'),
# menos as de valor monetario, que precisam continuar somaveis e ficam em
# AUTOMATICO ('General').
FORMAT_TEXTO_SIMPLES = "@"
FORMAT_AUTOMATICO = "General"

# Colunas extras da planilha de Clientes (alem de NOME/CPF) que podem ser
# enriquecidas com dados vindos da conta do ADVBOX pro mesmo cliente - as
# chaves sao as mesmas usadas em advbox_io._FIELD_LABEL_TO_KEY, pra poder
# comparar/preencher direto sem tradução no meio.
CLIENTES_FIELD_HEADER_CANDIDATES = {
    "rg": ["RG"],
    "nacionalidade": ["NACIONALIDADE"],
    "data_nascimento": ["DATA DE NASCIMENTO"],
    "estado_civil": ["ESTADO CIVIL"],
    "profissao": ["PROFISSAO", "PROFISSÃO"],
    "sexo": ["SEXO"],
    "celular": ["CELULAR"],
    "telefone": ["TELEFONE"],
    "email": ["EMAIL", "E-MAIL"],
    "pais": ["PAIS", "PAÍS"],
    "estado": ["ESTADO"],
    "cidade": ["CIDADE"],
    "bairro": ["BAIRRO"],
    "endereco": ["ENDERECO", "ENDEREÇO"],
    "cep": ["CEP"],
    "pis_pasep": ["PIS PASEP"],
    "ctps": ["CTPS"],
    "cid": ["CID"],
    "nome_mae": ["NOME DA MAE", "NOME DA MÃE"],
    "origem": ["ORIGEM DO CLIENTE", "ORIGEM"],
    "anotacoes": ["ANOTACOES GERAIS", "ANOTAÇÕES GERAIS"],
}


def _norm_header(text):
    return normalize_name(text)


def _find_header_row_and_col(ws, candidates, max_scan_rows=5):
    """Procura, nas primeiras `max_scan_rows` linhas, uma celula cujo texto bata
    com um dos `candidates` (normalizado). Retorna (row_idx, col_idx) 1-based ou None."""
    norm_candidates = [_norm_header(c) for c in candidates]
    for r in range(1, max_scan_rows + 1):
        for c in range(1, ws.max_column + 1):
            val = ws.cell(row=r, column=c).value
            if val is None:
                continue
            if _norm_header(val) in norm_candidates:
                return r, c
    return None


def _find_col_in_header_row(ws, header_row, candidates):
    norm_candidates = [_norm_header(c) for c in candidates]
    for c in range(1, ws.max_column + 1):
        val = ws.cell(row=header_row, column=c).value
        if val is not None and _norm_header(val) in norm_candidates:
            return c
    return None


# "1.000" / "1.234.567": ponto agrupando milhar (sempre exatamente 3 digitos
# depois de cada ponto). Serve pra separar do ponto DECIMAL ("337.5",
# "115619.06"), onde apagar o ponto multiplicaria o valor por 10/100.
_DOT_MILHAR_RE = re.compile(r"^\d{1,3}(\.\d{3})+$")


def normalize_monetary_text(value):
    """Tira o separador de MILHAR de um valor monetario, preservando a virgula
    decimal: '1.000' -> '1000', '1.234,56' -> '1234,56', '337,50' fica igual.

    O risco aqui e confundir o ponto de milhar com o ponto DECIMAL da notacao
    inglesa - '337.5' virando '3375' seria erro de 10x no dinheiro. Por isso o
    ponto so e removido em dois casos, ambos sem ambiguidade:
      1. tem virgula no valor -> a virgula e o decimal, entao TODO ponto e milhar
         ('1.234,56' -> '1234,56');
      2. nao tem virgula, mas todo ponto e seguido de exatamente 3 digitos
         ('1.000', '1.234.567') - unico formato em que o ponto agrupa milhar.
    Fora disso o valor volta intacto. Celula que ja e numero (int/float) nao tem
    separador de milhar guardado (isso e so formatacao de exibicao), entao
    tambem volta intacta."""
    if value is None or isinstance(value, (int, float)):
        return value
    core = str(value).strip()
    if not core:
        return value
    if "," in core:
        novo = core.replace(".", "")
    elif _DOT_MILHAR_RE.match(core):
        novo = core.replace(".", "")
    else:
        return value
    return novo if novo != str(value) else value


def apply_monetary_normalization(ws, header_row, changes):
    """Roda normalize_monetary_text em todas as colunas de valor monetario da
    aba. Registra em `changes` so o que realmente mudou - valor que ja estava
    certo nao vira linha de log nem polui a previa."""
    for col in range(1, ws.max_column + 1):
        if not _is_monetary_header(ws.cell(row=header_row, column=col).value):
            continue
        coluna_label = str(ws.cell(row=header_row, column=col).value or "VALOR")
        for row in range(header_row + 1, ws.max_row + 1):
            cell = ws.cell(row=row, column=col)
            novo = normalize_monetary_text(cell.value)
            if novo != cell.value:
                changes.append({"row": row, "before": cell.value, "after": novo,
                                "coluna": coluna_label})
                cell.value = novo


def _is_monetary_header(text):
    """True quando o cabecalho da coluna indica valor monetario - detecta pelo
    token inteiro "VALOR" (nao substring), o que cobre "VALOR", "VALOR
    HONORARIOS" e "EXPECTATIVA/VALOR DA CAUSA" (a barra vira espaco na
    normalizacao) sem pegar por engano coisas como "VALORIZACAO"."""
    return "VALOR" in _norm_header(text).split()


def apply_column_formats(ws, header_row):
    """Formata as colunas da aba: valor monetario em AUTOMATICO, todo o resto
    em TEXTO SIMPLES (ver FORMAT_TEXTO_SIMPLES). So mexe no FORMATO da celula,
    nunca no valor - converter '337,50' pra numero (ou '01/10/2025' pra data)
    mudaria o dado em si e e justamente o que se quer evitar."""
    if not ws.max_row or not ws.max_column:
        return
    for col in range(1, ws.max_column + 1):
        header = ws.cell(row=header_row, column=col).value
        fmt = FORMAT_AUTOMATICO if _is_monetary_header(header) else FORMAT_TEXTO_SIMPLES
        for row in range(header_row + 1, ws.max_row + 1):
            ws.cell(row=row, column=col).number_format = fmt


def find_escavador_sheet(wb):
    """Retorna (sheet_name, header_row, col_idx, col_responsavel, col_parte_contraria,
    col_tipo_acao, col_grupo_acao) da aba/coluna 'NOME DO CLIENTE'. As demais
    colunas vem None se nao existirem."""
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        found = _find_header_row_and_col(ws, NOME_CLIENTE_HEADER_CANDIDATES)
        if found:
            header_row, col_idx = found
            col_responsavel = _find_col_in_header_row(ws, header_row, RESPONSAVEL_HEADER_CANDIDATES)
            col_parte_contraria = _find_col_in_header_row(ws, header_row, PARTE_CONTRARIA_HEADER_CANDIDATES)
            col_tipo_acao = _find_col_in_header_row(ws, header_row, TIPO_ACAO_HEADER_CANDIDATES)
            col_grupo_acao = _find_col_in_header_row(ws, header_row, GRUPO_ACAO_HEADER_CANDIDATES)
            return (sheet_name, header_row, col_idx, col_responsavel, col_parte_contraria,
                    col_tipo_acao, col_grupo_acao)
    return None


def find_clientes_sheet(wb):
    """Retorna (sheet_name, header_row, col_nome, col_cpf, field_cols) da aba
    de clientes. field_cols e um dict {chave_campo: col_idx} pras colunas
    extras reconhecidas (RG, telefone, endereco...), usadas pra trazer dados
    da conta do ADVBOX pro mesmo cliente (ver app.py)."""
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        found_nome = _find_header_row_and_col(ws, NOME_HEADER_CANDIDATES)
        if not found_nome:
            continue
        header_row, col_nome = found_nome
        col_cpf = _find_col_in_header_row(ws, header_row, CPF_HEADER_CANDIDATES)
        field_cols = {}
        for key, candidates in CLIENTES_FIELD_HEADER_CANDIDATES.items():
            col = _find_col_in_header_row(ws, header_row, candidates)
            if col:
                field_cols[key] = col
        return sheet_name, header_row, col_nome, col_cpf, field_cols
    return None


def find_financeiro_sheet(wb):
    """Retorna (sheet_name, header_row, col_nome, col_descricao, col_valor) da
    aba de lancamentos financeiros. Exige as tres colunas juntas (NOME DO
    CLIENTE + DESCRICAO + VALOR) de proposito: so "NOME DO CLIENTE" tambem
    existe na planilha de Processos, e sem essa exigencia a deteccao poderia
    casar com a aba errada se alguem enviasse o arquivo no campo trocado."""
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        found = _find_header_row_and_col(ws, NOME_CLIENTE_HEADER_CANDIDATES)
        if not found:
            continue
        header_row, col_nome = found
        col_descricao = _find_col_in_header_row(ws, header_row, DESCRICAO_HEADER_CANDIDATES)
        col_valor = _find_col_in_header_row(ws, header_row, VALOR_HEADER_CANDIDATES)
        if col_descricao and col_valor:
            return sheet_name, header_row, col_nome, col_descricao, col_valor
    return None


def read_financeiro_rows(path):
    """Le a planilha de Financeiro. Cada linha vira um dict
    {row, text, norm, descricao}. Diferente das outras planilhas, aqui a
    coluna NOME DO CLIENTE tem UM nome por linha (nao lista separada por
    ';'), entao o valor da celula e usado inteiro."""
    wb = openpyxl.load_workbook(path, data_only=True)
    found = find_financeiro_sheet(wb)
    if not found:
        raise ValueError(
            "Nao encontrei uma aba com as colunas 'NOME DO CLIENTE', 'DESCRICAO' e "
            "'VALOR' neste arquivo - confira se e mesmo a planilha de Financeiro."
        )
    sheet_name, header_row, col_nome, col_descricao, col_valor = found
    ws = wb[sheet_name]

    rows = []
    for row in range(header_row + 1, ws.max_row + 1):
        raw = ws.cell(row=row, column=col_nome).value
        if raw is None or not str(raw).strip():
            continue
        text = str(raw).strip()
        if is_junk_name(text):
            continue
        descricao = ws.cell(row=row, column=col_descricao).value
        rows.append({
            "row": row,
            "text": text,
            "norm": normalize_name(text),
            "descricao": str(descricao).strip() if descricao is not None else "",
        })
    return {
        "sheet_name": sheet_name,
        "header_row": header_row,
        "col_nome": col_nome,
        "col_descricao": col_descricao,
        "col_valor": col_valor,
        "rows": rows,
    }


def read_escavador_occurrences(path):
    """Le o arquivo do escavador e retorna:
      - meta: {sheet_name, header_row, col_idx, col_responsavel, col_parte_contraria}
      - occurrences: lista de dicts {text, norm, row, part_index, source, column} -
        cobre tanto NOME DO CLIENTE (column='cliente') quanto PARTE CONTRARIA
        (column='parte_contraria', se a coluna existir na planilha)
      - responsavel_occurrences: lista de dicts {text, norm, row} (coluna RESPONSAVEL,
        se existir na planilha)
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    found = find_escavador_sheet(wb)
    if not found:
        raise ValueError(
            "Nao encontrei uma coluna 'NOME DO CLIENTE' em nenhuma aba deste arquivo."
        )
    (sheet_name, header_row, col_idx, col_responsavel, col_parte_contraria,
     col_tipo_acao, col_grupo_acao) = found
    ws = wb[sheet_name]

    occurrences = []
    responsavel_occurrences = []
    tipo_acao_occurrences = []
    grupo_acao_occurrences = []
    for row in range(header_row + 1, ws.max_row + 1):
        cell_val = ws.cell(row=row, column=col_idx).value
        parts = [p for p in split_names(cell_val) if not is_junk_name(p)]
        for idx, text in enumerate(parts):
            occurrences.append({
                "text": text,
                "norm": normalize_name(text),
                "row": row,
                "part_index": idx,
                "source": "escavador",
                "column": "cliente",
            })
        if col_parte_contraria:
            pc_val = ws.cell(row=row, column=col_parte_contraria).value
            pc_parts = [p for p in split_names(pc_val) if not is_junk_name(p)]
            for idx, text in enumerate(pc_parts):
                occurrences.append({
                    "text": text,
                    "norm": normalize_name(text),
                    "row": row,
                    "part_index": idx,
                    "source": "escavador",
                    "column": "parte_contraria",
                })
        if col_responsavel:
            resp_val = ws.cell(row=row, column=col_responsavel).value
            if resp_val is not None and str(resp_val).strip():
                text = str(resp_val).strip()
                responsavel_occurrences.append({
                    "text": text,
                    "norm": normalize_name(text),
                    "row": row,
                })
        if col_tipo_acao:
            tipo_val = ws.cell(row=row, column=col_tipo_acao).value
            if tipo_val is not None and str(tipo_val).strip():
                text = str(tipo_val).strip()
                tipo_acao_occurrences.append({
                    "text": text,
                    "norm": normalize_name(text),
                    "row": row,
                })
        if col_grupo_acao:
            grupo_val = ws.cell(row=row, column=col_grupo_acao).value
            if grupo_val is not None and str(grupo_val).strip():
                text = str(grupo_val).strip()
                grupo_acao_occurrences.append({
                    "text": text,
                    "norm": normalize_name(text),
                    "row": row,
                })
    return {
        "sheet_name": sheet_name,
        "header_row": header_row,
        "col_idx": col_idx,
        "col_responsavel": col_responsavel,
        "col_parte_contraria": col_parte_contraria,
        "col_tipo_acao": col_tipo_acao,
        "col_grupo_acao": col_grupo_acao,
        "tipo_acao_occurrences": tipo_acao_occurrences,
        "grupo_acao_occurrences": grupo_acao_occurrences,
        "occurrences": occurrences,
        "responsavel_occurrences": responsavel_occurrences,
    }


def read_clientes_rows(path):
    """Le o arquivo de clientes e retorna:
      - meta: {sheet_name, header_row, col_nome, col_cpf, field_cols}
      - rows: lista de dicts {row, text, norm, cpf_raw, cpf_norm, fields}
        (fields: dict com os campos extras - RG, telefone, endereco... - que
        tiverem coluna E valor preenchido nessa linha; mesmas chaves que
        advbox_io usa, pra comparar/trazer dados da conta do ADVBOX)
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    found = find_clientes_sheet(wb)
    if not found:
        raise ValueError("Nao encontrei uma coluna 'NOME' neste arquivo de clientes.")
    sheet_name, header_row, col_nome, col_cpf, field_cols = found
    ws = wb[sheet_name]

    rows = []
    for row in range(header_row + 1, ws.max_row + 1):
        nome_val = ws.cell(row=row, column=col_nome).value
        if nome_val is None or not str(nome_val).strip():
            continue
        cpf_val = ws.cell(row=row, column=col_cpf).value if col_cpf else None
        fields = {}
        for key, col in field_cols.items():
            val = ws.cell(row=row, column=col).value
            if val is not None and str(val).strip():
                fields[key] = str(val).strip()
        rows.append({
            "row": row,
            "text": str(nome_val).strip(),
            "norm": normalize_name(nome_val),
            "cpf_raw": cpf_val,
            "cpf_norm": normalize_cpf(cpf_val),
            "source": "clientes",
            "fields": fields,
        })
    return {
        "sheet_name": sheet_name,
        "header_row": header_row,
        "col_nome": col_nome,
        "col_cpf": col_cpf,
        "field_cols": field_cols,
        "rows": rows,
    }


def _dedupe_preserve_order(items):
    seen = set()
    out = []
    for it in items:
        key = normalize_name(it)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _apply_multi_value_column(ws, header_row, col_idx, mapping, changes, coluna_label, remove_norms=None):
    """Aplica o mapa norm->canonico numa coluna que pode ter varios nomes separados
    por ';' na mesma celula, removendo duplicata apos a padronizacao, cortando
    fora qualquer "nome" que na verdade seja mensagem de sistema (ex: "PROCESSO
    ESTA EM SEGREDO DE JUSTICA") e removendo os nomes indicados em `remove_norms`
    (usado, por ex., pra tirar de Cliente uma parte contraria cadastrada por
    engano como cliente)."""
    remove_norms = remove_norms or set()
    for row in range(header_row + 1, ws.max_row + 1):
        cell = ws.cell(row=row, column=col_idx)
        original = cell.value
        raw_parts = split_names(original)
        if not raw_parts:
            continue
        new_parts = []
        for text in raw_parts:
            if is_junk_name(text):
                continue
            norm = normalize_name(text)
            if norm in remove_norms:
                continue
            canonical = mapping.get(norm, text)
            new_parts.append(canonical)
        new_parts = _dedupe_preserve_order(new_parts)
        if not new_parts and coluna_label == "NOME DO CLIENTE":
            # ficou vazio (so tinha mensagem de sistema, ou nada) - usa o
            # padrao ja existente na planilha em vez de deixar em branco.
            new_value = NAO_INFORMADO
        else:
            # sem espaco depois do ";" - preserva o formato original da
            # planilha (ex: "GILMAR OTAVIO;RAFAEL NUNES"), sem colar um espaco
            # a mais que nao existia antes.
            new_value = ";".join(new_parts)
        if new_value != (original or ""):
            changes.append({"row": row, "before": original, "after": new_value, "coluna": coluna_label})
            cell.value = new_value


def _apply_single_value_column(ws, header_row, col, value_mapping, changes, coluna_label):
    """Corrige uma coluna de valor unico por linha (RESPONSAVEL, TIPO DE ACAO,
    GRUPO DE ACAO...) usando um mapa norm->valor final. So mexe na celula
    quando ha um mapeamento pro valor atual E ele e diferente do que ja
    esta la."""
    if not col or not value_mapping:
        return
    for row in range(header_row + 1, ws.max_row + 1):
        cell = ws.cell(row=row, column=col)
        original = cell.value
        if original is not None and str(original).strip():
            norm = normalize_name(original)
            canonical = value_mapping.get(norm)
            if canonical and canonical != original:
                changes.append({"row": row, "before": original, "after": canonical, "coluna": coluna_label})
                cell.value = canonical


def apply_escavador(path, meta, mapping, out_path, responsavel_mapping=None,
                     tipo_acao_mapping=None, grupo_acao_mapping=None,
                     remove_from_cliente_norms=None, remove_from_parte_norms=None,
                     dry_run=False):
    """Aplica o mapa norm->canonico nas colunas NOME DO CLIENTE e PARTE CONTRARIA
    (removendo duplicata dentro da mesma celula em cada uma) e, se
    `responsavel_mapping`/`tipo_acao_mapping`/`grupo_acao_mapping` forem
    passados e a coluna correspondente existir, tambem corrige essas colunas
    (RESPONSAVEL, TIPO DE ACAO, GRUPO DE ACAO). `remove_from_cliente_norms`
    tira de NOME DO CLIENTE (em TODAS as linhas onde aparecer) nomes
    confirmados como sendo, na verdade, uma parte contraria (usa "NAO
    INFORMADO" se a celula ficar vazia). `remove_from_parte_norms` faz o
    mesmo, mas tirando de PARTE CONTRARIA (fica so em branco se ficar
    vazia). Grava um novo arquivo com aba extra de log - a menos que
    `dry_run=True`, que calcula tudo igual mas NAO salva nada em disco
    (usado pra mostrar uma previa do que vai mudar antes de aplicar de
    verdade). Retorna lista de mudancas: [{row, before, after, coluna}]."""
    wb = openpyxl.load_workbook(path)
    ws = wb[meta["sheet_name"]]
    col_idx = meta["col_idx"]
    col_parte_contraria = meta.get("col_parte_contraria")

    changes = []

    _apply_multi_value_column(ws, meta["header_row"], col_idx, mapping, changes, "NOME DO CLIENTE",
                               remove_norms=remove_from_cliente_norms)
    if col_parte_contraria:
        _apply_multi_value_column(ws, meta["header_row"], col_parte_contraria, mapping, changes, "PARTE CONTRARIA",
                                   remove_norms=remove_from_parte_norms)

    _apply_single_value_column(ws, meta["header_row"], meta.get("col_responsavel"),
                                responsavel_mapping or {}, changes, "RESPONSAVEL")
    _apply_single_value_column(ws, meta["header_row"], meta.get("col_tipo_acao"),
                                tipo_acao_mapping or {}, changes, "TIPO DE ACAO")
    _apply_single_value_column(ws, meta["header_row"], meta.get("col_grupo_acao"),
                                grupo_acao_mapping or {}, changes, "GRUPO DE ACAO")

    # fora do `if not dry_run` de proposito: e uma alteracao de VALOR (nao de
    # formatacao), entao precisa aparecer na previa antes de ser aplicada.
    apply_monetary_normalization(ws, meta["header_row"], changes)

    if not dry_run:
        apply_column_formats(ws, meta["header_row"])
        _write_change_log(wb, changes, "valor")
        wb.save(out_path)
    return changes


def apply_clientes(path, meta, mapping, out_path, rows_to_delete=None, extra_rows=None,
                    field_updates=None, field_overrides=None, dry_run=False):
    """Aplica o mapa norm->canonico na coluna NOME, opcionalmente remove linhas
    de CPF duplicado ja resolvidas, adiciona linhas novas ao final (ex: nomes
    que so existem na conta do ADVBOX e ainda nao estao cadastrados aqui -
    `extra_rows: [{"nome": str, "fields": {chave: valor}}]`), enriquece
    linhas existentes com dados vindos do ADVBOX pro mesmo cliente
    (`field_updates: {norm: {chave: valor}}` - so preenche celula que
    estava VAZIA, nunca sobrescreve dado que ja existia) e resolve
    conflitos de campo confirmados pelo usuario (`field_overrides:
    {norm: {chave: valor}}` - esse SIM sobrescreve, mas so quando o valor
    ja existente e diferente do escolhido, e so pro campo especifico que
    foi confirmado). Grava um novo arquivo com aba extra de log - a menos
    que `dry_run=True` (calcula tudo, nao salva - usado pra previa)."""
    rows_to_delete = rows_to_delete or set()
    extra_rows = extra_rows or []
    field_updates = field_updates or {}
    field_overrides = field_overrides or {}
    wb = openpyxl.load_workbook(path)
    ws = wb[meta["sheet_name"]]
    col_nome = meta["col_nome"]
    col_cpf = meta.get("col_cpf")
    all_field_cols = dict(meta.get("field_cols") or {})
    if col_cpf:
        all_field_cols["cpf_cnpj"] = col_cpf

    changes = []
    for row in range(meta["header_row"] + 1, ws.max_row + 1):
        cell = ws.cell(row=row, column=col_nome)
        original = cell.value
        if original is None or not str(original).strip():
            continue
        norm = normalize_name(original)
        canonical = mapping.get(norm)
        if canonical and canonical != original:
            changes.append({"row": row, "before": original, "after": canonical})
            cell.value = canonical

        updates = field_updates.get(norm)
        if updates:
            for key, value in updates.items():
                col = all_field_cols.get(key)
                if not col or not value:
                    continue
                target_cell = ws.cell(row=row, column=col)
                current_value = str(target_cell.value).strip() if target_cell.value is not None else ""
                if not current_value:
                    changes.append({"row": row, "before": "(vazio)", "after": value,
                                     "coluna": f"{key} (trazido do ADVBOX)"})
                    target_cell.value = value
                elif (
                    len(" ".join(value.split())) > len(" ".join(current_value.split()))
                    and " ".join(value.split()).upper().startswith(" ".join(current_value.split()).upper())
                ):
                    # o ADVBOX "ultrapassa" o que ja esta aqui - mesmo
                    # comeco, so que mais completo (ex: endereco truncado
                    # localmente) - completa em vez de so sinalizar.
                    changes.append({"row": row, "before": target_cell.value, "after": value,
                                     "coluna": f"{key} (completado com dado mais extenso do ADVBOX)"})
                    target_cell.value = value

        overrides = field_overrides.get(norm)
        if overrides:
            for key, value in overrides.items():
                col = all_field_cols.get(key)
                if not col or not value:
                    continue
                target_cell = ws.cell(row=row, column=col)
                before = target_cell.value
                if str(before or "").strip() != value.strip():
                    changes.append({"row": row, "before": before, "after": value,
                                     "coluna": f"{key} (conflito resolvido - ADVBOX)"})
                    target_cell.value = value

    for row in sorted(rows_to_delete, reverse=True):
        ws.delete_rows(row, 1)
        changes.append({"row": row, "before": "(linha removida - CPF duplicado)", "after": ""})

    next_row = ws.max_row + 1
    for extra in extra_rows:
        nome = (extra.get("nome") or "").strip()
        if not nome:
            continue
        ws.cell(row=next_row, column=col_nome).value = nome
        for key, value in (extra.get("fields") or {}).items():
            col = all_field_cols.get(key)
            if col and value:
                ws.cell(row=next_row, column=col).value = value
        changes.append({"row": next_row, "before": "(linha nova - vinda do ADVBOX)", "after": nome})
        next_row += 1

    apply_monetary_normalization(ws, meta["header_row"], changes)

    if not dry_run:
        apply_column_formats(ws, meta["header_row"])
        _write_change_log(wb, changes, "NOME")
        wb.save(out_path)
    return changes


def apply_financeiro(path, meta, mapping, out_path, move_to_descricao_norms=None, dry_run=False):
    """Aplica na planilha de Financeiro:
      - `mapping` (norm -> canonico): padroniza a coluna NOME DO CLIENTE com o
        mesmo nome final decidido nos grupos de homonimos, pra planilha
        financeira nao ficar com uma grafia diferente das outras duas;
      - `move_to_descricao_norms`: nomes confirmados como NAO existentes nem em
        Clientes nem em Processos. Nesses, o nome sai da coluna NOME DO CLIENTE
        (celula fica vazia) e vai pro INICIO da DESCRICAO, separado do que ja
        estava la por ';' sem espaco (ex: "FULANO;Parcela 7 de 8...").

    A decisao de mover e avaliada pela norma ORIGINAL da celula (a mesma que a
    tela mostrou), nao pela pos-padronizacao - um nome orfao nao tem
    correspondente pra virar canonico, entao aplicar o mapping antes so
    embaralharia a chave da decisao. Retorna lista de mudancas."""
    move_to_descricao_norms = move_to_descricao_norms or set()
    wb = openpyxl.load_workbook(path)
    ws = wb[meta["sheet_name"]]
    header_row = meta["header_row"]
    col_nome = meta["col_nome"]
    col_descricao = meta["col_descricao"]

    changes = []
    for row in range(header_row + 1, ws.max_row + 1):
        cell_nome = ws.cell(row=row, column=col_nome)
        raw = cell_nome.value
        if raw is None or not str(raw).strip():
            continue
        text = str(raw).strip()
        norm = normalize_name(text)

        if norm in move_to_descricao_norms:
            cell_desc = ws.cell(row=row, column=col_descricao)
            desc_atual = "" if cell_desc.value is None else str(cell_desc.value).strip()
            novo_desc = f"{text};{desc_atual}" if desc_atual else text
            if novo_desc != (cell_desc.value or ""):
                changes.append({"row": row, "before": cell_desc.value, "after": novo_desc,
                                "coluna": "DESCRICAO"})
                cell_desc.value = novo_desc
            changes.append({"row": row, "before": text, "after": "", "coluna": "NOME DO CLIENTE"})
            cell_nome.value = None
            continue

        canonical = mapping.get(norm)
        if canonical and canonical != text:
            changes.append({"row": row, "before": text, "after": canonical,
                            "coluna": "NOME DO CLIENTE"})
            cell_nome.value = canonical

    apply_monetary_normalization(ws, header_row, changes)

    if not dry_run:
        apply_column_formats(ws, header_row)
        _write_change_log(wb, changes, "NOME DO CLIENTE")
        wb.save(out_path)
    return changes


def _write_change_log(wb, changes, default_column_label):
    sheet_name = "Alteracoes Padronizador"
    if sheet_name in wb.sheetnames:
        del wb[sheet_name]
    ws = wb.create_sheet(sheet_name)
    ws.append(["Linha", "Coluna", "Antes", "Depois", "Gerado em"])
    now = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    for ch in changes:
        ws.append([ch["row"], ch.get("coluna", default_column_label), ch["before"], ch["after"], now])


def make_output_path(original_path, out_dir, suffix="_padronizado"):
    base = os.path.basename(original_path)
    name, ext = os.path.splitext(base)
    return os.path.join(out_dir, f"{name}{suffix}{ext}")
