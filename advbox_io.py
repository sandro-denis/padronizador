"""
Leitura dos relatorios em PDF exportados do ADVBOX ("Pagina de impressao"),
usados pra validar/cruzar os nomes ja padronizados com o que ja existe
cadastrado na conta do escritorio no ADVBOX, e pra trazer os dados extras
(CPF, telefone, endereco...) de quem so existe la.

Dois formatos suportados:
  - "LISTA DE PESSOAS": nome + varios campos (CPF/CNPJ, RG, data de
    nascimento, telefone/celular, e-mail, endereco, origem...), um bloco por
    pessoa. E um layout de "ficha" com 2 sub-colunas de campos (esquerda:
    CPF/CNPJ, RG, DATA DE NASCIMENTO, ENDERECO, ORIGEM; direita: TELEFONE/
    CELULAR, E-MAIL) - extraido com layout=True (preserva posicao via
    espacamento) pra distinguir nome (sem indentacao) de campo/continuacao
    (indentado).
  - "RESUMO DE PROCESSOS": tabela de 3 colunas (dados do processo / ultimo
    andamento / fase) - so a primeira coluna interessa aqui (nomes das
    partes). A posicao X que separa as colunas NAO e fixa (varia entre
    contas/exportacoes do ADVBOX) - e medida dinamicamente a partir da
    palavra "ANDAMENTO" no cabecalho de cada arquivo, nao de uma constante.

Ambos os relatorios repetem o mesmo cabecalho (nome do escritorio/telefone/
email/endereco/"Relatorio emitido em...") no topo de cada pagina - removido
via padrao de texto, nao por posicao fixa, porque um bloco de processo pode
continuar na pagina seguinte (o cabecalho aparece NO MEIO do bloco nesse
caso).
"""
import re

import pdfplumber

from matching import classify_court_or_judge, normalize_cpf, normalize_name

_PHONE_RE = re.compile(r"^\(\d{2}\)\s?\d{4,5}-\d{4,5}$")
_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")
_CEP_CIDADE_RE = re.compile(r"^\d{5}-\d{3}\s*-\s*.+/[A-Z]{2}$")
_EMITIDO_RE = re.compile(r"^Relat[oó]rio emitido em ")
_LISTA_HEADER_RE = re.compile(r"^(LISTA DE PESSOAS|RESUMO DE PROCESSOS)\s*-\s*\d+\s*A\b", re.IGNORECASE)
_TOTAL_RE = re.compile(r"^TOTAL:\s*[\d.]+$", re.IGNORECASE)
_COL_HEADER_RE = re.compile(r"^DADOS DO PROCESSO\b", re.IGNORECASE)


def _is_junk_line(stripped, next_stripped):
    """Linhas de cabecalho/rodape repetidas em cada pagina do relatorio
    (nome do escritorio, telefone, email, endereco, 'emitido em...',
    cabecalho da lista/coluna, 'TOTAL: N'). O nome do escritorio em si
    (livre, sem padrao fixo) e identificado por look-ahead: e sempre
    seguido imediatamente pela linha de telefone; o endereco, pela linha
    de CEP/cidade."""
    if _PHONE_RE.match(next_stripped) or _CEP_CIDADE_RE.match(next_stripped):
        return True
    if _PHONE_RE.match(stripped) or _EMAIL_RE.match(stripped) or _CEP_CIDADE_RE.match(stripped):
        return True
    if _EMITIDO_RE.match(stripped) or _LISTA_HEADER_RE.match(stripped):
        return True
    if _COL_HEADER_RE.match(stripped) or _TOTAL_RE.match(stripped):
        return True
    return False


def _strip_letterhead(lines):
    """Como _is_junk_line, mas descarta a linha inteira (usado quando a
    indentacao original nao importa - relatorio de processos, que ja foi
    isolado numa unica coluna antes de chegar aqui)."""
    cleaned = []
    n = len(lines)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        next_stripped = lines[i + 1].strip() if i + 1 < n else ""
        if _is_junk_line(stripped, next_stripped):
            continue
        cleaned.append(stripped)
    return cleaned


def _clean_layout_lines(lines):
    """Como _strip_letterhead, mas preserva a indentacao original de cada
    linha que sobra (usado pro relatorio de pessoas, onde a indentacao
    distingue nome de campo/continuacao - ver read_pessoas_pdf)."""
    cleaned = []
    n = len(lines)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        next_stripped = lines[i + 1].strip() if i + 1 < n else ""
        if _is_junk_line(stripped, next_stripped):
            continue
        cleaned.append(line)
    return cleaned


# --- LISTA DE PESSOAS (campos ricos: CPF/CNPJ, RG, DATA DE NASCIMENTO,
# TELEFONE/CELULAR, E-MAIL, ENDERECO, ORIGEM, e outros da PLANILHA CLIENTES
# do ADVBOX) --------------------------------------------------------------

_FIELD_LABEL_TO_KEY = {
    "CPF/CNPJ": "cpf_cnpj",
    "RG": "rg",
    "DATA DE NASCIMENTO": "data_nascimento",
    "ESTADO CIVIL": "estado_civil",
    "NACIONALIDADE": "nacionalidade",
    "PROFISSAO": "profissao",
    "PROFISSÃO": "profissao",
    "SEXO": "sexo",
    "CELULAR": "celular",
    "TELEFONE": "telefone",
    "E-MAIL": "email",
    "EMAIL": "email",
    "PAIS": "pais",
    "PAÍS": "pais",
    "ESTADO": "estado",
    "CIDADE": "cidade",
    "BAIRRO": "bairro",
    "ENDERECO": "endereco",
    "ENDEREÇO": "endereco",
    "CEP": "cep",
    "PIS PASEP": "pis_pasep",
    "CTPS": "ctps",
    "CID": "cid",
    "NOME DA MAE": "nome_mae",
    "NOME DA MÃE": "nome_mae",
    "ORIGEM": "origem",
    "ANOTACOES GERAIS": "anotacoes",
    "ANOTAÇÕES GERAIS": "anotacoes",
    # o rotulo "ANOTACOES GERAIS" e o valor mais longo da ficha e por isso
    # o unico da sub-coluna direita que chega a quebrar em mais de uma
    # linha - as vezes a quebra cai bem no meio do proprio rotulo (ex:
    # "...ANOTAÇÕES" no fim de uma linha, "GERAIS <texto>" no comeco da
    # seguinte). Sem essas variantes soltas, "ANOTAÇÕES"/"GERAIS" nao eram
    # reconhecidos como rotulo nenhum e o texto livre das anotacoes vazava
    # pro campo da ESQUERDA que estivesse ativo naquela linha (RG, DATA DE
    # NASCIMENTO, ENDERECO, ORIGEM ficavam com lixo colado no valor).
    "ANOTACOES": "anotacoes",
    "ANOTAÇÕES": "anotacoes",
}
_FIELD_LABELS_SORTED = sorted(_FIELD_LABEL_TO_KEY, key=len, reverse=True)
_FIELD_LABEL_ANYWHERE_RE = re.compile(
    r"(" + "|".join(re.escape(l) for l in _FIELD_LABELS_SORTED) + r")\b",
    re.IGNORECASE,
)
# so os campos da sub-coluna ESQUERDA da ficha (CPF/CNPJ, RG, DATA DE
# NASCIMENTO, ENDERECO, ORIGEM...) chegam a quebrar em mais de uma linha -
# os da direita (CELULAR/TELEFONE/E-MAIL) sao sempre curtos, cabem numa
# linha so. Por isso uma linha de continuacao (sem nenhum label) sempre
# pertence ao ULTIMO CAMPO DA ESQUERDA visto, nunca a um da direita, mesmo
# que o da direita tenha aparecido depois dele na mesma linha (ex:
# "ENDERECO ...(quebra)... E-MAIL ..." - a proxima linha continua o
# ENDERECO, nao o E-MAIL, mesmo o E-MAIL sendo o ultimo par da linha).
# ANOTACOES tambem mora na sub-coluna direita, mas ao contrario de
# CELULAR/TELEFONE/E-MAIL ela E longa o bastante pra quebrar linha - por
# isso tem tratamento a parte (ver _WRAPPING_RIGHT_COLUMN_KEY abaixo).
_RIGHT_COLUMN_KEYS = {"celular", "telefone", "email", "anotacoes"}
_WRAPPING_RIGHT_COLUMN_KEY = "anotacoes"
# coluna (em numero de caracteres) onde comeca a sub-coluna direita da
# ficha - medido nos relatorios reais (rotulos da esquerda como "RG" ou
# "DATA DE NASCIMENTO" mais seus valores curtos nunca chegam nem perto
# disso; a continuacao de ANOTACOES sempre comeca bem depois). Usado so
# pra decidir, numa linha de continuacao sem rotulo nenhum, se ela
# pertence ao campo ativo da esquerda ou ao ANOTACOES da direita.
_RIGHT_COLUMN_CONTINUATION_INDENT = 35


def _split_field_line(line):
    """Uma linha de campo pode ter 1 ou 2 pares label/valor lado a lado
    (sub-coluna esquerda + direita da ficha, ex: 'CPF/CNPJ 123...
    TELEFONE (62)...'). Retorna lista de (chave_campo, valor)."""
    tokens = _FIELD_LABEL_ANYWHERE_RE.split(line)
    pairs = []
    idx = 1
    while idx < len(tokens):
        label = tokens[idx]
        value = tokens[idx + 1].strip() if idx + 1 < len(tokens) else ""
        key = _FIELD_LABEL_TO_KEY.get(label.upper())
        if key:
            pairs.append((key, value))
        idx += 2
    return pairs


def read_pessoas_pdf(path):
    """Le o relatorio 'LISTA DE PESSOAS' do ADVBOX. Retorna lista de dicts
    {text, norm, cpf_norm, fields} - um por pessoa/empresa cadastrada na
    conta (mistura clientes e partes contrarias, o ADVBOX nao distingue
    nessa lista). `fields` e um dict com as chaves em _FIELD_LABEL_TO_KEY
    que tiverem valor preenchido no relatorio (ex: {"cpf_cnpj": "123...",
    "celular": "(62) ...", "endereco": "..."})."""
    all_lines = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(layout=True) or ""
            all_lines.extend(text.split("\n"))
    lines = _clean_layout_lines(all_lines)

    results = []
    current = None
    current_field_left = None
    current_field_right = None
    # True logo apos uma linha terminar com "ANOTAÇÕES"/"ANOTACOES" solto,
    # sem valor nenhum depois - sinal de que o rotulo "ANOTACOES GERAIS"
    # quebrou no meio e o "GERAIS" residual vai aparecer no comeco da
    # sub-coluna direita da PROXIMA linha, colado ao texto livre real.
    anotacoes_label_dangling = False

    def finalize(entry):
        fields = entry["fields"]
        return {
            "text": entry["text"],
            "norm": normalize_name(entry["text"]),
            "cpf_norm": normalize_cpf(fields.get("cpf_cnpj", "")),
            "fields": fields,
        }

    def append_field(entry, key, extra):
        if not extra:
            return
        existing = entry["fields"].get(key, "")
        entry["fields"][key] = f"{existing} {extra}".strip()

    for raw_line in lines:
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if not stripped:
            continue

        if indent <= 1:
            # sem indentacao (ou quase) = nome de uma nova pessoa
            if current:
                results.append(finalize(current))
            current = {"text": stripped, "fields": {}}
            current_field_left = None
            current_field_right = None
            anotacoes_label_dangling = False
            continue

        if current is None:
            continue  # linha orfa antes de qualquer nome - nao deveria ocorrer

        line_to_split = stripped
        if anotacoes_label_dangling:
            # o rotulo ANOTACOES GERAIS ficou com valor vazio na linha
            # anterior (ou porque o proprio rotulo quebrou no meio - sobra
            # "GERAIS" solto aqui - ou porque o rotulo inteiro coube numa
            # linha so e o texto livre comeca direto na de baixo, sem
            # "GERAIS" nenhum). Nos dois casos a sub-coluna DIREITA desta
            # linha pertence as anotacoes - so a ESQUERDA (ate a coluna
            # limite) e que pode ter um rotulo de verdade (ex: DATA DE
            # NASCIMENTO). Sem tratar os dois casos aqui, o texto livre
            # ficava colado direto no valor desse campo da esquerda.
            prefix = raw_line[:_RIGHT_COLUMN_CONTINUATION_INDENT]
            rest = raw_line[_RIGHT_COLUMN_CONTINUATION_INDENT:]
            m = re.match(r"\s*GERAIS\b\s*", rest, re.IGNORECASE)
            anotacoes_label_dangling = False
            right_text = (rest[m.end():] if m else rest).strip()
            if right_text:
                append_field(current, _WRAPPING_RIGHT_COLUMN_KEY, right_text)
                current_field_right = _WRAPPING_RIGHT_COLUMN_KEY
            line_to_split = prefix.strip()

        if not line_to_split:
            continue

        pairs = _split_field_line(line_to_split)
        if pairs:
            for key, value in pairs:
                if key == _WRAPPING_RIGHT_COLUMN_KEY:
                    if value:
                        append_field(current, key, value)
                    else:
                        anotacoes_label_dangling = True
                elif value:
                    current["fields"][key] = value
            left_pairs = [k for k, _ in pairs if k not in _RIGHT_COLUMN_KEYS]
            if left_pairs:
                current_field_left = left_pairs[-1]
            if any(k == _WRAPPING_RIGHT_COLUMN_KEY for k, _ in pairs):
                current_field_right = _WRAPPING_RIGHT_COLUMN_KEY
        else:
            # continuacao do valor do ultimo campo (ex: endereco ou
            # anotacoes que quebraram em varias linhas por serem longos
            # demais pra largura da coluna) - qual dos dois depende da
            # posicao horizontal (coluna) da linha, esquerda ou direita.
            if indent >= _RIGHT_COLUMN_CONTINUATION_INDENT and current_field_right:
                append_field(current, current_field_right, stripped)
            elif current_field_left:
                append_field(current, current_field_left, stripped)

    if current:
        results.append(finalize(current))

    return results


# --- RESUMO DE PROCESSOS --------------------------------------------------

_LABEL_LINE_RE = re.compile(
    r"^(N[UÚ]MERO CNJ|N[UÚ]MERO PROTOCOLO|COMARCA|VARA|PROCESSO ORIGIN[AÁ]RIO|"
    r"RESPONS[AÁ]VEL|SISTEMA ELETR[OÔ]NICO|TIPO DE A[CÇ][AÃ]O|GRUPO DE A[CÇ][AÃ]O|"
    r"ETAPA|PASTA):",
    re.IGNORECASE,
)
_FASE_LINE_RE = re.compile(r"^FASE:", re.IGNORECASE)
_CNJ_VALUE_RE = re.compile(r"^N[UÚ]MERO CNJ:\s*(.+)$", re.IGNORECASE)
# cabecalho da lista as vezes fica truncado na coluna 1 (a contagem final,
# ex: "50 DE 1.214", pode terminar cortada ou sobrar sozinha numa linha,
# ja que o cabecalho ocupa a largura inteira da pagina, nao so a coluna 1).
_HEADER_TAIL_RE = re.compile(r"^\d+\s+DE\s+[\d.]+$", re.IGNORECASE)

# fallback pro caso raro de nao achar a palavra "ANDAMENTO" no cabecalho
# (relatorio com layout diferente do esperado) - valor observado num dos
# relatorios reais testados, mais provavel de cortar cedo demais (perdendo
# um pouco de nome) do que tarde demais (misturando coluna 2 junto).
_PROCESSOS_COLUNA1_X_FALLBACK = 140.0


def _find_coluna1_x_limit(pdf):
    """Acha a coordenada X onde comeca a coluna 'ULTIMO ANDAMENTO' do
    relatorio de processos, procurando a palavra 'ANDAMENTO' no cabecalho da
    tabela. Essa posicao NAO e fixa entre contas/exportacoes diferentes do
    ADVBOX (ja variou entre dois relatorios reais testados) - por isso e
    sempre medida no proprio arquivo, nunca fixada como constante."""
    for page in pdf.pages[:2]:
        for w in page.extract_words():
            if w["top"] < 150 and w["text"].upper().startswith("ANDAMENTO"):
                return w["x0"] - 1
    return _PROCESSOS_COLUNA1_X_FALLBACK


def _group_words_into_lines(words, y_tolerance=2.0):
    """Agrupa palavras (de extract_words) em linhas visuais - cada uma com
    o texto (na ordem X) e se e 'negrito'. No relatorio de processos, o(s)
    nome(s) do CLIENTE sempre aparecem em negrito, diferente de parte
    contraria ('X ...'), metadados e texto de continuacao (todos em peso
    normal) - e o unico jeito confiavel de saber se uma linha sem 'X ' na
    frente e um nome de cliente novo ou a continuacao (quebra de linha) do
    que veio antes, ja que o espacamento vertical entre elas e identico."""
    if not words:
        return []
    ordered = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines = [[ordered[0]]]
    for w in ordered[1:]:
        if abs(w["top"] - lines[-1][-1]["top"]) <= y_tolerance:
            lines[-1].append(w)
        else:
            lines.append([w])

    result = []
    for line_words in lines:
        line_words.sort(key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in line_words)
        is_bold = any("bold" in (w.get("fontname") or "").lower() for w in line_words)
        result.append({"text": text, "bold": is_bold})
    return result


def _extract_first_column_lines(page, x_limit):
    cropped = page.within_bbox((0, 0, x_limit, page.height))
    words = cropped.extract_words(extra_attrs=["fontname"])
    return _group_words_into_lines(words)


def _strip_letterhead_lines(lines):
    """Como _strip_letterhead, mas mantem a marcacao de negrito de cada
    linha (necessaria pro parsing de processos)."""
    cleaned = []
    n = len(lines)
    for i, line in enumerate(lines):
        stripped = line["text"].strip()
        if not stripped:
            continue
        next_stripped = lines[i + 1]["text"].strip() if i + 1 < n else ""
        if _is_junk_line(stripped, next_stripped) or _HEADER_TAIL_RE.match(stripped):
            continue
        cleaned.append({"text": stripped, "bold": line["bold"]})
    return cleaned


def read_processos_pdf(path):
    """Le o relatorio 'RESUMO DE PROCESSOS' do ADVBOX (so a coluna 'DADOS DO
    PROCESSO', que tem os nomes das partes). Retorna lista de dicts
    {cnj, cliente_names: [...], parte_names: [...]} - um por processo.

    Cada bloco de processo comeca com os nomes (sem prefixo = cliente, em
    negrito; com prefixo 'X ' = parte contraria) seguidos de linhas 'LABEL:
    valor' (metadados, ignorados aqui - so os nomes interessam pra essa
    validacao) terminando sempre em 'FASE: ...'. Um bloco pode continuar na
    pagina seguinte (o cabecalho da pagina e removido antes desse parsing,
    entao isso e transparente aqui). Nomes longos que quebram em mais de uma
    linha sao reconhecidos pelo peso da fonte: a quebra nunca fica em
    negrito nem comeca com 'X ', entao e sempre reconhecida como
    continuacao do ultimo nome adicionado (cliente ou parte)."""
    all_lines = []
    with pdfplumber.open(path) as pdf:
        x_limit = _find_coluna1_x_limit(pdf)
        for page in pdf.pages:
            all_lines.extend(_extract_first_column_lines(page, x_limit))
    lines = _strip_letterhead_lines(all_lines)

    blocks = []
    current = None
    # "names": coletando nomes (cliente/parte) do bloco atual.
    # "metadata": depois do 1o rotulo (NUMERO CNJ/COMARCA/...), antes de FASE.
    # "after_fase": depois da linha "FASE: ..." - so falta saber se o texto
    #   da fase quebrou em mais linhas (ignoradas) ou se o proximo bloco ja
    #   comecou (primeira linha em negrito ou com "X ").
    state = "names"
    last_target = None  # "cliente" | "parte" - quem uma continuacao pertence

    def start_new_block():
        return {"cnj": None, "cliente_names": [], "parte_names": []}

    def finalize_current():
        if current and (current["cliente_names"] or current["parte_names"]):
            blocks.append(current)

    current = start_new_block()

    for line in lines:
        text = line["text"]

        if state == "names":
            if _LABEL_LINE_RE.match(text):
                state = "metadata"
                m = _CNJ_VALUE_RE.match(text)
                if m:
                    current["cnj"] = m.group(1).strip()
            elif text.startswith("X "):
                current["parte_names"].append(text[2:].strip())
                last_target = "parte"
            elif line["bold"] or not last_target:
                current["cliente_names"].append(text)
                last_target = "cliente"
            else:
                # nem rotulo, nem "X ", nem negrito - continuacao (quebra de
                # linha) do ultimo nome adicionado
                target = current[f"{last_target}_names"]
                target[-1] = f"{target[-1]} {text}"
            continue

        if state == "metadata":
            m = _CNJ_VALUE_RE.match(text)
            if m and not current["cnj"]:
                current["cnj"] = m.group(1).strip()
            if _FASE_LINE_RE.match(text):
                state = "after_fase"
            continue

        # state == "after_fase": o texto livre da fase (ex: "C1. PREVISAO DE
        # PAGAMENTO") pode continuar em mais uma linha antes do proximo
        # bloco comecar de verdade - so trata como novo bloco quando a linha
        # e claramente um nome (negrito ou "X "), senao ignora (continuacao
        # do texto da fase, irrelevante pra essa validacao de nomes).
        if line["bold"]:
            finalize_current()
            current = start_new_block()
            current["cliente_names"].append(text)
            last_target = "cliente"
            state = "names"
        elif text.startswith("X "):
            finalize_current()
            current = start_new_block()
            current["parte_names"].append(text[2:].strip())
            last_target = "parte"
            state = "names"
        # senao: continuacao do texto da fase - ignora

    finalize_current()
    return blocks


def is_court_reference(text):
    """True quando um nome vindo do ADVBOX (pessoa ou parte de processo) na
    verdade e referencia a tribunal/vara/comarca/juiz - contaminacao comum
    nos dois relatorios (ex: pessoa cadastrada como '14A VARA', parte
    contraria 'JUIZADO ESPECIAL FEDERAL'). Reaproveita o mesmo detector
    usado pra Escavador (matching.classify_court_or_judge)."""
    return classify_court_or_judge(text) is not None
