<script setup>
import { ref, computed, onMounted, nextTick } from "vue";
import * as api from "./api";
import { inicializarConfig } from "./config";
import { guardarArquivos, recuperarArquivos, salvarDecisoes, carregarDecisoes } from "./sessao";
import Sidebar from "./components/Sidebar.vue";
import UploadSection from "./components/UploadSection.vue";
import SensibilidadeSection from "./components/SensibilidadeSection.vue";
import ClustersSection from "./components/ClustersSection.vue";
import ClientesDuplicatasSection from "./components/ClientesDuplicatasSection.vue";
import ClienteParteSection from "./components/ClienteParteSection.vue";
import CourtJudgeSection from "./components/CourtJudgeSection.vue";
import FinanceiroSection from "./components/FinanceiroSection.vue";
import AdvboxSection from "./components/AdvboxSection.vue";
import AcaoValidationSection from "./components/AcaoValidationSection.vue";
import ApplySection from "./components/ApplySection.vue";

const recuperando = ref(false);

onMounted(() => {
  inicializarConfig();
  api.configurarRecuperacao(recuperarSessao);

  // Autossalvamento: em vez de observar o estado de cada secao uma a uma,
  // tira uma foto do que seria ENVIADO. E o mesmo objeto do "Aplicar", entao
  // nao tem como o que foi salvo divergir do que a pessoa esta vendo.
  setInterval(() => {
    if (analyzed.value && sessionId.value) salvarDecisoes(collectAllDecisions());
  }, 15000);

  // Sinal de vida. A revisao nao gera requisicao nenhuma - a pessoa pode
  // passar uma hora lendo sem o servidor saber que ela existe. Sem isso a
  // instancia dorme (plano gratuito) e a varredura por tempo apaga a sessao
  // de quem esta trabalhando, inclusive por causa do upload de outra pessoa.
  setInterval(async () => {
    if (!sessionId.value || recuperando.value) return;
    try {
      const r = await api.ping(sessionId.value);
      if (!r.viva) await recuperarSessao();
    } catch {
      // sem rede agora: a proxima batida tenta de novo
    }
  }, 3 * 60 * 1000);
});

function restaurarTudo(salvo) {
  if (!salvo) return;
  clustersRef.value?.restaurar(salvo.decisions);
  clientesDuplicatasRef.value?.restaurar(salvo.clientes_duplicate_decisions);
  responsaveisRef.value?.restaurar(salvo.responsavel_decisions);
  tipoAcaoRef.value?.restaurar(salvo.tipo_acao_decisions, salvo.tipo_acao_cluster_decisions);
  grupoAcaoRef.value?.restaurar(salvo.grupo_acao_decisions, salvo.grupo_acao_cluster_decisions);
  nomeValidacaoRef.value?.restaurar(salvo.nome_validacao_decisions, []);
  clienteParteRef.value?.restaurar(salvo.cliente_parte_overlap_decisions);
  courtJudgeRef.value?.restaurar(salvo.court_judge_decisions);
  financeiroRef.value?.restaurar(salvo.financeiro_orphan_decisions);
  advboxRef.value?.restaurar(salvo.advbox_only_decisions, salvo.advbox_conflict_decisions);
}

// Reergue a sessao sozinho quando o servidor perdeu ela. Reenvia os arquivos
// guardados no navegador, refaz a analise - que da o mesmo resultado pro
// mesmo arquivo e o mesmo limiar - e religa as decisoes pelo NOME, nunca pelo
// id (id so vale dentro de uma analise). Chamada pelo api.js em qualquer rota
// que receba "sessao nao encontrada", e tambem pelo sinal de vida.
async function recuperarSessao() {
  if (recuperando.value) return null;
  const arquivos = await recuperarArquivos();
  if (!arquivos) return null;
  const salvo = carregarDecisoes();
  recuperando.value = true;
  try {
    const up = await api.uploadArquivos(arquivos);
    sessionId.value = up.session_id;
    await runAnalyze();
    await nextTick();
    restaurarTudo(salvo);
    return up.session_id;
  } catch {
    return null;
  } finally {
    recuperando.value = false;
  }
}


const sessionId = ref(null);
const threshold = ref(88);
const responsaveisText = ref("");
const tiposAcaoText = ref("");
const gruposAcaoText = ref("");
const nomesText = ref("");

const clusters = ref([]);
const clientesDuplicatesExact = ref([]);
const clientesDuplicatesFuzzy = ref([]);
const respSuggestions = ref([]);
const tipoAcaoSuggestions = ref([]);
const grupoAcaoSuggestions = ref([]);
const tipoAcaoClusters = ref([]);
const grupoAcaoClusters = ref([]);
const nomeValidacaoSuggestions = ref([]);
const temColunaTipoAcao = ref(false);
const temColunaGrupoAcao = ref(false);
const clienteParteOverlap = ref([]);
const courtJudgeItems = ref([]);
const financeiroOrphans = ref([]);
const advboxOnly = ref([]);
const advboxFieldConflicts = ref([]);

const temColunaResponsavel = ref(false);
const temColunaParteContraria = ref(false);
const temAdvbox = ref(false);
const temFinanceiro = ref(false);
const temPlanilhaClientes = ref(false);
const temEscavador = ref(false);

const stats = ref(null);
const analyzed = ref(false);
const analyzing = ref(false);
const uploadStatus = ref(null);
const escFilename = ref(null);
const cliFilename = ref(null);
const finFilename = ref(null);

const clustersRef = ref(null);
const clientesDuplicatasRef = ref(null);
const clienteParteRef = ref(null);
const courtJudgeRef = ref(null);
const financeiroRef = ref(null);
const advboxRef = ref(null);
const responsaveisRef = ref(null);
const tipoAcaoRef = ref(null);
const grupoAcaoRef = ref(null);
const nomeValidacaoRef = ref(null);

async function handleUpload(formData) {
  uploadStatus.value = null;
  try {
    // os arquivos vao pro navegador ANTES de subir: se a sessao do
    // servidor morrer depois, da pra reenviar sem pedir nada pra pessoa
    await guardarArquivos(formData);
    const data = await api.uploadArquivos(formData);
    sessionId.value = data.session_id;
    escFilename.value = data.escavador?.filename || null;
    cliFilename.value = data.clientes?.filename || null;
    finFilename.value = data.financeiro?.filename || null;
    const parts = [];
    if (data.escavador) parts.push(`Escavador: ${data.escavador.n_occurrences} nomes encontrados na aba "${data.escavador.sheet}".`);
    if (data.clientes) parts.push(`Clientes: ${data.clientes.n_rows} linhas (${data.clientes.tem_cpf ? "com CPF" : "sem CPF"}).`);
    if (data.financeiro) parts.push(`Financeiro: ${data.financeiro.n_rows} lançamentos com nome.`);
    if (data.advbox_pessoas) parts.push(`ADVBOX pessoas: ${data.advbox_pessoas.n_pessoas} encontradas.`);
    if (data.advbox_processos) parts.push(`ADVBOX processos: ${data.advbox_processos.n_processos} encontrados.`);
    uploadStatus.value = { type: "ok", message: parts.join(" ") };
    await runAnalyze();
  } catch (err) {
    uploadStatus.value = { type: "error", message: `Falha ao enviar: ${err.message}` };
  }
}

// Numero de sequencia da chamada de analyze mais recente. "Comparar" (em
// qualquer uma das 4 secoes) e "Reanalisar" chamam runAnalyze() sem
// nenhuma exclusao mutua entre si - clicar em "Comparar" enquanto a
// analise inicial do upload ainda esta em andamento dispara uma segunda
// chamada concorrente. Sem essa guarda, a resposta que chegasse por
// ULTIMO vencia, nao a que foi enviada por ultimo: se a chamada inicial
// (lista colada ainda vazia) demorasse mais e respondesse DEPOIS da
// chamada do "Comparar" (lista ja preenchida), o resultado certo era
// sobrescrito pelo antigo - a tela dizia "nenhuma divergencia" ate o
// usuario clicar em "Comparar" de novo. Agora so a resposta da chamada
// mais recente e aplicada; qualquer resposta de uma chamada ja superada
// e descartada.
let analyzeSeq = 0;

async function runAnalyze() {
  if (!sessionId.value) return;
  const seq = ++analyzeSeq;
  analyzing.value = true;
  try {
    const data = await api.analisar({
      session_id: sessionId.value,
      threshold: threshold.value,
      responsaveis_text: responsaveisText.value,
      tipos_acao_text: tiposAcaoText.value,
      grupos_acao_text: gruposAcaoText.value,
      nomes_text: nomesText.value,
    });
    if (seq !== analyzeSeq) return; // resposta de uma chamada ja superada - descarta
    clusters.value = data.clusters;
    clientesDuplicatesExact.value = data.clientes_duplicates_exact || [];
    clientesDuplicatesFuzzy.value = data.clientes_duplicates_fuzzy || [];
    respSuggestions.value = data.responsavel_suggestions || [];
    tipoAcaoSuggestions.value = data.tipo_acao_suggestions || [];
    grupoAcaoSuggestions.value = data.grupo_acao_suggestions || [];
    tipoAcaoClusters.value = data.tipo_acao_clusters || [];
    grupoAcaoClusters.value = data.grupo_acao_clusters || [];
    nomeValidacaoSuggestions.value = data.nome_validacao_suggestions || [];
    temColunaTipoAcao.value = !!data.tem_coluna_tipo_acao;
    temColunaGrupoAcao.value = !!data.tem_coluna_grupo_acao;
    clienteParteOverlap.value = data.cliente_parte_overlap || [];
    courtJudgeItems.value = data.court_judge_items || [];
    financeiroOrphans.value = data.financeiro_orphans || [];
    advboxOnly.value = data.advbox_only || [];
    advboxFieldConflicts.value = data.advbox_field_conflicts || [];
    temColunaResponsavel.value = !!data.tem_coluna_responsavel;
    temColunaParteContraria.value = !!data.tem_coluna_parte_contraria;
    temAdvbox.value = !!data.tem_advbox;
    temFinanceiro.value = !!data.tem_financeiro;
    temPlanilhaClientes.value = !!data.tem_planilha_clientes;
    temEscavador.value = !!data.tem_escavador;
    stats.value = data.stats;
    analyzed.value = true;
  } finally {
    if (seq === analyzeSeq) analyzing.value = false;
  }
}

function collectAllDecisions() {
  return {
    session_id: sessionId.value,
    decisions: clustersRef.value?.collectDecisions() || [],
    clientes_duplicate_decisions: clientesDuplicatasRef.value?.collectDecisions() || [],
    responsavel_decisions: responsaveisRef.value?.collectDecisions() || [],
    tipo_acao_decisions: tipoAcaoRef.value?.collectDecisions() || [],
    grupo_acao_decisions: grupoAcaoRef.value?.collectDecisions() || [],
    tipo_acao_cluster_decisions: tipoAcaoRef.value?.collectClusterDecisions() || [],
    grupo_acao_cluster_decisions: grupoAcaoRef.value?.collectClusterDecisions() || [],
    nome_validacao_decisions: nomeValidacaoRef.value?.collectDecisions() || [],
    cliente_parte_overlap_decisions: clienteParteRef.value?.collectDecisions() || [],
    court_judge_decisions: courtJudgeRef.value?.collectDecisions() || [],
    financeiro_orphan_decisions: financeiroRef.value?.collectDecisions() || [],
    advbox_only_decisions: advboxRef.value?.collectOnlyDecisions() || [],
    advbox_conflict_decisions: advboxRef.value?.collectConflictDecisions() || [],
  };
}

const navCounts = computed(() => ({
  clusters: clusters.value.length,
  clientesDuplicatas: clientesDuplicatesExact.value.length + clientesDuplicatesFuzzy.value.length,
  clienteParte: clienteParteOverlap.value.length,
  courtJudge: courtJudgeItems.value.length,
  financeiro: financeiroOrphans.value.length,
  advbox: advboxOnly.value.length + advboxFieldConflicts.value.length,
  resp: respSuggestions.value.length,
  tipoAcao: tipoAcaoSuggestions.value.length + tipoAcaoClusters.value.length,
  grupoAcao: grupoAcaoSuggestions.value.length + grupoAcaoClusters.value.length,
  nomeValidacao: nomeValidacaoSuggestions.value.length,
}));

// Itens que pedem uma decisao de verdade (exclui as secoes de duplicatas em
// Clientes, que nao tem estado "pendente"/"revisado" - toda linha ja vem com
// uma acao padrao e nao ha nada de historico pra "lembrar" ali).
const totalItensRevisao = computed(() => (
  clusters.value.length +
  clienteParteOverlap.value.length +
  courtJudgeItems.value.length +
  financeiroOrphans.value.length +
  advboxOnly.value.length +
  advboxFieldConflicts.value.length +
  respSuggestions.value.length +
  tipoAcaoSuggestions.value.length +
  grupoAcaoSuggestions.value.length +
  tipoAcaoClusters.value.length +
  grupoAcaoClusters.value.length +
  nomeValidacaoSuggestions.value.length
));

// Soma o que cada secao realmente marcou como revisado NESTA sessao (nao
// conta decisao lembrada de planilha antiga como "ja revisado" - ver o bug
// corrigido em ClustersSection.vue e nas demais secoes).
const totalItensRevisados = computed(() => (
  (clustersRef.value?.touchedCount || 0) +
  (clienteParteRef.value?.touchedCount || 0) +
  (courtJudgeRef.value?.touchedCount || 0) +
  (financeiroRef.value?.touchedCount || 0) +
  (advboxRef.value?.touchedCount || 0) +
  (responsaveisRef.value?.touchedCount || 0) +
  (tipoAcaoRef.value?.touchedCount || 0) +
  (grupoAcaoRef.value?.touchedCount || 0) +
  (nomeValidacaoRef.value?.touchedCount || 0)
));

const progressPct = computed(() => {
  if (!totalItensRevisao.value) return 100;
  return Math.round((totalItensRevisados.value / totalItensRevisao.value) * 100);
});
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="topbar-mark">
        <span class="stamp-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 12.5l2 2 4.5-5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </span>
        <h1>padronizador</h1>
      </div>
      <p class="subtitle">motor de correspondência de nomes — Escavador × Clientes × ADVBOX</p>

      <div class="session-chip" v-if="escFilename || cliFilename">
        <span class="dot" aria-hidden="true"></span>
        <span v-if="escFilename"><strong>{{ escFilename }}</strong></span>
        <span v-if="escFilename && cliFilename">·</span>
        <span v-if="cliFilename"><strong>{{ cliFilename }}</strong></span>
        <span v-if="(escFilename || cliFilename) && finFilename">·</span>
        <span v-if="finFilename"><strong>{{ finFilename }}</strong></span>
      </div>

      <div class="progress-chip" v-if="analyzed">
        <span>{{ totalItensRevisados }}/{{ totalItensRevisao }} revisados</span>
        <div class="progress-track">
          <div class="progress-fill" :style="{ width: progressPct + '%' }"></div>
        </div>
      </div>
      <div class="session-chip" v-if="recuperando" role="status">
        <span class="dot" aria-hidden="true"></span>
        <span>A sessão caiu no servidor — reenviando os arquivos e
          recuperando a sua revisão, sem perder nada.</span>
      </div>

    </header>

    <div class="layout">
      <Sidebar :counts="navCounts" />

      <main>
        <UploadSection @uploaded="handleUpload" :status="uploadStatus" />

        <SensibilidadeSection
          v-if="sessionId"
          v-model:threshold="threshold"
          :stats="stats"
          :cliente-parte-count="clienteParteOverlap.length"
          :court-judge-count="courtJudgeItems.length"
          :advbox-count="advboxOnly.length + advboxFieldConflicts.length"
          :tem-advbox="temAdvbox"
          :resp-count="respSuggestions.length"
          :loading="analyzing"
          @reanalyze="runAnalyze"
        />

        <ClustersSection
          v-if="analyzed"
          id="clusters-section"
          ref="clustersRef"
          :clusters="clusters"
        />

        <ClientesDuplicatasSection
          v-if="analyzed && temPlanilhaClientes"
          id="clientes-duplicatas-section"
          ref="clientesDuplicatasRef"
          :exact-groups="clientesDuplicatesExact"
          :fuzzy-groups="clientesDuplicatesFuzzy"
        />

        <ClienteParteSection
          v-if="analyzed && temColunaParteContraria"
          id="cliente-parte-section"
          ref="clienteParteRef"
          :items="clienteParteOverlap"
        />

        <CourtJudgeSection
          v-if="analyzed && temEscavador"
          id="court-judge-section"
          ref="courtJudgeRef"
          :items="courtJudgeItems"
        />

        <FinanceiroSection
          v-if="analyzed && temFinanceiro"
          id="financeiro-section"
          ref="financeiroRef"
          :items="financeiroOrphans"
        />

        <AdvboxSection
          v-if="analyzed && temAdvbox"
          id="advbox-section"
          ref="advboxRef"
          :only-items="advboxOnly"
          :conflicts="advboxFieldConflicts"
          :tem-planilha-clientes="temPlanilhaClientes"
        />

        <AcaoValidationSection
          v-if="analyzed"
          id="nome-validacao-section"
          class="card"
          ref="nomeValidacaoRef"
          titulo="9. Conferir nomes com uma lista"
          descricao="Quando você só precisa bater os nomes e não quer enviar o PDF de pessoas do ADVBOX: cole aqui a lista de nomes como estão na conta (ou extraia de um print) e o sistema aponta os que estão diferentes na planilha. Nada é alterado sem você marcar 'Aplicar'."
          rotulo-lista="Lista de nomes (um por linha)"
          placeholder="MARIA JOSE DA SILVA&#10;JOAO PEREIRA SANTOS&#10;..."
          :show-ocr="true"
          v-model:registry-text="nomesText"
          :suggestions="nomeValidacaoSuggestions"
          :loading="analyzing"
          @compare="runAnalyze"
        />

        <AcaoValidationSection
          v-if="analyzed && temColunaResponsavel"
          id="responsaveis-section"
          class="card"
          ref="responsaveisRef"
          titulo="10. Responsáveis (usuários do sistema)"
          descricao="Cole a lista de responsáveis/usuários como existem no seu sistema (ou extraia de um print). O sistema aponta as divergências e você decide, uma a uma, se aplica ou mantém — e a decisão fica guardada para as próximas planilhas."
          rotulo-lista="Lista oficial de responsáveis (um nome por linha)"
          placeholder="ROBERTO ALVES DE MENEZES JUNIOR&#10;PATRICIA HELENA DA ROCHA&#10;..."
          :show-ocr="true"
          v-model:registry-text="responsaveisText"
          :suggestions="respSuggestions"
          :loading="analyzing"
          @compare="runAnalyze"
        />

        <AcaoValidationSection
          v-if="analyzed && temColunaTipoAcao"
          id="tipo-acao-section"
          class="card"
          ref="tipoAcaoRef"
          titulo="11. Tipos de Ação"
          descricao="Cole a lista oficial de TIPOS DE AÇÃO da sua conta (um por linha) para conferir se os valores da planilha batem. O sistema aponta o que está diferente e sugere o correspondente — você decide se altera ou mantém, e a decisão fica guardada para as próximas planilhas."
          placeholder="PETIÇÃO DE HERANÇA&#10;APOSENTADORIA POR IDADE&#10;..."
          v-model:registry-text="tiposAcaoText"
          :suggestions="tipoAcaoSuggestions"
          :clusters="tipoAcaoClusters"
          :loading="analyzing"
          @compare="runAnalyze"
        />

        <AcaoValidationSection
          v-if="analyzed && temColunaGrupoAcao"
          id="grupo-acao-section"
          class="card"
          ref="grupoAcaoRef"
          titulo="12. Grupos de Ação"
          descricao="Mesma conferência, agora para a coluna GRUPO DE AÇÃO: cole a lista oficial da conta e revise as divergências. As decisões também ficam lembradas."
          placeholder="FAMÍLIA&#10;PREVIDENCIÁRIO&#10;..."
          v-model:registry-text="gruposAcaoText"
          :suggestions="grupoAcaoSuggestions"
          :clusters="grupoAcaoClusters"
          :loading="analyzing"
          @compare="runAnalyze"
        />

        <ApplySection
          v-if="analyzed"
          id="apply-section"
          :session-id="sessionId"
          :collect-decisions="collectAllDecisions"
        />
      </main>
    </div>
  </div>
</template>
