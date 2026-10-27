"""
Motor de deteccao de homonimos e duplicatas de clientes.

Ideia geral:
  1. Normaliza nomes (maiusculas, sem acento, espacos colapsados).
  2. Compara pares de nomes usando similaridade fuzzy (rapidfuzz) + uma regra
     propria de "subconjunto/abreviacao" (ex: "GILMAR O ROCHA" ~ "GILMAR OTAVIO DA ROCHA").
  3. Agrupa pares que baterem em clusters (union-find) = candidatos a mesma pessoa.
  4. Cruza com CPF (quando disponivel) pra elevar a confianca ou detectar conflito
     (mesmo nome, CPFs diferentes).
  5. Sugere um nome canonico por cluster (o "mais completo", ou o nome oficial do
     cadastro de clientes quando ha CPF batendo).
"""
import re
import unicodedata
from collections import defaultdict

from rapidfuzz import fuzz

DEFAULT_THRESHOLD = 88

# Coesao minima entre os vizinhos de um nome pra ele NAO ser tratado como
# "farol" (ver o passo 5 de find_clusters). Metade e o ponto natural: acima
# dela os vizinhos formam de fato um grupo e o nome curto e uma variante dele;
# abaixo, cada vizinho e uma coisa distinta e o nome curto so os estaria
# ligando por acidente.
FAROL_COESAO_MINIMA = 0.5


def strip_accents(text):
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# Lixo que o Escavador cola no campo de nome. Cada padrao abaixo ou some do
# meio do texto, ou corta dali pra frente (quando o que vem depois e outra
# pessoa/observacao, nao parte do nome).
_LIXO_CORTA_DAQUI = re.compile(
    r"\s+(?:REPRESENTAD[OA]\s+POR|ASSISTID[OA]\s+POR|DADOS\s+DE\s+QUALIFICA\w*)\b.*$",
    re.IGNORECASE | re.UNICODE,
)
# Sufixo de procurador federal ("... PRF VARA PREV", "... PRF TRF EXEC FISCAL").
# Observado na planilha (planilha real): e rotulo de orgao/atribuicao grudado no nome.
_LIXO_PRF = re.compile(r"\s+PRF(?:\s+[A-Z0-9]{1,6})*\s*$", re.IGNORECASE)
_LIXO_REMOVE = [
    re.compile(r"\([^)]*\)"),                                   # (qualquer aparte)
    re.compile(r"REGISTRAD[OA]\(?A?\)?\s+CIVILMENTE\s+COMO\s*", re.IGNORECASE),
    re.compile(r"NOME\s+SOCIAL\s*[:\-]?\s*", re.IGNORECASE),
    re.compile(r"[\d.\-/]{8,}"),                                # CPF/CNPJ/CNJ colado
    re.compile(r"^\s*-\s*"),                                    # hifen solto no inicio
]


def limpar_nome(text):
    """Tira do nome o que o Escavador colou junto e nao e nome.

    Portado de limpezanomes2.gs (regexLixo). Se a limpeza consumir o texto
    inteiro, devolve o original: melhor um nome sujo do que uma celula vazia.
    """
    if not text:
        return ""
    original = str(text)
    res = _LIXO_CORTA_DAQUI.sub("", original)
    res = _LIXO_PRF.sub("", res)
    for rgx in _LIXO_REMOVE:
        res = rgx.sub("", res)
    res = re.sub(r"\s+", " ", res).strip(" -;,")
    return res if res else original


# Particulas e sufixos que nao contam como inicial de nome.
_SIGLA_IGNORAR = {
    "DE", "DO", "DA", "DOS", "DAS", "E", "O", "A", "OS", "AS",
    "LTDA", "ME", "EPP", "EIRELI", "SA", "S/A", "S.A", "MEI",
    "FALIDO", "FALIDA", "FILIAL", "MATRIZ", "CNPJ",
}


def _iniciais(nome):
    """Devolve as duas leituras de iniciais de um nome: com todas as palavras
    e so com as significativas (sem DE/DA/LTDA/SA...)."""
    # normalize_name ja junta "S/A" num token so ("SA"); sem isso o sufixo
    # societario viraria duas iniciais falsas ("S" e "A") no meio da sigla.
    palavras = [p for p in normalize_name(nome).split() if p]
    if not palavras:
        return "", ""
    todas = "".join(p[0] for p in palavras)
    signif = "".join(p[0] for p in palavras if p not in _SIGLA_IGNORAR)
    return todas, signif


def expandir_sigla(text, pool):
    """Troca iniciais pelo nome completo, mas SO por um nome que existe na
    propria planilha (`pool`).

    Portado de buscarNomePorSiglaV2 (limpezanomes2.gs), com duas travas a
    mais que o original nao tem:
      - se mais de um nome do documento bate com as iniciais, nao expande
        (o original pegava o primeiro da lista, no chute);
      - se o proprio texto ja esta no pool, e nome de verdade, nao sigla.

    Sem correspondencia, devolve o texto intacto. E o oposto do
    `subset_initial`, que casava "D R B" com qualquer nome longo parecido.
    """
    if not text:
        return ""
    original = str(text).strip()
    if not original:
        return ""

    tokens = [t for t in re.split(r"[\s.]+", original) if t]
    if not tokens:
        return original
    compacta = "".join(tokens).upper()
    # Piso de 3 iniciais. Com duas letras, achar um unico nome que bata num
    # acervo de milhares e coincidencia, nao prova - e boa parte desses valores
    # sao nomes mascarados de menor em vara de familia, onde "expandir" errado
    # revela como nome de outra pessoa algo que estava protegido de proposito.
    parece_sigla = (
        (all(len(t) == 1 for t in tokens) and len(compacta) >= 3)
        or (len(tokens) == 1 and 3 <= len(compacta) <= 6 and original.upper() == original)
    )
    if not parece_sigla:
        return original

    alvo = strip_accents(compacta)
    achados = []
    for nome in pool:
        if not nome:
            continue
        if str(nome).strip().upper() == original.upper():
            return original          # o proprio texto e um nome do documento
        todas, signif = _iniciais(nome)
        if alvo and (alvo == todas or alvo == signif):
            if nome not in achados:
                achados.append(nome)
    if len(achados) == 1:
        return achados[0]
    return original                  # nenhum match, ou ambiguo - nao chuta


def normalize_name(text):
    if text is None:
        return ""
    text = strip_accents(str(text)).upper()
    text = re.sub(r"[^A-Z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # "S/A" (Sociedade Anonima) vira dois tokens de 1 letra ("S", "A") depois da
    # normalizacao - isso e perigoso, porque a regra de "inicial abreviada" (pra
    # casar coisas tipo "D" com "OTAVIO") passa a tratar esse "S" solto como se
    # fosse inicial de QUALQUER palavra que comece com S (ex: "SAFRA"), juntando
    # empresas totalmente diferentes so por causa do sufixo. Junta de volta num
    # token so ("SA") pra nao ser confundido com uma inicial de verdade.
    text = re.sub(r"\bS A\b", "SA", text)
    return text


def normalize_cpf(text):
    if text is None:
        return ""
    digits = re.sub(r"\D", "", str(text))
    return digits


def split_names(cell_value):
    """Divide uma celula 'NOME A;NOME B' em nomes individuais (originais, sem normalizar)."""
    if cell_value is None:
        return []
    parts = [p.strip() for p in str(cell_value).split(";")]
    return [p for p in parts if p]


# Trechos que indicam que o "nome" na verdade e uma mensagem de sistema do
# Escavador, nao um cliente/parte de verdade - ex: "PROCESSO ESTA EM SEGREDO DE
# JUSTICA 4" (o numero no final varia). Sempre que aparecer, deve ser cortado
# da celula, nunca vira sugestao de cliente nem contato.
JUNK_NAME_SUBSTRINGS = [
    "SEGREDO DE JUSTICA",
]


def is_junk_name(text):
    """True quando o texto nao e um nome de cliente/parte de verdade, e sim uma
    mensagem de sistema que acabou parando no campo de nome por engano."""
    norm = normalize_name(text)
    return any(sub in norm for sub in JUNK_NAME_SUBSTRINGS)


def _is_gender_suffix_swap(tok_a, tok_b):
    """Nomes proprios em portugues costumam ter um par masculino/feminino que so
    difere na letra final (O/A): ANTONIO/ANTONIA, MARIO/MARIA, PAULO/PAULA,
    EDUARDO/EDUARDA, CLAUDIO/CLAUDIA... Isso NUNCA pode contar como 'erro de
    digitacao' (mesmo com alta similaridade de caracteres), porque sao nomes de
    pessoas diferentes (generos diferentes), nao grafias alternativas da mesma."""
    if len(tok_a) != len(tok_b) or len(tok_a) < 2:
        return False
    if tok_a[:-1] != tok_b[:-1]:
        return False
    return {tok_a[-1], tok_b[-1]} == {"O", "A"}


def _is_doubled_fragment(tok_a, tok_b):
    """True quando um token e o outro com um pedaco dele proprio repetido no
    final - corrupcao classica de digitacao\\importacao, ex: "DASILVA" virando
    "DASILVASILVA" (DASILVA + ALMEIDA). Sem essa regra o par nao casa (a
    similaridade cai pra ~70%, abaixo do piso de erro de digitacao) e o mesmo
    cliente acaba em dois grupos separados - ja visto em dados reais.

    Exige que a sobra seja um SUFIXO do token menor (nao qualquer texto), pra
    nao juntar nomes que so por acaso comecam igual ("COSTA" x "COSTALIMA")."""
    short, long_ = (tok_a, tok_b) if len(tok_a) <= len(tok_b) else (tok_b, tok_a)
    if len(short) < 4 or not long_.startswith(short):
        return False
    resto = long_[len(short):]
    return len(resto) >= 3 and short.endswith(resto)


def _rejoin_split_tokens(tokens, outros, fuzzy_threshold=90):
    """Junta de volta uma palavra que foi PARTIDA EM DUAS, quando a juncao
    corresponde a um token do outro nome.

    Caso real (05/10/2026): "CONSTRUÇÕES" perdeu o Ç/Õ na importacao e virou
    dois tokens, "CONSTRUC" + "ES". Isso desalinha a comparacao token a token
    e "SOL NASCENTE CONSTRUC ES E EMPREENDIMENTOS EIRELI" nao casava com "SOL
    NASCENTE CONSTRUCOES E EMPREENDIMENTOS LTDA" - a mesma empresa, na mesma
    celula, em dois grupos diferentes.

    So junta quando a palavra inteira do OUTRO lado confirma a juncao (>=90%)
    e quando nenhuma das duas metades ja casava sozinha com ela - sem isso,
    juntar tokens viraria licenca pra casar qualquer coisa (ex: "SOL NASCENTE"
    nao pode virar "SOLNASCENTE" pra casar com "SOLBRAVO")."""
    if len(tokens) < 2 or not outros:
        return tokens
    saida = []
    i = 0
    while i < len(tokens):
        if i + 1 < len(tokens):
            juncao = tokens[i] + tokens[i + 1]
            alvo = max(outros, key=lambda o: fuzz.ratio(juncao, o))
            if (fuzz.ratio(juncao, alvo) >= fuzzy_threshold
                    and fuzz.ratio(tokens[i], alvo) < fuzzy_threshold
                    and fuzz.ratio(tokens[i + 1], alvo) < fuzzy_threshold):
                saida.append(juncao)
                i += 2
                continue
        saida.append(tokens[i])
        i += 1
    return saida


def _mesmo_radical(tok_a, tok_b, minimo=6, proporcao=0.70):
    """True quando duas palavras sao formas da MESMA palavra, compartilhando
    um radical longo: "ALIMENTACAO"/"ALIMENTOS" (radical "ALIMENT"),
    "SUCUMBENCIAIS"/"SUCUMBENCIA".

    Usado SO na checagem do ULTIMO token, nunca no primeiro. Caso real
    (05/10/2026): "NUTRI INDUSTRIA PAULISTA DE ALIMENTACAO LTDA" nao casava com
    "NUTRI INDUSTRIA PAULISTA DE ALIMENTOS" - tudo batia menos a ultima
    palavra, que fica em 80% de similaridade, abaixo do piso de 85 exigido na
    ponta.

    Os dois pisos (radical >= 6 letras E >= 70% da palavra menor) foram
    calibrados contra os pares que NAO podem casar: "SILVA"/"SILVEIRA" e
    "SANTOS"/"SANTANA" param no radical de 4, e "MARIA"/"MARIANA" para no de
    5. Por isso tambem a regra nao vale pro PRIMEIRO token: la
    "MARIA"/"MARIANA" e "LUZA"/"LUZANIR" tem exatamente a mesma forma de um
    nome curto que e prefixo do longo, e sao pessoas diferentes."""
    if not tok_a or not tok_b:
        return False
    menor = min(len(tok_a), len(tok_b))
    comum = 0
    for x, y in zip(tok_a, tok_b):
        if x != y:
            break
        comum += 1
    return comum >= minimo and comum >= proporcao * menor


def _token_match(tok_a, tok_b, fuzzy_threshold=85):
    """True se dois tokens (palavras de um nome) podem ser considerados 'o mesmo',
    incluindo o caso de inicial abreviada (ex: 'D' casa com 'OTAVIO') ou um pequeno
    erro de digitacao (ex: 'GUTIERREZ'/'GUTIERRES'), exceto quando for uma troca de
    genero O/A (ANTONIO/ANTONIA), que nunca conta como o mesmo nome.

    fuzzy_threshold: piso de similaridade (0-100) pro caso de "erro de
    digitacao" - controlavel pra ligar no controle de sensibilidade da tela
    (quanto mais baixo, mais permissivo)."""
    if tok_a == tok_b:
        return True, "exact"
    if _is_gender_suffix_swap(tok_a, tok_b):
        return False, None
    if len(tok_a) == 1 or len(tok_b) == 1:
        short, long_ = (tok_a, tok_b) if len(tok_a) <= len(tok_b) else (tok_b, tok_a)
        # "S" (e ocasionalmente "A") quase sempre e resto de "S/A" (Sociedade
        # Anonima) mal normalizado, nao a inicial de uma pessoa - sem essa
        # excecao, um "S" perdido bate como "inicial" de QUALQUER palavra que
        # comece com S (ex: "SAFRA"), juntando empresas diferentes so por causa
        # do sufixo (ja visto em dados reais: "BANCO BMG S S" grudando em
        # "BANCO SAFRA S/A" e "BANCO SANTANDER S/A").
        if len(short) == 1 and short != "S" and long_.startswith(short):
            return True, "initial"
        return False, None
    if _is_doubled_fragment(tok_a, tok_b):
        return True, "typo"
    if fuzz.ratio(tok_a, tok_b) >= fuzzy_threshold:
        return True, "typo"
    return False, None


def _edge_token_match(tok_a, tok_b):
    """Regra mais rigida usada para o PRIMEIRO token do nome (tipicamente o
    prenome). Nomes de pessoas diferentes costumam variar so por uma letra
    (ANTONIO/ANTONIA, PAULO/PAULA, MARIA/MARIO...), entao aqui NAO aceitamos o
    'typo' fuzzy generico - so exato ou inicial abreviada. O ULTIMO token
    (sobrenome) usa uma regra mais permissiva - ver _token_match, chamado
    diretamente em compare_names."""
    if tok_a == tok_b:
        return True
    short, long_ = (tok_a, tok_b) if len(tok_a) <= len(tok_b) else (tok_b, tok_a)
    if len(short) == 1 and long_.startswith(short):
        return True
    return False


PREPOSITIONS = {"DE", "DA", "DO", "DOS", "DAS", "E", "NO", "NA", "NOS", "NAS"}

# Sufixos de tipo societario. Na pratica aparecem trocados/inconsistentes pra
# a MESMA empresa entre uma mencao e outra (ex: uma vez registrada como LTDA,
# outra como S/A) - diferenca no sufixo nao deve impedir o match do nome
# principal da empresa.
COMPANY_SUFFIXES = {"LTDA", "ME", "EPP", "SA", "EIRELI", "EIRL", "MEI"}

# Artigo definido no INICIO de razao social (ex: "O Touro do Noroeste", "A
# Padaria...") - as vezes aparece, as vezes nao, pra descrever a MESMA empresa.
LEADING_ARTICLES = {"O", "A", "OS", "AS"}


def _strip_trailing_suffixes(tokens):
    """Remove sufixos societarios (LTDA, ME, EPP, S/A...) do final da lista de
    tokens, pra comparar so o nome principal da empresa. Nunca esvazia a lista
    por completo (mantem ao menos 1 token)."""
    if not tokens:
        return tokens
    stripped = list(tokens)
    while len(stripped) > 1 and stripped[-1] in COMPANY_SUFFIXES:
        stripped.pop()
    return stripped


def _strip_leading_article(tokens):
    """Remove um artigo definido (O/A/OS/AS) do INICIO do nome, se houver -
    pra "O TOURO DO NOROESTE..." bater com "TOURO DO NOROESTE...". So remove um
    unico token e nunca esvazia a lista."""
    if len(tokens) > 1 and tokens[0] in LEADING_ARTICLES:
        return tokens[1:]
    return tokens


def _strip_leading_acronym(tokens):
    """Remove a sigla colada no INICIO do nome, quando ela e exatamente as
    iniciais do que vem depois: "CEF CAIXA ECONOMICA FEDERAL" -> "CAIXA
    ECONOMICA FEDERAL", "INSS INSTITUTO NACIONAL DO SEGURO SOCIAL" ->
    "INSTITUTO NACIONAL DO SEGURO SOCIAL".

    Motivo: `compare_names` exige que o PRIMEIRO token bata (pra nome de
    pessoa, o prenome e a ancora de identidade). Uma sigla na frente desloca
    todos os tokens e a comparacao morria na porta - a mesma entidade
    aparecia duas vezes na MESMA celula sem ser unificada (caso real:
    "CAIXA ECONOMICA FEDERAL;CEF CAIXA ECONOMICA FEDERAL").

    A trava e a igualdade exata com as iniciais - "SUL" nao e sigla de
    "AMERICA SEGUROS" (iniciais "AS"), entao "SUL AMERICA SEGUROS" continua
    inteiro. Aceita as duas leituras de sigla, com e sem as preposicoes
    ("BCB" = Banco Central (do) Brasil), igual a `_iniciais`.
    """
    if len(tokens) < 3:
        # com so dois tokens, o "resto" vira uma palavra so e qualquer
        # inicial isolada casaria ("E EMPRESA" viraria "EMPRESA").
        return tokens
    candidata = tokens[0]
    if len(candidata) < 2 or not candidata.isalpha():
        return tokens
    resto = tokens[1:]
    todas, significativas = _iniciais(" ".join(resto))
    if candidata in (todas, significativas):
        return resto
    return tokens

# Sobrenomes extremamente comuns no Brasil. Um nome curto tipo "FRANCISCO DA SILVA"
# ou "MARIA PEREIRA" (prenome + so um desses sobrenomes) e generico demais: ele bate
# por "subconjunto" com dezenas de pessoas DIFERENTES que tem o mesmo prenome e o
# mesmo sobrenome comum, e viraria um "hub" que junta gente que nao tem nada a ver
# (ex: FRANCISCO ANTENOR DA SILVA e FRANCISCO ANTONIO DA SILVA nao sao a mesma pessoa,
# so passam pelo mesmo nome curto "FRANCISCO DA SILVA"). Por isso essa combinacao NAO
# e aceita como abreviacao/subconjunto - fica de fora do agrupamento automatico.
COMMON_SURNAMES = {
    "SILVA", "SANTOS", "SOUZA", "SOUSA", "OLIVEIRA", "PEREIRA", "RODRIGUES",
    "FERREIRA", "ALVES", "COSTA", "GOMES", "MARTINS", "ARAUJO", "MELO", "BARBOSA",
    "RIBEIRO", "ALMEIDA", "LIMA", "MOURA", "CARDOSO", "CARVALHO", "ROCHA", "DIAS",
    "MONTEIRO", "MENDES", "BARROS", "FREITAS", "MOREIRA", "NASCIMENTO", "FERNANDES",
    "GONCALVES", "TEIXEIRA", "MACHADO", "SOARES", "VIEIRA", "LOPES", "PINTO",
    "ANDRADE", "NUNES", "PEIXOTO", "CORREIA", "CAVALCANTE", "MORAIS", "MORAES",
    "CASTRO", "FARIAS", "AZEVEDO", "DUARTE", "PAIVA", "MEDEIROS", "SIQUEIRA",
    "BEZERRA", "LEITE", "CAMPOS", "XAVIER", "FONSECA", "GUIMARAES", "TAVARES",
    "BATISTA", "MAGALHAES", "SALES", "ALENCAR", "BRITO", "SANTANA", "MATOS",
}

# Palavras genericas de razao social/qualificador geografico que aparecem em
# MUITAS empresas diferentes e nao ajudam a distinguir uma da outra (ex: "BANCO
# DO BRASIL" x "BANCO SANTANDER DO BRASIL" nao sao o mesmo banco so por causa
# do "BRASIL" em comum). Tratada igual a um sobrenome comum pra efeito do guard
# de "generico demais".
GENERIC_QUALIFIER_WORDS = {
    "BRASIL", "BRASILEIRO", "BRASILEIRA",
}


def _content_tokens(tokens):
    return [t for t in tokens if t not in PREPOSITIONS]


def _too_generic_for_subset(short_content_tokens):
    """True quando o nome curto so tem a primeira palavra + UMA palavra
    extremamente comum/generica (sobrenome tipo 'FRANCISCO SILVA', ou
    qualificador tipo 'BANCO ... BRASIL') - generico demais, vira 'hub' que
    junta coisas sem nada a ver. Com 2+ tokens extras (ex: 'FABIANA OLIVEIRA
    SANTOS') a combinacao ja e especifica o suficiente mesmo que cada palavra
    isolada seja comum - so bloqueia o caso de exatamente 1 extra."""
    extra = short_content_tokens[1:]
    return len(extra) == 1 and (extra[0] in COMMON_SURNAMES or extra[0] in GENERIC_QUALIFIER_WORDS)


# Palavras genericas de ORGANIZACAO que, sozinhas, nao bastam pra ancorar o
# fallback de "mesma marca" dentro da mesma celula (ver _same_cell_brand_match)
# - ex: duas empresas BEM diferentes podem comecar com "BANCO", "GRUPO",
# "INSTITUTO"... isso nao e sinal de que sao a mesma coisa.
GENERIC_FIRST_WORDS = {
    "BANCO", "GRUPO", "INSTITUTO", "ASSOCIACAO", "COOPERATIVA", "CONDOMINIO",
    "FUNDACAO", "SINDICATO", "EMPRESA", "COMERCIO", "COMERCIAL",
}


def _looks_like_company(tokens):
    """True se a lista de tokens (antes de tirar sufixo) contem algum sufixo
    societario conhecido (LTDA, ME, EPP, S/A...) ou comeca por uma palavra
    generica de empresa (BANCO, CIA, ASSOCIACAO...) - sinal de que e nome de
    empresa, nao de pessoa fisica."""
    if any(t in COMPANY_SUFFIXES for t in tokens):
        return True
    return bool(tokens) and tokens[0] in GENERIC_FIRST_WORDS


def _same_cell_brand_match(tokens_a, tokens_b, content_a, content_b):
    """Fallback especifico pra nomes que apareceram na MESMA celula (ver
    find_clusters/same_row) - aceita com MENOS evidencia que as demais regras
    porque o contexto ja e forte (a propria planilha listou os dois nomes
    juntos, separados por ';', na mesma celula). Cobre o caso de filiais/
    unidades de uma mesma empresa com qualificador de cidade diferente,
    inclusive quando uma das variantes esta incompleta (sem NENHUM sufixo
    societario), ex:
      "O FACILITADOR GUARAPUAVA"  x  "O FACILITADOR LONDRINA ASSESSORIA LTDA"
      x  "O FACILITADOR ASSESSORIA LTDA"
    tres formas de escrever a mesma rede, uma delas sem sufixo nenhum - o
    subset-match normal (_ordered_subset_match) exige que os tokens do nome
    curto apareçam dentro do nome longo, e "GUARAPUAVA" nunca vai aparecer
    dentro de "LONDRINA ASSESSORIA LTDA" (sao palavras diferentes) - por isso
    precisa desse fallback a parte, olhando so pra marca em comum.

    So aceita quando:
      - pelo menos um dos dois lados tem sufixo societario conhecido (senao
        arriscaria juntar nome de PESSOA so por compartilhar o primeiro nome,
        que costuma ser bem mais comum entre pessoas diferentes do que entre
        marcas/empresas diferentes);
      - o primeiro token de conteudo (a "marca") e IDENTICO nos dois lados;
      - esse token nao e generico demais (nem palavra de organizacao tipo
        "BANCO"/"GRUPO", nem sobrenome comum tipo "SANTOS"/"SILVA") - senao
        juntaria empresas ou pessoas diferentes que so por acaso comecam
        parecido."""
    if not content_a or not content_b:
        return False
    if not (_looks_like_company(tokens_a) or _looks_like_company(tokens_b)):
        return False
    tok_a, tok_b = content_a[0], content_b[0]
    if tok_a != tok_b:
        return False
    if len(tok_a) < 4:
        return False
    if tok_a in GENERIC_FIRST_WORDS or tok_a in COMMON_SURNAMES:
        return False
    return True


def _positional_typo_match(tokens_a, tokens_b, per_token_threshold=70):
    """Compara nomes com o MESMO numero de tokens, posicao a posicao. Usado como
    ultimo recurso quando nao ha relacao de subconjunto (abreviacao) entre os nomes.

    So aceita como 'a mesma pessoa, so com erro de digitacao/grafia' quando no
    MAXIMO um token no meio do nome difere - e mesmo assim exige uma similaridade
    minima nesse token (per_token_threshold, controlavel pelo controle de
    sensibilidade da tela), pra pegar variantes de grafia reais (LUIZ/LUIS,
    ISAIAS/IZAIAS) sem deixar passar nomes do meio claramente diferentes
    (ex: ARMANDO x DAMIAO, ratio ~61 - pessoas diferentes que so coincidem no
    prenome e sobrenome)."""
    if len(tokens_a) != len(tokens_b):
        return False
    diffs = 0
    for ta, tb in zip(tokens_a, tokens_b):
        if ta == tb:
            continue
        if _is_gender_suffix_swap(ta, tb):
            return False
        if fuzz.ratio(ta, tb) < per_token_threshold:
            return False
        diffs += 1
    return diffs <= 1


def _ordered_subset_match(tokens_short, tokens_long, fuzzy_threshold=85):
    """Verifica se todos os tokens de `tokens_short` aparecem, na mesma ordem,
    dentro de `tokens_long` (permitindo tokens extras no meio de `tokens_long`).
    Usado para casar nomes truncados/abreviados, ex:
      ['GILMAR','O','ROCHA']  contra  ['GILMAR','OTAVIO','DA','ROCHA']
    Retorna (bateu: bool, usou_inicial: bool).
    """
    if not tokens_short:
        return False, False
    used_initial = False
    j = 0
    for tok in tokens_short:
        matched = False
        while j < len(tokens_long):
            ok, kind = _token_match(tok, tokens_long[j], fuzzy_threshold=fuzzy_threshold)
            j += 1
            if ok:
                matched = True
                if kind == "initial":
                    used_initial = True
                break
        if not matched:
            return False, False
    return True, used_initial


def _so_iniciais(tokens):
    """True quando o valor e so uma sequencia de iniciais - nome MASCARADO.

    "Q K", "Z A P", "L P M N", ou uma letra sozinha. Nao e nome incompleto: e
    nome deliberadamente oculto (segredo de justica, menor, vitima), do jeito
    que a planilha de uma pratica criminal traz.
    """
    return bool(tokens) and all(len(t.strip(".")) <= 1 for t in tokens)


def compare_names(norm_a, norm_b, threshold=DEFAULT_THRESHOLD, require_last_token=True):
    """Compara dois nomes ja normalizados.
    Retorna None se nao ha match, ou dict {score, reason} se ha.
    reason: 'exact' | 'fuzzy' | 'subset' | 'subset_initial'

    require_last_token=False relaxa a exigencia do ultimo token bater - usado na
    verificacao dentro da mesma celula, onde e comum um dos nomes ter uma sigla ou
    qualificador extra no final (ex: "BANCO CENTRAL DO BRASIL" x "BANCO CENTRAL DO
    BRASIL BACEN") que faria o ultimo token nao coincidir mesmo sendo a mesma parte.

    `threshold` (o controle de sensibilidade da tela, 70-98, padrao 88) tambem
    afeta o quanto de erro de digitacao se aceita no primeiro/ultimo token e
    nos tokens do meio - quanto mais baixo, mais permissivo (ex: VALDOMIR/
    VALDORI, SILVEIRA/SILVA). No padrao (88) o comportamento e identico ao que
    sempre foi (piso de 85 no primeiro/ultimo token, 70 nos do meio). Abaixar o
    controle pega mais variantes reais, mas tambem mais pares que so parecem
    a mesma pessoa por coincidencia (ex: PEREIRA/FERREIRA) - continuam so
    "sugestao" (nada e aplicado sem voce revisar e confirmar), entao o preco de
    abaixar o controle e revisar mais, nao aplicar errado."""
    if not norm_a or not norm_b:
        return None
    if norm_a == norm_b:
        return {"score": 100.0, "reason": "exact"}

    # Nome MASCARADO nao se compara com nada (ver _so_iniciais).
    #
    # Duas sequencias de inicial parecidas nao dizem nada sobre identidade, e a
    # regra de erro de digitacao - que existe pra pegar GUTIERREZ/GUTIERRES - tratava
    # inicial diferente como quase igual: na conta (planilha real), "Q K B L" casava com
    # "Q K S A" (B/S e L/A, uma letra cada) e cinco pessoas anonimizadas de
    # processo criminal viraram uma. Juntar duas delas seria AFIRMAR que duas
    # pessoas ocultadas sao a mesma, que e o oposto do que o dado diz.
    #
    # A checagem vem antes de qualquer tokenizacao de proposito, pra nao depender
    # das outras regras (sigla na frente, juncao de token partido) e pra fechar
    # tambem o caminho relaxado da mesma celula - que e justamente onde co-reus e
    # co-vitimas de um mesmo processo aparecem.
    #
    # Isso NAO atinge inicial no meio de nome de verdade ("GILMAR O ROCHA" x
    # "GILMAR OTAVIO ROCHA"), que continua casando: ali ha palavra inteira.
    if _so_iniciais(norm_a.split()) or _so_iniciais(norm_b.split()):
        return None

    edge_fuzzy = max(70, threshold - 3)
    # nunca deixa passar de 65, nem no controle mais baixo (70) - abaixo disso
    # reabriria coisas tipo ARMANDO/DAMIAO (ratio ~61, pessoas diferentes que so
    # coincidem no prenome e sobrenome).
    positional_floor = max(65, threshold - 18)

    tokens_a = _strip_leading_acronym(_strip_leading_article(norm_a.split()))
    tokens_b = _strip_leading_acronym(_strip_leading_article(norm_b.split()))
    # palavra partida em duas por erro de codificacao - ver _rejoin_split_tokens
    tokens_a = _rejoin_split_tokens(tokens_a, tokens_b)
    tokens_b = _rejoin_split_tokens(tokens_b, tokens_a)

    # Primeiro token (prenome) - aceita pequeno erro de digitacao (ex: VALDOMIR/
    # VALDORI), mas a troca de genero O/A (ANTONIO/ANTONIA) e sempre bloqueada
    # dentro de _token_match, nao importa o quao permissivo o limiar estiver.
    first_ok, _ = _token_match(tokens_a[0], tokens_b[0], fuzzy_threshold=edge_fuzzy)
    if not first_ok:
        return None

    # Sufixo societario (LTDA, S/A, ME...) e frequentemente registrado de forma
    # inconsistente pra mesma empresa - o resto da comparacao usa os tokens sem
    # esse sufixo, pra "VENDEXPRESS ... LIMPEZA LTDA" bater com "VENDEXPRESS ...
    # LIMPEZA S/A".
    core_a = _strip_trailing_suffixes(tokens_a)
    core_b = _strip_trailing_suffixes(tokens_b)

    # Tenta primeiro por subconjunto/abreviacao (nome curto contido, na ordem,
    # dentro do nome longo) - isso cobre tanto truncamento de pessoa quanto
    # qualificador extra de empresa (ex: "BANCO BRADESCO" dentro de "BANCO
    # BRADESCO FINANCIAMENTO"), sem exigir que o ULTIMO token bata, porque nesse
    # caso o "ultimo token" relevante pode ter mudado de posicao.
    #
    # A comparacao usa so os tokens de CONTEUDO (sem preposicao) dos DOIS lados,
    # nao so do lado escolhido como "curto" - isso cobre o caso de "UNIAO
    # FAZENDA NACIONAL" x "UNIAO DA NACIONAL": um tem a palavra "FAZENDA", o
    # outro tem a preposicao "DA" no mesmo lugar; sem isso, o "DA"/"FAZENDA" nao
    # bate contra nada do outro lado e a comparacao falhava dos dois jeitos,
    # dependendo de qual nome caia como "curto" (empate de tamanho bruto).
    content_a = _content_tokens(core_a)
    content_b = _content_tokens(core_b)
    short, long_ = (content_a, content_b) if len(content_a) <= len(content_b) else (content_b, content_a)
    if len(short) >= 2 and not _too_generic_for_subset(short):
        subset_ok, used_initial = _ordered_subset_match(short, long_, fuzzy_threshold=edge_fuzzy)
        if subset_ok:
            # Inicial abreviada ("D" casando com "OTAVIO") so faz sentido em
            # nome de PESSOA. Em nome de empresa, uma letra solta vira curinga
            # e gruda tudo: "BANCO B V FINANCEIRA SA" casava com BMG,
            # BRADESCO, BANKPAR e VOTORANTIM (o "B" bate com qualquer palavra
            # que comece com B, o "V" com qualquer uma que comece com V),
            # formando um grupo unico com bancos totalmente diferentes.
            if used_initial and (_looks_like_company(tokens_a) or _looks_like_company(tokens_b)):
                return None
            reason = "subset_initial" if used_initial else "subset"
            score = 92.0 if used_initial else 96.0
            return {"score": score, "reason": reason}

    # Sem relacao de subconjunto - so resta a via fuzzy/typo (nomes do mesmo
    # tamanho, no maximo 1 token diferente). Aqui sim o ultimo token (ja sem
    # sufixo societario) precisa bater - senao arrisca juntar gente/empresas
    # diferentes que so compartilham o prenome/primeira palavra.
    if require_last_token:
        last_ok, _ = _token_match(core_a[-1], core_b[-1], fuzzy_threshold=edge_fuzzy)
        if not last_ok and not _mesmo_radical(core_a[-1], core_b[-1]):
            return None

    if _positional_typo_match(core_a, core_b, per_token_threshold=positional_floor):
        score = fuzz.token_sort_ratio(norm_a, norm_b)
        if score >= threshold:
            return {"score": float(score), "reason": "fuzzy"}
    return None


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _blocking_key(norm_name):
    tokens = norm_name.split()
    if not tokens:
        return "?"
    return tokens[0][:2]


def build_occurrence_index(occurrences):
    """occurrences: lista de dicts {text, norm, source...}. Agrupa por norm."""
    by_norm = defaultdict(list)
    for occ in occurrences:
        by_norm[occ["norm"]].append(occ)
    return by_norm


def find_clusters(occurrences, cpf_by_norm=None, threshold=DEFAULT_THRESHOLD,
                   blacklist_pairs=None, confirmed_pairs=None):
    """
    occurrences: lista de dicts com pelo menos {text, norm} (e metadados de origem
      que sao apenas carregados junto, nao usados aqui).
    cpf_by_norm: dict norm_name -> set of cpfs normalizados (do cadastro de clientes).
    blacklist_pairs / confirmed_pairs: sets de frozenset({norm_a, norm_b}) vindos do
      rules_store, para nunca (ou sempre) juntar certo par.
    Retorna lista de clusters: cada um {members: [norm,...], reason, max_score}
    """
    blacklist_pairs = blacklist_pairs or set()
    confirmed_pairs = confirmed_pairs or set()
    cpf_by_norm = cpf_by_norm or {}

    unique_norms = sorted(set(occ["norm"] for occ in occurrences if occ["norm"]))

    uf = UnionFind()
    for n in unique_norms:
        uf.find(n)

    pair_info = {}  # frozenset({a,b}) -> {score, reason}

    def register_match(a, b, score, reason):
        if a == b:
            return
        key = frozenset((a, b))
        if key in blacklist_pairs:
            return
        prev = pair_info.get(key)
        if prev is None or score > prev["score"]:
            pair_info[key] = {"score": score, "reason": reason}
        # NAO une aqui: a uniao acontece no passo 5, depois da trava do efeito
        # farol. Unir na hora tornaria a trava impossivel, porque o estrago da
        # transitividade ja estaria feito quando desse pra perceber o padrao.

    # 1) pares confirmados manualmente em execucoes anteriores
    for key in confirmed_pairs:
        if key in blacklist_pairs:
            continue
        a, b = tuple(key)
        if a in uf.parent or b in uf.parent:
            register_match(a, b, 100.0, "confirmado")

    # 2) mesmo CPF, nomes com grafias diferentes -> match forte direto
    norms_by_cpf = defaultdict(set)
    for norm, cpfs in cpf_by_norm.items():
        for cpf in cpfs:
            if cpf:
                norms_by_cpf[cpf].add(norm)
    for cpf, norms in norms_by_cpf.items():
        norms = [n for n in norms if n in uf.parent or n in unique_norms]
        for i in range(len(norms)):
            for j in range(i + 1, len(norms)):
                register_match(norms[i], norms[j], 99.0, "mesmo_cpf")

    # 3) comparacao fuzzy com blocking por prefixo do primeiro token
    buckets = defaultdict(list)
    for n in unique_norms:
        buckets[_blocking_key(n)].append(n)

    for key, names in buckets.items():
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                if frozenset((a, b)) in blacklist_pairs:
                    continue
                result = compare_names(a, b, threshold=threshold)
                if result:
                    register_match(a, b, result["score"], result["reason"])

    # 4) nomes na MESMA celula (separados por ";" na mesma linha) - e muito comum
    # o mesmo cliente aparecer duas vezes na mesma linha com grafias diferentes
    # (ex: "BANCO CENTRAL DO BRASIL;BANCO CENTRAL DO BRASIL BACEN"). Como os dois
    # nomes ja vieram juntos no mesmo processo, a chance de ser a mesma parte e bem
    # maior - por isso aqui a comparacao e mais permissiva (nao exige que o ultimo
    # token bata, so o primeiro), pra pegar sigla/qualificador extra no final.
    # agrupa por (linha, coluna) - nao faz sentido comparar um nome da coluna
    # NOME DO CLIENTE com um da coluna PARTE CONTRARIA so por estarem na mesma
    # linha, entao cada coluna e checada separadamente dentro da linha.
    same_row = defaultdict(set)
    for occ in occurrences:
        if occ.get("source") == "escavador" and occ.get("norm"):
            same_row[(occ.get("row"), occ.get("column"))].add(occ["norm"])

    for norms_in_row in same_row.values():
        norms_in_row = sorted(norms_in_row)
        for i in range(len(norms_in_row)):
            for j in range(i + 1, len(norms_in_row)):
                a, b = norms_in_row[i], norms_in_row[j]
                if frozenset((a, b)) in blacklist_pairs:
                    continue
                if frozenset((a, b)) in pair_info:
                    continue
                result = compare_names(a, b, threshold=threshold, require_last_token=False)
                if result:
                    register_match(a, b, result["score"], "mesma_celula")
                    continue
                # nem a comparacao normal (mesmo relaxada) bateu - tenta o
                # fallback de "mesma marca" (filiais/unidades com qualificador
                # de cidade diferente, ou faltando o sufixo societario por
                # completo - ver _same_cell_brand_match).
                tokens_a = _strip_leading_article(a.split())
                tokens_b = _strip_leading_article(b.split())
                content_a = _content_tokens(_strip_trailing_suffixes(tokens_a))
                content_b = _content_tokens(_strip_trailing_suffixes(tokens_b))
                if _same_cell_brand_match(tokens_a, tokens_b, content_a, content_b):
                    register_match(a, b, 80.0, "marca_comum")

    # 5) trava do EFEITO FAROL, e so entao a uniao.
    #
    # Um nome curto pode casar por subconjunto/abreviacao com muitos nomes
    # longos que nao casam entre si. Ele nao e "um membro a mais" do grupo: e a
    # unica ponte que, via transitividade do union-find, funde todos num so.
    #
    # Visto na conta (planilha real) (21/10/2026): "MARIA DAS DORES" sozinha casava com
    # 16 "MARIA DAS DORES <sobrenomes>" que tinham ZERO de 120 pares casando
    # entre si - 17 mulheres diferentes viraram uma. O mesmo com "L P" (nome
    # mascarado de processo criminal, ligando J A C, J B C, J C M N...),
    # "MINISTERIO PUBLICO" (ligando MP Federal, MP do Trabalho e MP de MG) e
    # "AUTORIDADE POLICIAL".
    #
    # A regra: se os vizinhos de um nome quase nao casam entre si, aquele nome e
    # ambiguo - poderia ser qualquer um deles - e nao se junta a nenhum. E a
    # mesma disciplina que `expandir_sigla` ja aplicava a sigla ("se duas
    # pessoas do documento tem as mesmas iniciais, expandir seria chute").
    #
    # Par confirmado a mao e par de mesmo CPF sao autoridade e passam por cima:
    # ali nao ha o que adivinhar.
    autoridade = {"confirmado", "mesmo_cpf"}
    vizinhos = defaultdict(set)
    for key, info in pair_info.items():
        if info["reason"] in autoridade:
            continue
        a, b = tuple(key)
        vizinhos[a].add(b)
        vizinhos[b].add(a)

    arestas_de_farol = set()
    for nome, vs in vizinhos.items():
        if len(vs) < 2:
            continue  # com um vizinho so nao ha ambiguidade
        vl = sorted(vs)
        possiveis = len(vl) * (len(vl) - 1) // 2
        coesos = sum(1 for i, x in enumerate(vl) for y in vl[i + 1:]
                     if frozenset((x, y)) in pair_info)
        if coesos / possiveis < FAROL_COESAO_MINIMA:
            arestas_de_farol.update(frozenset((nome, v)) for v in vs)

    for key, info in pair_info.items():
        if key in arestas_de_farol and info["reason"] not in autoridade:
            continue
        a, b = tuple(key)
        uf.union(a, b)

    groups = defaultdict(list)
    for n in unique_norms:
        groups[uf.find(n)].append(n)

    # Grafias diferentes que normalizam pro MESMO valor (acento, caixa, espaco
    # extra...) sao garantidamente a mesma pessoa/empresa - mas como so existe
    # UMA norma (nao duas pra comparar), esse caso nunca teria cluster nenhum
    # pelas regras acima, e a inconsistencia (ex: "JOSE" numa linha, "JOSÉ"
    # noutra) passaria direto pro arquivo final sem o usuario nem ver. Junta
    # aqui as grafias originais por norma pra tambem sinalizar esse caso.
    texts_by_norm = defaultdict(set)
    for occ in occurrences:
        if occ.get("norm") and occ.get("text"):
            texts_by_norm[occ["norm"]].add(occ["text"])

    clusters = []
    for root, members in groups.items():
        has_spelling_variation = len(members) == 1 and len(texts_by_norm.get(members[0], ())) > 1
        if len(members) < 2 and not has_spelling_variation:
            continue
        if has_spelling_variation:
            best_score = 100.0
            reasons = {"mesmo_normalizado"}
        else:
            best_score = 0.0
            reasons = set()
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    info = pair_info.get(frozenset((members[i], members[j])))
                    if info:
                        best_score = max(best_score, info["score"])
                        reasons.add(info["reason"])
        conflict_cpfs = set()
        for m in members:
            for cpf in cpf_by_norm.get(m, set()):
                if cpf:
                    conflict_cpfs.add(cpf)
        clusters.append({
            "members": sorted(members),
            "score": round(best_score, 2),
            "reasons": sorted(reasons),
            "cpfs": sorted(conflict_cpfs),
            "cpf_conflict": len(conflict_cpfs) > 1,
        })

    clusters.sort(key=lambda c: (-c["score"], c["members"][0]))
    return clusters


# Marcadores de cargo/funcao que aparecem COLADOS no fim do nome na planilha
# de origem. Nao sao sobrenome: "ROBERVAL PINTO COELHO CARGO" e o mesmo
# ROBERVAL, com um rotulo de campo que vazou pro valor.
_CARGO_OU_FUNCAO = {
    "CARGO", "ADV", "ADVOGADO", "ADVOGADA", "PREFEITO", "PREFEITA", "VEREADOR",
    "VEREADORA", "PRESIDENTE", "DIRETOR", "DIRETORA", "SECRETARIO", "SECRETARIA",
    "GOVERNADOR", "GOVERNADORA", "DELEGADO", "DELEGADA", "ESPOLIO", "HERDEIRO",
    "HERDEIRA", "REPRESENTANTE", "RESPONSAVEL",
}

# Inicio de razao social de orgao publico. Orgao publico nao tem sufixo
# societario nem UF colada no nome.
_INICIO_ORGAO_PUBLICO = (
    "UNIAO", "ESTADO", "MUNICIPIO", "PREFEITURA", "FUNDACAO", "INSTITUTO",
    "CAIXA ECONOMICA", "DEFENSORIA", "MINISTERIO", "TRIBUNAL", "CONSELHO",
    "AGENCIA", "SUPERINTEND", "DEPARTAMENTO", "SECRETARIA", "UNIVERSIDADE",
    "CAMARA", "PROCURADORIA", "POLICIA", "JUIZO",
)

_SUFIXO_SOCIETARIO = {"SA", "LTDA", "EIRELI", "ME", "EPP", "MEI", "LIMITADA"}

# Orgao de nivel MUNICIPAL: a cidade no nome ja localiza, entao estado colado
# no fim e sobra. Separado de _INICIO_ORGAO_PUBLICO porque em orgao ESTADUAL o
# estado e a propria entidade.
_INICIO_ORGAO_MUNICIPAL = ("MUNICIPIO", "PREFEITURA", "CAMARA MUNICIPAL",
                           "SECRETARIA MUNICIPAL")

# Situacao juridica da empresa colada no nome ("BANCO CRUZEIRO DO SUL S/A
# FALIDO"). E estado processual, nao razao social: muda com o tempo e nao
# identifica a parte.
_STATUS_DA_EMPRESA = {
    "FALIDO", "FALIDA", "FALENCIA", "LIQUIDACAO", "LIQUIDANDO", "EXTINTO",
    "EXTINTA", "RECUPERACAO", "INATIVO", "INATIVA", "BAIXADO", "BAIXADA",
}

_UFS = {"AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
        "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
        "SP", "SE", "TO"}

# Estado escrito por extenso no fim do nome de orgao publico ("MUNICIPIO DE UBA
# MINAS GERAIS"): mesmo caso da UF abreviada, so com mais palavras.
_ESTADOS_POR_EXTENSO = (
    "ACRE", "ALAGOAS", "AMAPA", "AMAZONAS", "BAHIA", "CEARA",
    "DISTRITO FEDERAL", "ESPIRITO SANTO", "GOIAS", "MARANHAO", "MATO GROSSO",
    "MATO GROSSO DO SUL", "MINAS GERAIS", "PARA", "PARAIBA", "PARANA",
    "PERNAMBUCO", "PIAUI", "RIO DE JANEIRO", "RIO GRANDE DO NORTE",
    "RIO GRANDE DO SUL", "RONDONIA", "RORAIMA", "SANTA CATARINA", "SAO PAULO",
    "SERGIPE", "TOCANTINS",
)


def _ruim_como_canonico(text):
    """True quando a variante nao serve de NOME FINAL, mesmo sendo a mais longa.

    O token extra dessas formas nao completa o nome: ou e rotulo de campo que
    vazou (cargo, funcao), ou e sufixo que o tipo de parte nao tem (orgao
    publico com LTDA), ou ESTREITA um nome que era geral (orgao publico com
    local ou UF). Escolher a forma estreita como nome de todo o grupo e pior
    que escolher a geral: rotularia o processo de Sao Paulo como sendo de Juiz
    de Fora.

    Casos reais: contas (planilha real) (08/10/2026) e (planilha real) (21/10/2026).
    """
    norm = normalize_name(text)
    tokens = norm.split()
    if not tokens:
        return True

    if tokens[-1] in _CARGO_OU_FUNCAO:
        return True

    # Situacao juridica colada no fim ("BANCO CRUZEIRO DO SUL S/A FALIDO"): e
    # estado processual da empresa, nao razao social - muda com o tempo e nao
    # identifica a parte. Ver _STATUS_DA_EMPRESA.
    if tokens[-1] in _STATUS_DA_EMPRESA:
        return True

    # O artigo na frente nao pode esconder o orgao: "O ESTADO DE MINAS GERAIS
    # S/A" tem que cair na mesma regra que "ESTADO DO CEARA LTDA". Sem tirar o
    # artigo, o startswith falha e a forma com S/A ganharia por ser mais longa
    # - foi o que aconteceu em 45 celulas da conta (planilha real).
    sem_artigo = " ".join(_strip_leading_article(tokens))
    publico = any(sem_artigo.startswith(p) for p in _INICIO_ORGAO_PUBLICO)
    if publico:
        # Estado por extenso no fim de orgao MUNICIPAL ("MUNICIPIO DE UBA MINAS
        # GERAIS"): a cidade ja localiza o orgao, o estado e apendice.
        #
        # So vale pra orgao municipal de proposito: num orgao ESTADUAL o estado
        # E a entidade - "ESTADO DO CEARA" e o nome certo, nao um nome com
        # sobra, e tirar dali deixaria "ESTADO DO CEARA LTDA" ganhar por ser
        # mais longo.
        municipal = any(sem_artigo.startswith(p) for p in _INICIO_ORGAO_MUNICIPAL)
        if municipal and any(sem_artigo.endswith(" " + e) for e in _ESTADOS_POR_EXTENSO):
            return True
        if tokens[-1] in _SUFIXO_SOCIETARIO:
            return True
        if tokens[-1] in _UFS:
            return True
        # UF composta ("PR/SP") - a normalizacao tira a barra e deixa dois
        # tokens de UF seguidos no fim.
        if len(tokens) >= 2 and tokens[-1] in _UFS and tokens[-2] in _UFS:
            return True
        # qualificador de local ("... EM JUIZ DE FORA"): estreita o orgao.
        if "EM" in tokens[1:]:
            return True

    return False


def suggest_canonical(cluster_members, occ_by_norm, cpf_registry_name_by_cpf=None):
    """Escolhe o nome 'mais completo' entre as variantes de texto originais de um cluster.
    occ_by_norm: dict norm -> lista de occurrences (cada uma com 'text').
    cpf_registry_name_by_cpf: dict cpf -> nome oficial (do cadastro de clientes), tem prioridade.
    """
    cpf_registry_name_by_cpf = cpf_registry_name_by_cpf or {}

    texts_count = defaultdict(int)
    for norm in cluster_members:
        for occ in occ_by_norm.get(norm, []):
            texts_count[occ["text"]] += 1

    if not texts_count:
        return cluster_members[0] if cluster_members else ""

    def completeness(text):
        norm = normalize_name(text)
        tokens = norm.split()
        n_single = sum(1 for t in tokens if len(t) == 1)
        n_numeric = sum(1 for t in tokens if t.isdigit())
        # Forma que RESTRINGE em vez de completar (cargo colado, orgao publico
        # com sufixo societario, com UF ou com local) perde de qualquer forma
        # boa - ver _ruim_como_canonico. Vem primeiro na tupla porque nem o
        # nome mais longo deve ganhar quando o que o alonga e um rotulo.
        # Se TODAS as variantes forem ruins, empatam aqui e o desempate segue
        # pelos criterios de sempre, entao nunca devolve vazio.
        ruim = 1 if _ruim_como_canonico(text) else 0
        # nomes nunca deveriam ter numeros - se tiver (ex: CPF colado por engano no
        # campo nome na planilha de origem), isso e sinal de sujeira, nao de nome
        # "mais completo": penaliza pesado pra nao virar o sugerido.
        return (-ruim, -n_numeric, len(tokens) - n_single - n_numeric, len(norm), texts_count[text])

    best_text = max(texts_count.keys(), key=completeness)
    return best_text


def match_against_registry(value_norm, registry_texts, threshold=DEFAULT_THRESHOLD):
    """Compara um nome (ja normalizado) contra uma lista fixa de nomes 'oficiais'
    (ex: usuarios/responsaveis cadastrados no sistema). Diferente do clustering,
    aqui a lista oficial e a verdade - a funcao so acha, entre ela, o nome mais
    parecido (se houver), pra sugerir a troca.

    registry_texts: lista de strings (nomes oficiais, como aparecem no sistema).
    Retorna None se o valor ja bate exatamente com algum, ou dict
    {official_text, score, reason} com o melhor candidato, ou None se nada
    parecido o suficiente foi encontrado.
    """
    best = None
    for official in registry_texts:
        official_norm = normalize_name(official)
        if official_norm == value_norm:
            return None  # ja esta correto
        result = compare_names(value_norm, official_norm, threshold=threshold)
        if result and (best is None or result["score"] > best["score"]):
            best = {"official_text": official, "score": result["score"], "reason": result["reason"]}
    if best:
        return best

    # A lista de responsaveis costuma ser pequena e conhecida (a equipe do
    # escritorio) - diferente do clustering geral de clientes, aqui vale a pena
    # um criterio extra, mais permissivo: mesmo primeiro E ultimo nome que um
    # responsavel oficial, mesmo com o nome do meio bem diferente, e forte
    # indicio de erro de digitacao/selecao (ex: "ROBERTO CESAR DE MENEZES JUNIOR"
    # por engano no lugar de "ROBERTO ALVES DE MENEZES JUNIOR"). Fica marcado com
    # confianca mais baixa pra deixar claro que precisa de atencao extra.
    # Essa regra extra vale so pra nome de PESSOA. Em nome de empresa o
    # "primeiro e ultimo token iguais" nao diz nada: "BANCO ... S/A" bate com
    # qualquer outro "BANCO ... S/A", entao BRADESCO, SANTANDER, ITAU e
    # NORDESTE eram todos sugeridos como "BANCO DO BRASIL S/A" (com 60% de
    # confianca, mas ainda assim sugeridos - e "Aplicar todas as sugestoes"
    # fundiria bancos diferentes num so). O que distingue duas empresas mora
    # justamente no MEIO do nome, que e o pedaco que essa regra ignora.
    tokens_value = value_norm.split()
    if not tokens_value or _looks_like_company(tokens_value):
        return None
    for official in registry_texts:
        official_norm = normalize_name(official)
        tokens_official = official_norm.split()
        if not tokens_official or _looks_like_company(tokens_official):
            continue
        if (_edge_token_match(tokens_value[0], tokens_official[0])
                and _edge_token_match(tokens_value[-1], tokens_official[-1])):
            return {"official_text": official, "score": 60.0, "reason": "mesmo_prenome_sobrenome"}
    return None


# Palavras que, sozinhas (como token inteiro, nao substring), indicam que o
# "nome" e na verdade uma referencia a orgao/local do processo (tribunal, vara,
# comarca...), nao um cliente ou parte de verdade - ex: "1a VARA CIVEL DE SAO
# PAULO" ou "TRIBUNAL DE JUSTICA DO ESTADO DE SP" as vezes acabam coladas no
# campo de nome por engano.
# Palavras que sozinhas ja denunciam orgao julgador: nao aparecem em nome de
# pessoa nem em razao social de verdade.
COURT_STRONG_KEYWORDS = {
    "TRIBUNAL", "COMARCA", "JUIZADO", "FORO", "FORUM", "JUIZO",
    "ESCRIVANIA", "CARTORIO",
}

# Palavras que sugerem orgao mas NAO bastam sozinhas - exigem uma segunda
# palavra do conjunto (forte ou fraca). "VARA" saiu das fortes por isso: o
# Escavador cola sufixos como "PRF VARA PREV" no nome de procurador federal,
# e a regra antiga (uma palavra so) removia a pessoa junto com as varas.
# Ideia portada do Apps Script "Automações advbox" (limpezanomes2.gs), que
# exige duas palavras isoladas do mesmo pool.
#
# Divididas em duas camadas porque "duas fracas quaisquer" e frouxo demais:
# "SERVICO NACIONAL DE APRENDIZAGEM INDUSTRIAL DEPARTAMENTO REGIONAL DO
# DISTRITO FEDERAL" (o SENAI) bate REGIONAL + FEDERAL e nao e vara nenhuma -
# sao so adjetivos genericos de instituicao. Exigir pelo menos UMA palavra
# especifica de Judiciario evita isso sem perder "1A VARA FEDERAL DE DUQUE DE
# CAXIAS RJ" (VARA e especifica, FEDERAL so reforca).
COURT_WEAK_KEYWORDS_ESPECIFICAS = {
    "VARA", "CIVEL", "CRIMINAL", "FAMILIA", "SUCESSOES", "ORFAOS",
    "TRABALHO", "EMPRESARIAL", "FISCAL", "FISCAIS", "EXECUCOES",
    "JUDICIARIA", "JUDICIARIO", "SUBSECAO", "SECAO", "DISTRIBUIDOR",
    "PREVIDENCIARIA", "INFANCIA", "JUVENTUDE", "TURMA", "REGIAO",
}
# So reforcam uma palavra especifica ao lado - sozinhas (ou entre si) nao
# provam nada, aparecem o tempo todo em nome de orgao publico/empresa que
# nao e vara nem tribunal.
COURT_WEAK_KEYWORDS_GENERICAS = {"FEDERAL", "ESTADUAL", "REGIONAL"}
COURT_WEAK_KEYWORDS = COURT_WEAK_KEYWORDS_ESPECIFICAS | COURT_WEAK_KEYWORDS_GENERICAS

# Titulos de magistrado - quando o "nome" comeca com um desses (opcionalmente
# precedido de um tratamento tipo "MM"/"EXMO"/"DR"), e o nome de um juiz ou
# desembargador que apareceu no campo errado, nao um cliente/parte de verdade
# (ex: "JUIZ PAULO..." ou "JUIZA ANA...").
JUDGE_TITLE_TOKENS = {"JUIZ", "JUIZA", "DESEMBARGADOR", "DESEMBARGADORA", "MAGISTRADO", "MAGISTRADA"}
JUDGE_TREATMENT_TOKENS = {"MM", "MMA", "EXMO", "EXMA", "DR", "DRA"}

# Frases institucionais genericas (orgao do processo, nao cliente/parte de
# verdade) que só fazem sentido como sequencia de tokens - "JUSTICA" ou
# "PUBLICA" sozinhos apareceriam demais em nomes reais (ex: "FAZENDA PUBLICA"
# seria outro caso, nao cobrir sozinho), entao casa a frase inteira em
# qualquer posicao do valor (ex: "JUIZO DA JUSTICA PUBLICA" tambem entra).
INSTITUTIONAL_PHRASES = [
    ("JUSTICA", "PUBLICA"),
]


def _contains_phrase(tokens, phrase):
    n = len(phrase)
    return any(tuple(tokens[i:i + n]) == phrase for i in range(len(tokens) - n + 1))


def classify_court_or_judge(text):
    """Detecta se um valor no campo de nome (Cliente/Parte Contraria) e na
    verdade referencia a tribunal/vara/comarca, a um juiz/desembargador, ou a
    uma frase institucional generica (ex: "justica publica") - nao um cliente
    ou parte de verdade. So sinaliza pra revisao - nunca remove sozinho (ver
    find_court_or_judge_names / decisao do usuario na tela).
    Retorna 'tribunal' | 'juiz' | 'institucional' | None. Usa tokens inteiros
    (nao substring), pra nao confundir palavra parecida dentro de um nome de
    verdade."""
    norm = normalize_name(text)
    if not norm:
        return None
    tokens = norm.split()
    # Magistrado vem ANTES de tribunal: "JUIZ DA 11 VARA FEDERAL..." e juiz,
    # nao vara - quem manda e como o valor comeca.
    if tokens[0] in JUDGE_TITLE_TOKENS:
        return "juiz"
    if len(tokens) > 1 and tokens[0] in JUDGE_TREATMENT_TOKENS and tokens[1] in JUDGE_TITLE_TOKENS:
        return "juiz"
    if any(t in COURT_STRONG_KEYWORDS for t in tokens):
        return "tribunal"
    # Duas ou mais palavras fracas (contando as fortes) - uma so nao condena,
    # senao "... PRF VARA PREV" levaria junto o nome da pessoa. E precisa ter
    # pelo menos UMA especifica de Judiciario - duas genericas (REGIONAL,
    # FEDERAL...) sozinhas nao provam nada, so descrevem uma instituicao
    # qualquer (ver COURT_WEAK_KEYWORDS_GENERICAS acima).
    tokens_set = set(tokens)
    tem_especifica = bool(tokens_set & COURT_WEAK_KEYWORDS_ESPECIFICAS) or \
        bool(tokens_set & COURT_STRONG_KEYWORDS)
    fracas = sum(1 for t in tokens_set
                 if t in COURT_WEAK_KEYWORDS or t in COURT_STRONG_KEYWORDS)
    if fracas >= 2 and tem_especifica:
        return "tribunal"
    if any(_contains_phrase(tokens, phrase) for phrase in INSTITUTIONAL_PHRASES):
        return "institucional"
    return None


def find_court_or_judge_names(occurrences):
    """Acha valores em NOME DO CLIENTE / PARTE CONTRARIA (planilha do Escavador)
    que parecem ser, na verdade, nome de tribunal/vara/comarca ou de juiz/
    desembargador. Retorna lista de dicts:
      {norm, text, reason, cliente_rows, parte_rows, n_cliente, n_parte_contraria}
    """
    cliente_rows = defaultdict(list)
    parte_rows = defaultdict(list)
    reason_by_norm = {}
    text_by_norm = {}
    for occ in occurrences:
        if occ.get("source") != "escavador" or not occ.get("norm"):
            continue
        reason = classify_court_or_judge(occ["text"])
        if not reason:
            continue
        norm = occ["norm"]
        reason_by_norm[norm] = reason
        text_by_norm.setdefault(norm, occ["text"])
        if occ.get("column") == "parte_contraria":
            parte_rows[norm].append(occ["row"])
        else:
            cliente_rows[norm].append(occ["row"])

    results = []
    for norm in sorted(reason_by_norm):
        c_rows = sorted(set(cliente_rows.get(norm, [])))
        p_rows = sorted(set(parte_rows.get(norm, [])))
        results.append({
            "norm": norm,
            "text": text_by_norm[norm],
            "reason": reason_by_norm[norm],
            "cliente_rows": c_rows,
            "parte_rows": p_rows,
            "n_cliente": len(c_rows),
            "n_parte_contraria": len(p_rows),
        })
    results.sort(key=lambda x: -(x["n_cliente"] + x["n_parte_contraria"]))
    return results


def find_cliente_parte_overlap(occurrences):
    """Acha nomes que aparecem tanto como NOME DO CLIENTE quanto como PARTE
    CONTRARIA em algum lugar da planilha - seja na MESMA linha (erro classico de
    cadastro: o nome foi listado nos dois lados do mesmo processo) seja em
    linhas DIFERENTES (ex: uma concessionaria/banco que e sempre re em varios
    processos e, numa linha especifica, foi cadastrada por engano como
    cliente). Comparacao por nome normalizado exato.

    Retorna lista de dicts:
      {norm, text, cliente_rows: [...], parte_rows: [...], n_cliente, n_parte_contraria, same_row}
    """
    cliente_rows = defaultdict(list)
    parte_rows = defaultdict(list)
    for occ in occurrences:
        if occ.get("source") != "escavador" or not occ.get("norm"):
            continue
        if occ.get("column") == "cliente":
            cliente_rows[occ["norm"]].append((occ["row"], occ["text"]))
        elif occ.get("column") == "parte_contraria":
            parte_rows[occ["norm"]].append((occ["row"], occ["text"]))

    results = []
    for norm in sorted(set(cliente_rows) & set(parte_rows)):
        c_rows = sorted(set(r for r, _ in cliente_rows[norm]))
        p_rows = sorted(set(r for r, _ in parte_rows[norm]))
        results.append({
            "norm": norm,
            "text": cliente_rows[norm][0][1],
            "cliente_rows": c_rows,
            "parte_rows": p_rows,
            "n_cliente": len(cliente_rows[norm]),
            "n_parte_contraria": len(parte_rows[norm]),
            "same_row": bool(set(c_rows) & set(p_rows)),
        })
    results.sort(key=lambda x: -(x["n_cliente"] + x["n_parte_contraria"]))
    return results


def find_advbox_only_candidates(all_occ, clusters):
    """Acha nomes vindos do ADVBOX (occurrences com source comecando com
    'advbox_') que nao tem NENHUM correspondente local (nem identico, nem
    parecido o suficiente pra ter caido no mesmo cluster que um nome vindo
    do Escavador/Clientes). Usado pra sugerir "esse nome so existe na conta
    do ADVBOX, quer adicionar na planilha de clientes?" - ver app.py
    /api/analyze. Quando HA correspondente (direto ou por parecenca), o
    nome do ADVBOX ja aparece como mais uma variante dentro do cluster
    normal (secao 3), nao precisa de tratamento a parte aqui.
    Retorna lista de dicts {norm, text, source}."""
    norm_to_cluster = {}
    for c in clusters:
        for m in c["members"]:
            norm_to_cluster[m] = c

    local_norms = {occ["norm"] for occ in all_occ if occ.get("source") in ("escavador", "clientes")}

    seen = set()
    results = []
    for occ in all_occ:
        source = occ.get("source") or ""
        if not source.startswith("advbox"):
            continue
        norm = occ["norm"]
        if norm in seen:
            continue
        if norm in local_norms:
            # match EXATO (mesma norma) com Escavador/Clientes - nao passa
            # por find_clusters (so cluster nomes DIFERENTES e parecidos,
            # nao ha o que decidir quando a norma ja e identica), entao
            # nunca aparece em norm_to_cluster. Sem esse check direto,
            # esse nome ficava listado como "so existe no ADVBOX" mesmo
            # ja tendo o correspondente exato aqui.
            continue
        cluster = norm_to_cluster.get(norm)
        if cluster and any(m in local_norms for m in cluster["members"]):
            continue
        seen.add(norm)
        results.append({"norm": norm, "text": occ["text"], "source": source})
    results.sort(key=lambda x: x["text"])
    return results


def find_financeiro_orphans(all_occ, clusters):
    """Acha nomes da planilha de FINANCEIRO que nao existem nem na planilha de
    Clientes nem na de Processos - nem com a grafia identica, nem parecidos o
    bastante pra terem caido no mesmo cluster de homonimos que um nome de la.

    Quando HA correspondente (identico ou por parecenca), nao entra aqui: se e
    identico ja esta certo, e se e so parecido o nome ja aparece como mais uma
    variante dentro do grupo de homonimos (secao 3), onde a padronizacao e
    decidida junto com as outras planilhas.

    Sobra este caso: cobranca lancada no financeiro pra alguem que nunca foi
    cadastrado como cliente nem aparece em processo. Ai o nome nao deveria
    ocupar a coluna NOME DO CLIENTE (viraria cadastro fantasma na importacao),
    e a decisao oferecida e mover esse nome pra DESCRICAO do lancamento - ver
    excel_io.apply_financeiro.
    Retorna lista de dicts {norm, text, rows, count}."""
    norm_to_cluster = {}
    for c in clusters:
        for m in c["members"]:
            norm_to_cluster[m] = c

    local_norms = {occ["norm"] for occ in all_occ if occ.get("source") in ("escavador", "clientes")}

    by_norm = {}
    for occ in all_occ:
        if occ.get("source") != "financeiro":
            continue
        norm = occ["norm"]
        if norm in local_norms:
            # match exato com Clientes/Processos - nao passa por find_clusters
            # (que so agrupa nomes DIFERENTES e parecidos), entao precisa deste
            # check direto, senao apareceria como "orfao" tendo correspondente.
            continue
        cluster = norm_to_cluster.get(norm)
        if cluster and any(m in local_norms for m in cluster["members"]):
            continue
        entry = by_norm.setdefault(norm, {"norm": norm, "text": occ["text"], "rows": []})
        if occ.get("row") is not None:
            entry["rows"].append(occ["row"])

    results = []
    for entry in by_norm.values():
        entry["rows"] = sorted(set(entry["rows"]))
        entry["count"] = len(entry["rows"])
        results.append(entry)
    results.sort(key=lambda x: x["text"])
    return results


def find_advbox_field_conflicts(occ_by_norm):
    """Compara, campo a campo, clientes que tem o MESMO nome (norma
    identica) cadastrados tanto na planilha de Clientes quanto na conta do
    ADVBOX. Quando os dois lados tem valor preenchido pro mesmo campo (ex:
    CELULAR) e esse valor e DIFERENTE, e um conflito - nao da pra saber
    automaticamente qual esta certo, entao e sinalizado pra revisao (nunca
    aplicado sozinho). Campos que so um dos lados tem (o outro vazio) NAO
    sao conflito - esses sao preenchidos direto (ver app.py
    _advbox_fields_for_norms/field_updates).
    Dois casos parecem conflito mas nao sao, entao nao entram na lista:
    (a) mesmo numero de telefone/celular escrito com formatacao diferente
    (com/sem parenteses e traco) - mesmo dado, nada pra revisar; (b) um
    valor e prefixo exato do outro (ex: endereco local truncado, ADVBOX
    tem a versao completa) - aqui o ADVBOX so "ultrapassa" o que ja existe,
    entao e complemento automatico (ver excel_io.apply_clientes), nao
    conflito.
    Retorna lista de dicts {norm, text, field, local_value, advbox_value}."""
    conflicts = []
    for norm, occs in occ_by_norm.items():
        clientes_occ = next((o for o in occs if o.get("source") == "clientes"), None)
        advbox_occ = next((o for o in occs if o.get("source") == "advbox_pessoas"), None)
        if not clientes_occ or not advbox_occ:
            continue
        local_fields = clientes_occ.get("fields") or {}
        advbox_fields = advbox_occ.get("fields") or {}
        for field, advbox_value in advbox_fields.items():
            local_value = local_fields.get(field)
            if not local_value or not advbox_value:
                continue
            local_norm_text = re.sub(r"\s+", " ", local_value.strip()).upper()
            advbox_norm_text = re.sub(r"\s+", " ", advbox_value.strip()).upper()
            if local_norm_text == advbox_norm_text:
                continue
            if field in ("celular", "telefone"):
                local_digits = re.sub(r"\D", "", local_value)
                advbox_digits = re.sub(r"\D", "", advbox_value)
                if local_digits and local_digits == advbox_digits:
                    continue
            if advbox_norm_text.startswith(local_norm_text) or local_norm_text.startswith(advbox_norm_text):
                continue
            conflicts.append({
                "norm": norm,
                "text": clientes_occ["text"],
                "field": field,
                "local_value": local_value,
                "advbox_value": advbox_value,
            })
    conflicts.sort(key=lambda c: (c["text"], c["field"]))
    return conflicts


def find_clientes_duplicates(clientes_rows, threshold=DEFAULT_THRESHOLD):
    """Acha linhas DUPLICADAS dentro da propria planilha de Clientes - nao
    cruza com Escavador nem ADVBOX, e so entre as linhas de clientes.
    Dois grupos: (a) EXATAS - mesma norma (nome) em 2+ linhas, classificadas
    por CPF (mesmo CPF nos dois lados confirma ser a mesma pessoa; CPF
    diferente indica que provavelmente NAO e; sem CPF em nenhum lado fica
    indefinido - revisar com calma); (b) PARECIDAS - nomes parecidos mas
    nao identicos (via find_clusters), podem ser a mesma pessoa com grafia
    diferente ou so uma coincidencia de nome.
    Retorna (exact_groups, fuzzy_groups):
      exact_groups: [{"norm", "status", "rows": [{"row","text","cpf","fields","suggested_keep"}]}]
      fuzzy_groups: [{"score","reasons","rows": [{"row","text","cpf","fields"}]}]
    """
    by_norm = defaultdict(list)
    for r in clientes_rows:
        by_norm[r["norm"]].append(r)
    exact_norm_groups = {norm: rs for norm, rs in by_norm.items() if len(rs) > 1}

    def row_view(r):
        return {"row": r["row"], "text": r["text"], "cpf": r.get("cpf_raw") or None, "fields": r.get("fields") or {}}

    def cpf_status(group_rows):
        cpfs = {r["cpf_norm"] for r in group_rows if r.get("cpf_norm")}
        if len(cpfs) == 0:
            return "sem_cpf"
        if len(cpfs) == 1:
            return "mesmo_cpf"
        return "cpf_diferente"

    def best_row(group_rows):
        return max(group_rows, key=lambda r: len(r.get("fields") or {}) + (1 if r.get("cpf_norm") else 0))

    exact_groups = []
    for norm, rows in sorted(exact_norm_groups.items(), key=lambda kv: kv[1][0]["text"]):
        status = cpf_status(rows)
        keep = best_row(rows)
        exact_groups.append({
            "norm": norm,
            "status": status,
            "rows": [dict(row_view(r), suggested_keep=(r is keep)) for r in rows],
        })

    cpf_by_norm = defaultdict(set)
    for r in clientes_rows:
        if r.get("cpf_norm"):
            cpf_by_norm[r["norm"]].add(r["cpf_norm"])

    occ_like = [
        {"text": r["text"], "norm": r["norm"], "row": r["row"], "source": "clientes"}
        for r in clientes_rows
    ]
    clusters = find_clusters(occ_like, cpf_by_norm=cpf_by_norm, threshold=threshold,
                              blacklist_pairs=set(), confirmed_pairs=set())

    fuzzy_groups = []
    for c in clusters:
        if all(m in exact_norm_groups for m in c["members"]):
            continue  # ja cobertas pelas exatas, nao repete
        rows = [r for m in c["members"] for r in by_norm.get(m, [])]
        if not rows:
            continue
        fuzzy_groups.append({
            "score": c["score"],
            "reasons": c["reasons"],
            "rows": [row_view(r) for r in rows],
        })

    return exact_groups, fuzzy_groups


CATEGORY_MATCH_THRESHOLD = 80.0

# Palavras que sao so conector/gramatica em rotulo de TIPO/GRUPO DE ACAO -
# tirar elas do rotulo NUNCA muda o sentido juridico da categoria. Qualquer
# OUTRA palavra que sobrar depois de tirar essas e tratada como parte do
# SENTIDO da categoria, mesmo se curta - ver find_label_clusters pra saber
# por que (dado real mostrou contencao/fuzzy sendo perigosa demais aqui).
LABEL_FILLER_WORDS = PREPOSITIONS | {
    "ACAO", "ACOES", "PROCESSO", "PROCESSOS", "C", "CC",
}


def match_category_against_registry(value_norm, registry_texts, threshold=CATEGORY_MATCH_THRESHOLD):
    """Igual a match_against_registry, mas pra ROTULOS DE CATEGORIA (TIPO DE
    ACAO / GRUPO DE ACAO) - nao pra nome de pessoa.

    A diferenca importante: em nome de pessoa, um nome ser parte do outro NAO
    pode virar match ("SILVA" nao e "JOAO DA SILVA"), e por isso o motor de
    nomes bloqueia esse caso. Em rotulo de categoria e o contrario - um ser
    parte do outro e justamente o caso mais comum de mesma coisa escrita de
    dois jeitos ("CONSUMIDOR" e "DIREITO DO CONSUMIDOR", "ALIMENTOS" e
    "FIXACAO DE ALIMENTOS"). Por isso aqui a comparacao usa token_set_ratio,
    que da 100 quando um contem o outro, e mesmo assim continua baixo pra
    categorias de verdade diferentes ("DANO AMBIENTAL" x "DANO MORAL" ~67,
    "PENAL" x "PREVIDENCIARIO" ~42), ficando abaixo do limiar.

    Retorna None se ja bate exatamente com algum oficial (ou se nada passou do
    limiar), ou dict {official_text, score, reason}.
    """
    def content_tokens(text):
        return {t for t in text.split() if t not in PREPOSITIONS}

    value_tokens = content_tokens(value_norm)
    if not value_tokens:
        return None

    best = None
    for official in registry_texts:
        official_norm = normalize_name(official)
        if official_norm == value_norm:
            return None  # ja esta correto
        official_tokens = content_tokens(official_norm)
        if not official_tokens:
            continue
        # exige pelo menos uma palavra de conteudo em comum - sem isso, dois
        # rotulos sem nenhuma relacao poderiam pontuar alto so por acaso de
        # letras parecidas.
        if not (value_tokens & official_tokens):
            continue
        score = max(
            fuzz.token_set_ratio(value_norm, official_norm),
            fuzz.token_sort_ratio(value_norm, official_norm),
        )
        if score < threshold:
            continue
        if value_tokens <= official_tokens or official_tokens <= value_tokens:
            reason = "contido"
        else:
            reason = "parecido"
        if best is None or score > best["score"]:
            best = {"official_text": official, "score": float(score), "reason": reason}
    return best


def find_dirty_names(occurrences):
    """Nomes da planilha que estao sujos ou abreviados demais.

    Dois casos, nessa ordem de prioridade:
      - "lixo": o Escavador colou algo que nao e nome (ver `limpar_nome`);
      - "sigla": o valor sao iniciais que batem, sem ambiguidade, com UM nome
        que existe na propria planilha (ver `expandir_sigla`).

    So sugere - quem decide e o usuario na tela, igual as varas/juizes.
    Retorna [{norm, texto, sugerido, motivo, cliente_rows, parte_rows,
    n_cliente, n_parte_contraria}].
    """
    cliente_rows = defaultdict(list)
    parte_rows = defaultdict(list)
    text_by_norm = {}
    ordem = []
    for occ in occurrences:
        if occ.get("source") != "escavador" or not occ.get("norm"):
            continue
        norm = occ["norm"]
        if norm not in text_by_norm:
            text_by_norm[norm] = occ["text"]
            ordem.append(norm)
        if occ.get("column") == "parte_contraria":
            parte_rows[norm].append(occ["row"])
        else:
            cliente_rows[norm].append(occ["row"])

    # O pool da expansao de sigla e a propria planilha, sem os nomes que ja
    # estao sujos - expandir uma sigla PARA um nome com lixo colado so trocaria
    # um problema por outro.
    pool = [t for t in text_by_norm.values() if limpar_nome(t) == t]

    # Em que processos (linhas) cada nome aparece - usado pra corroborar a
    # expansao de sigla logo abaixo.
    linhas_por_norm = defaultdict(set)
    for occ in occurrences:
        if occ.get("source") == "escavador" and occ.get("norm"):
            linhas_por_norm[occ["norm"]].add(occ.get("row"))

    results = []
    for norm in ordem:
        texto = text_by_norm[norm]
        limpo = limpar_nome(texto)
        if limpo != texto:
            motivo, sugerido = "lixo", limpo
        else:
            # o proprio valor sai do pool: senao `expandir_sigla` o reconhece
            # como "nome de verdade do documento" e desiste de expandir.
            expandido = expandir_sigla(texto, [t for t in pool if t != texto])
            if expandido == texto:
                continue
            # INICIAIS SEPARADAS exigem corroboracao: a sigla e o nome inteiro
            # tem que estar no MESMO processo.
            #
            # A distincao e entre duas coisas que parecem a mesma:
            #   - sigla CONTIGUA ("MARF", "CMMP", "BBF") - alguem abreviou um
            #     nome ao digitar. Nao ha convencao de sigilo nisso, e a
            #     checagem de ambiguidade de `expandir_sigla` da conta;
            #   - iniciais SEPARADAS ("Z C P", "J D M C") - e a convencao de
            #     MASCARAMENTO do dado judicial: vitima, menor, segredo de
            #     justica.
            #
            # Pra forma separada, "inequivoco no documento" nao e evidencia.
            # Num acervo grande quase toda sequencia de 3 iniciais acha UM nome
            # com aquelas letras por acaso: na conta (planilha real) (3.016 processos),
            # das 28 siglas expandidas 27 tinham o nome sugerido em processo
            # NENHUM em comum - inclusive 'T M S' -> 'TOKIO MARINE SEGURADORA
            # S/A' e 'A C B' -> 'APPLE COMPUTER BRASIL LTDA'.
            #
            # E o preco do erro e alto nas duas direcoes: a expansao errada
            # troca o nome de uma parte, e a expansao certa revela o que o
            # processo oculta.
            #
            # Mesmo processo e a situacao pra qual a regra foi feita: o
            # Escavador abreviou numa coluna um nome que esta inteiro na outra.
            if _so_iniciais(norm.split()) and not (
                    linhas_por_norm.get(norm, set())
                    & linhas_por_norm.get(normalize_name(expandido), set())):
                continue
            motivo, sugerido = "sigla", expandido
        c_rows = sorted(set(cliente_rows.get(norm, [])))
        p_rows = sorted(set(parte_rows.get(norm, [])))
        results.append({
            "norm": norm,
            "texto": texto,
            "sugerido": sugerido,
            "motivo": motivo,
            "cliente_rows": c_rows,
            "parte_rows": p_rows,
            "n_cliente": len(c_rows),
            "n_parte_contraria": len(p_rows),
        })
    results.sort(key=lambda x: -(x["n_cliente"] + x["n_parte_contraria"]))
    return results


def _suggest_label_canonical(variants):
    """Escolhe o rotulo 'melhor formado' entre as variantes de um cluster de
    categoria. Diferente de suggest_canonical (nome de pessoa, onde mais
    tokens quase sempre e sobrenome de verdade), aqui TODA diferenca entre
    variantes do mesmo cluster e SO de palavra-conector (e a propria premissa
    do agrupamento por igualdade - ver find_label_clusters) - entao "mais
    tokens" as vezes escolhe o pior, nao o melhor: "MULTA DE" tem mais tokens
    que "MULTA", mas o "DE" solto no final e sinal de dado truncado, nao de
    rotulo mais completo (visto em dado real, planilha (planilha real), 10/09/2026).
    Por isso a primeira regra e nunca escolher um rotulo que termina em
    conector; dentro dos que nao terminam, o mais frequente na planilha."""
    def termina_em_conector(v):
        tokens = v["norm"].split()
        return bool(tokens) and tokens[-1] in LABEL_FILLER_WORDS

    def qualidade(v):
        return (not termina_em_conector(v), v["count"], len(v["norm"]))
    return max(variants, key=qualidade)["text"]


def find_label_clusters(occurrences, blacklist_pairs=None, confirmed_pairs=None):
    """Agrupa rotulos de TIPO DE ACAO / GRUPO DE ACAO que aparecem escritos
    de formas diferentes DENTRO DA PROPRIA planilha - "COBRANCA" e "ACAO DE
    COBRANCA" sendo provavelmente a mesma coisa. Diferente de
    match_category_against_registry, que compara contra uma lista externa
    colada e ja vetada pelo usuario, aqui a comparacao e planilha-contra-
    planilha - sem ninguem vetando os rotulos de antemao.

    A regra NAO e contencao/similaridade fuzzy (como match_category_against_
    registry usa) - e IGUALDADE do conjunto de palavras de conteudo depois de
    tirar so conectores gramaticais (LABEL_FILLER_WORDS). Motivo: dados reais
    de escritorio (planilha (planilha real), 10/09/2026) mostraram que contencao e
    perigosa demais aqui. Rotulo do ADVBOX costuma vir como trilha composta
    ("CASAMENTO / DISSOLUCAO / EMENDA A INICIAL FLS / NAO ATUA FLS"), e uma
    palavra curta generica bate por acaso dentro de varias trilhas sem
    relacao nenhuma ("URBANO" contido em "URBANO AUXILIO DOENCA
    PREVIDENCIARIO BENEFICIOS EM ESPECIE", "TUTELA" contido em "ANTECIPACAO
    DE TUTELA / TUTELA ESPECIFICA"). Pior: "APOSENTADORIA" batia por
    contencao com "APOSENTADORIA POR IDADE", "POR INVALIDEZ ACIDENTARIA" e
    "POR TEMPO DE CONTRIBUICAO" simultaneamente - que sao BENEFICIOS
    DIFERENTES do INSS, nao grafias da mesma categoria. Juntar teria sido
    erro juridico, nao so estetico (mesma licao de "DIVORCIO
    LITIGIOSO"/"DIVORCIO CONSENSUAL" descoberta nos testes sinteticos, so que
    pior porque nao dependia de um rotulo "farol" no meio - a propria
    contencao direta ja era o problema).

    Com IGUALDADE de conjunto (em vez de contencao), qualquer palavra que
    sobra depois de tirar os conectores conta como parte do SENTIDO da
    categoria - "POR IDADE", "MORAL", "DE MENOR" nunca somem so porque o
    rotulo mais curto nao os tem. E, de brinde, igualdade de conjunto e
    sempre transitiva (se A==B e A==C, entao B==C por definicao matematica) -
    o "efeito farol" que forcava um clique-check pra nome de pessoa e pra
    categoria por contencao SOME por construcao aqui, nao precisa mais de
    verificacao extra.

    Retorna lista de clusters (so os com 2+ variantes): [{members, variants:
    [{text, norm, rows, count}], score, reasons, suggested_canonical,
    remembered_canonical}]. `score` e sempre 100.0 (e igualdade, nao grau de
    parecenca) exceto quando a razao e "confirmado".
    """
    blacklist_pairs = blacklist_pairs or set()
    confirmed_pairs = confirmed_pairs or {}

    by_norm = defaultdict(lambda: {"text": None, "rows": []})
    for occ in occurrences:
        norm = occ.get("norm")
        if not norm:
            continue
        entry = by_norm[norm]
        entry["text"] = entry["text"] or occ["text"]
        entry["rows"].append(occ["row"])

    unique_norms = sorted(by_norm.keys())

    def content_words(norm):
        return frozenset(t for t in norm.split() if t not in LABEL_FILLER_WORDS)

    # agrupa direto pela chave de conteudo - dois rotulos com o MESMO
    # conjunto de palavras de conteudo caem na mesma chave automaticamente,
    # sem precisar de union-find (igualdade ja e a relacao de agrupamento).
    by_content_key = defaultdict(list)
    for n in unique_norms:
        key = content_words(n)
        if not key:
            continue  # rotulo vazio depois de tirar conectores - nada a comparar
        by_content_key[key].append(n)

    groups = [members for members in by_content_key.values() if len(members) >= 2]

    # pares confirmados/rejeitados manualmente podem juntar (ou impedir de
    # juntar) rotulos que o calculo automatico NAO uniu sozinho - por
    # exemplo, o usuario decidindo a mao que "CIVEL" e "AREA CIVEL" sao a
    # mesma coisa mesmo com RESPONSABILIDADE... digo, com AREA sobrando.
    ja_agrupados = {n for members in groups for n in members}
    grupos_extra = defaultdict(set)
    for key in confirmed_pairs:
        a, b = tuple(key)
        if a in by_norm and b in by_norm and key not in blacklist_pairs:
            grupos_extra[frozenset((a, b))] |= {a, b}
    # funde grupos extras que compartilham norm (varios pares confirmados
    # formando uma cadeia) - simples union-find so pra esse conjunto pequeno.
    uf = UnionFind()
    for s in grupos_extra.values():
        membros = list(s)
        for m in membros:
            uf.find(m)
        for i in range(1, len(membros)):
            uf.union(membros[0], membros[i])
    extras_por_raiz = defaultdict(set)
    for s in grupos_extra.values():
        for m in s:
            extras_por_raiz[uf.find(m)].add(m)
    for membros in extras_por_raiz.values():
        if len(membros) >= 2:
            groups.append(sorted(membros))

    clusters = []
    for members in groups:
        members = sorted(set(members))
        # blacklist pode separar um membro individual de um grupo automatico
        # (ex: usuario disse na tela que "X" nao e a mesma coisa que "Y",
        # mesmo os dois tendo o mesmo conjunto de palavras de conteudo).
        # Diferente do agrupamento de pessoa (onde blacklist so corta UM par
        # e o resto do cluster fica de pe): aqui, como o agrupamento inteiro
        # vem de uma unica regra de igualdade (nao de pares independentes),
        # um par rejeitado dentro do grupo poe em duvida a premissa "sao
        # todos a mesma coisa" - mais seguro descartar a sugestao automatica
        # inteira do que tentar adivinhar uma reconstrucao parcial.
        tem_par_rejeitado = any(
            frozenset((members[i], members[j])) in blacklist_pairs
            for i in range(len(members)) for j in range(i + 1, len(members))
        )
        if tem_par_rejeitado:
            continue
        membros_validos = members
        variants = []
        for m in membros_validos:
            variants.append({
                "text": by_norm[m]["text"],
                "norm": m,
                "rows": sorted(set(by_norm[m]["rows"])),
                "count": len(by_norm[m]["rows"]),
            })
        reason = "confirmado" if any(
            frozenset((membros_validos[i], membros_validos[j])) in confirmed_pairs
            for i in range(len(membros_validos)) for j in range(i + 1, len(membros_validos))
        ) else "mesma_categoria"
        remembered_canonical = None
        for i in range(len(membros_validos)):
            for j in range(i + 1, len(membros_validos)):
                found = confirmed_pairs.get(frozenset((membros_validos[i], membros_validos[j])))
                if found:
                    remembered_canonical = found
                    break
            if remembered_canonical:
                break
        clusters.append({
            "members": membros_validos,
            "variants": variants,
            "score": 100.0,
            "reasons": [reason],
            "suggested_canonical": _suggest_label_canonical(variants),
            "remembered_canonical": remembered_canonical,
        })
    return clusters
