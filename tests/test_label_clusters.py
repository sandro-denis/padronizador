# -*- coding: utf-8 -*-
"""Homonimos de TIPO DE ACAO / GRUPO DE ACAO - agrupamento dos valores da
PROPRIA planilha entre si (diferente de match_category_against_registry, que
compara contra uma lista externa colada pelo usuario).

A regra e IGUALDADE do conjunto de palavras de conteudo depois de tirar
conectores gramaticais (LABEL_FILLER_WORDS) - NAO contencao nem fuzzy. Dados
reais (uma planilha real, 10/09/2026) mostraram que contencao e perigosa aqui:
rotulo do ADVBOX vem como trilha composta ("CASAMENTO / DISSOLUCAO / EMENDA A
INICIAL FLS"), e "APOSENTADORIA" batia por contencao com "APOSENTADORIA POR
IDADE"/"POR INVALIDEZ"/"POR TEMPO DE CONTRIBUICAO" ao mesmo tempo - que sao
BENEFICIOS DIFERENTES do INSS, nao grafias da mesma categoria. Igualdade de
conjunto e sempre transitiva, entao o "efeito farol" (nome curto conectando
duas coisas que nunca se pareceram entre si, visto com pessoas e com
categoria por contencao) some por construcao - nao precisa mais de
verificacao de clique.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matching import find_label_clusters, normalize_name


def occ(text, row=1):
    return {"text": text, "norm": normalize_name(text), "row": row}


def members_of(cluster):
    return set(cluster["members"])


def test_agrupa_diferenca_so_de_conector():
    clusters = find_label_clusters([
        occ("COBRANCA", row=1),
        occ("ACAO DE COBRANCA", row=2),
    ])
    assert len(clusters) == 1
    c = clusters[0]
    assert members_of(c) == {normalize_name("COBRANCA"), normalize_name("ACAO DE COBRANCA")}
    assert c["suggested_canonical"] == "ACAO DE COBRANCA"  # o mais completo
    assert c["reasons"] == ["mesma_categoria"]
    assert c["score"] == 100.0


def test_nao_sugere_variante_truncada_como_canonico():
    """Bug real (uma planilha real, 10/09/2026): 'MULTA DE' tinha mais
    ocorrencias e mais tokens que 'MULTA', mas o 'DE' solto no final e sinal
    de dado truncado - a sugestao nunca pode ser a variante que termina em
    conector, mesmo sendo a mais frequente."""
    clusters = find_label_clusters([
        occ("MULTA", row=1),
        occ("MULTA DE", row=2), occ("MULTA DE", row=3), occ("MULTA DE", row=4),
    ])
    assert len(clusters) == 1
    assert clusters[0]["suggested_canonical"] == "MULTA"


def test_qualificador_diferente_nunca_agrupa_mesmo_com_radical_comum():
    """O bug real: contencao juntava 'APOSENTADORIA' com qualquer 'APOSENTADORIA
    POR X'. Com igualdade de conjunto, POR/IDADE/INVALIDEZ sobram e o rotulo
    generico nunca agrupa com nenhum especifico - nem em pares."""
    clusters = find_label_clusters([
        occ("APOSENTADORIA"),
        occ("APOSENTADORIA POR IDADE"),
        occ("APOSENTADORIA POR INVALIDEZ"),
    ])
    assert clusters == []


def test_rotulo_curto_generico_nao_bate_com_trilha_composta():
    """Caso real: 'URBANO' sozinho batia por contencao com rotulos compostos
    do ADVBOX tipo 'URBANO AUXILIO DOENCA PREVIDENCIARIO BENEFICIOS EM
    ESPECIE' - sao categorias sem relacao, so compartilham uma palavra."""
    clusters = find_label_clusters([
        occ("URBANO"),
        occ("URBANO AUXILIO DOENCA PREVIDENCIARIO BENEFICIOS EM ESPECIE"),
        occ("AVERBACAO / COMPUTO DE TEMPO DE SERVICO URBANO"),
    ])
    assert clusters == []


def test_categorias_juridicas_diferentes_nao_batem():
    clusters = find_label_clusters([occ("DANO MORAL"), occ("DANO MATERIAL")])
    assert clusters == []
    clusters = find_label_clusters([
        occ("BUSCA E APREENSAO DE MENOR"),
        occ("BUSCA E APREENSAO DE VEICULO"),
    ])
    assert clusters == []
    clusters = find_label_clusters([occ("DIVORCIO LITIGIOSO"), occ("DIVORCIO CONSENSUAL")])
    assert clusters == []


def test_tres_variantes_com_mesmo_conteudo_agrupam_juntas():
    clusters = find_label_clusters([
        occ("COBRANCA", row=1),
        occ("ACAO DE COBRANCA", row=2),
        occ("COBRANCA DE", row=3),  # "DE" sobrando no final e so conector
    ])
    assert len(clusters) == 1
    assert len(clusters[0]["members"]) == 3


def test_blacklist_descarta_a_sugestao_do_grupo_inteiro():
    """Diferente do agrupamento de pessoa: aqui o grupo inteiro vem de UMA
    regra de igualdade, nao de pares independentes. Se o usuario rejeita um
    par dentro do grupo (mesmo com o mesmo conteudo), a premissa fica em
    duvida - mais seguro descartar a sugestao toda do que reconstruir uma
    parte."""
    a, b = normalize_name("COBRANCA"), normalize_name("ACAO DE COBRANCA")
    clusters = find_label_clusters(
        [occ("COBRANCA"), occ("ACAO DE COBRANCA")],
        blacklist_pairs={frozenset((a, b))},
    )
    assert clusters == []

    # o mesmo vale pra um trio: um par rejeitado descarta o grupo inteiro,
    # nao so aquele par.
    clusters = find_label_clusters(
        [occ("COBRANCA"), occ("ACAO DE COBRANCA"), occ("COBRANCA DE")],
        blacklist_pairs={frozenset((a, b))},
    )
    assert clusters == []


def test_confirmado_forca_o_par_mesmo_com_conteudo_diferente():
    """Par que o usuario ja confirmou antes entra mesmo sem bater no calculo -
    e uma decisao humana, nao uma sugestao automatica."""
    a, b = normalize_name("PENAL"), normalize_name("PREVIDENCIARIO")
    clusters = find_label_clusters(
        [occ("PENAL"), occ("PREVIDENCIARIO")],
        confirmed_pairs={frozenset((a, b)): "PENAL"},
    )
    assert len(clusters) == 1
    assert clusters[0]["reasons"] == ["confirmado"]
    assert clusters[0]["remembered_canonical"] == "PENAL"


def test_ocorrencias_da_mesma_grafia_se_juntam_num_variant_so():
    clusters = find_label_clusters([
        occ("COBRANCA", row=1),
        occ("COBRANCA", row=5),
        occ("ACAO DE COBRANCA", row=9),
    ])
    assert len(clusters) == 1
    v = {v["norm"]: v for v in clusters[0]["variants"]}
    cobranca = v[normalize_name("COBRANCA")]
    assert cobranca["rows"] == [1, 5]
    assert cobranca["count"] == 2


def test_valor_sozinho_nao_gera_cluster():
    clusters = find_label_clusters([occ("USUCAPIAO")])
    assert clusters == []


def test_rotulo_so_de_conector_nao_gera_grupo_vazio():
    """Se sobrar vazio depois de tirar conectores (ex: celula so com 'DE'),
    nao pode virar chave de agrupamento - juntaria lixo com lixo."""
    clusters = find_label_clusters([occ("DE"), occ("E"), occ("ACAO")])
    assert clusters == []


def test_lista_vazia():
    assert find_label_clusters([]) == []
