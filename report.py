"""
Gera um resumo em texto (.txt) de tudo que foi padronizado numa aplicacao -
pensado pra ser colado direto numa descricao/registro do que foi feito (ex:
campo de observacoes de um processo, e-mail pro time...), nao so pra arquivar
junto com a planilha.
"""
import datetime


def _section(lines, title, items, render_item):
    if not items:
        return
    plural = "s" if len(items) != 1 else ""
    lines.append(f"{title} ({len(items)} item{plural})")
    lines.append("-" * 50)
    for i, item in enumerate(items, 1):
        lines.extend(render_item(i, item))
    lines.append("")


def build_summary_text(esc_filename, merged_groups, cliente_parte_items,
                        court_judge_items, responsavel_items,
                        n_changes_escavador=None, n_changes_clientes=None,
                        advbox_added_items=None, advbox_enriched_items=None,
                        clientes_duplicates_removed=None,
                        tipo_acao_items=None, grupo_acao_items=None,
                        nome_validacao_items=None, financeiro_moved_items=None,
                        n_changes_financeiro=None):
    """
    merged_groups: [{"canonical": str, "variants": [str,...], "excluded": [str,...]}]
    cliente_parte_items: [{"text": str, "action": "only_parte"|"only_cliente"}]
    court_judge_items: [{"text": str}]
    responsavel_items: [{"text": str, "canonical": str}]
    advbox_added_items: [{"text": str}] - nomes que so existiam na conta do
      ADVBOX e foram adicionados na planilha de clientes
    advbox_enriched_items: [{"text": str, "campos": [str,...]}] - clientes ja
      cadastrados aqui que ganharam campos vazios preenchidos com dados da
      conta do ADVBOX (CPF, RG, telefone, endereco...)
    """
    advbox_added_items = advbox_added_items or []
    advbox_enriched_items = advbox_enriched_items or []
    clientes_duplicates_removed = clientes_duplicates_removed or []
    tipo_acao_items = tipo_acao_items or []
    grupo_acao_items = grupo_acao_items or []
    nome_validacao_items = nome_validacao_items or []
    financeiro_moved_items = financeiro_moved_items or []
    lines = []
    lines.append("PADRONIZACAO DE CLIENTES - RESUMO DAS ALTERACOES")
    lines.append(f"Planilha: {esc_filename}")
    lines.append(f"Gerado em: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}")
    lines.append("")

    def render_merged(i, g):
        out = [f'{i}. Nome final: "{g["canonical"]}"',
               f'   Variantes unificadas: {", ".join(g["variants"])}']
        if g.get("excluded"):
            out.append(f'   Excluidas do grupo (nao e a mesma pessoa/empresa): {", ".join(g["excluded"])}')
        return out

    _section(lines, "HOMONIMOS PADRONIZADOS", merged_groups, render_merged)

    def render_cliente_parte(i, item):
        acao = "mantido só em Parte Contrária" if item["action"] == "only_parte" else "mantido só em Cliente"
        return [f'{i}. "{item["text"]}" - {acao}']

    _section(lines, "CLIENTE E PARTE CONTRARIA AO MESMO TEMPO", cliente_parte_items, render_cliente_parte)

    def render_clientes_duplicate_removed(i, item):
        return [f'{i}. "{item["text"]}"']

    _section(lines, "LINHAS DUPLICADAS REMOVIDAS DA PLANILHA DE CLIENTES", clientes_duplicates_removed, render_clientes_duplicate_removed)

    def render_court_judge(i, item):
        return [f'{i}. "{item["text"]}"']

    _section(lines, "NOMES DE TRIBUNAL/VARA/COMARCA/JUIZ REMOVIDOS", court_judge_items, render_court_judge)

    def render_responsavel(i, item):
        return [f'{i}. "{item["text"]}" -> "{item["canonical"]}"']

    _section(lines, "RESPONSAVEIS CORRIGIDOS", responsavel_items, render_responsavel)

    def render_acao(i, item):
        return [f'{i}. "{item["text"]}" -> "{item["canonical"]}"']

    _section(lines, "TIPOS DE ACAO CORRIGIDOS", tipo_acao_items, render_acao)
    _section(lines, "GRUPOS DE ACAO CORRIGIDOS", grupo_acao_items, render_acao)
    _section(lines, "NOMES CORRIGIDOS PELA LISTA CONFERIDA", nome_validacao_items, render_acao)

    def render_advbox_added(i, item):
        return [f'{i}. "{item["text"]}"']

    _section(lines, "NOMES ADICIONADOS DA CONTA ADVBOX (SO EXISTIAM LA)", advbox_added_items, render_advbox_added)

    def render_advbox_enriched(i, item):
        return [f'{i}. "{item["text"]}" - campos preenchidos: {", ".join(item["campos"])}']

    _section(lines, "CLIENTES ENRIQUECIDOS COM DADOS DO ADVBOX", advbox_enriched_items, render_advbox_enriched)

    def render_financeiro_moved(i, item):
        return [f'{i}. "{item["text"]}" - saiu de NOME DO CLIENTE e foi pro inicio da DESCRICAO']

    _section(lines, "FINANCEIRO - NOMES SEM CADASTRO MOVIDOS PRA DESCRICAO",
             financeiro_moved_items, render_financeiro_moved)

    lines.append("TOTAIS")
    lines.append("-" * 50)
    if n_changes_escavador is not None:
        lines.append(f"Celulas alteradas na planilha do Escavador: {n_changes_escavador}")
    if n_changes_clientes is not None:
        lines.append(f"Celulas alteradas na planilha de Clientes: {n_changes_clientes}")
    if n_changes_financeiro is not None:
        lines.append(f"Celulas alteradas na planilha de Financeiro: {n_changes_financeiro}")

    return "\n".join(lines)
