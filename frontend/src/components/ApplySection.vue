<script setup>
import { ref } from "vue";
import * as api from "../api";
import { config } from "../config";

const props = defineProps({
  sessionId: { type: String, default: null },
  collectDecisions: { type: Function, required: true },
});

const persistRules = ref(true);
const previewLoading = ref(false);
const applying = ref(false);
const previewResult = ref(null);
const previewError = ref("");
const applyStatus = ref(null);
const summaryText = ref("");
const downloadLinks = ref([]);
const copyLabel = ref("Copiar resumo");

function buildPayload(dryRun) {
  return {
    ...props.collectDecisions(),
    persist_rules: persistRules.value,
    dry_run: dryRun,
  };
}

const SHEET_LABELS = { escavador: "Escavador", clientes: "Clientes", financeiro: "Financeiro" };
const SHEET_KINDS = ["escavador", "clientes", "financeiro"];

function sheetLabel(kind) {
  return SHEET_LABELS[kind] || kind;
}

async function onPreview() {
  previewError.value = "";
  previewLoading.value = true;
  try {
    const data = await api.aplicar(buildPayload(true));
    previewResult.value = data.result;
  } catch (err) {
    previewError.value = `Erro ao gerar a prévia: ${err.message}`;
    previewResult.value = null;
  } finally {
    previewLoading.value = false;
  }
}

async function onApply() {
  applyStatus.value = null;
  downloadLinks.value = [];
  applying.value = true;
  try {
    const data = await api.aplicar(buildPayload(false));

    const summaryParts = [];
    if (data.result.escavador) summaryParts.push(`Escavador: ${data.result.escavador.n_changes} célula(s) alterada(s).`);
    if (data.result.clientes) summaryParts.push(`Clientes: ${data.result.clientes.n_changes} linha(s) alterada(s).`);
    if (data.result.financeiro) summaryParts.push(`Financeiro: ${data.result.financeiro.n_changes} célula(s) alterada(s).`);
    applyStatus.value = { type: "ok", message: summaryParts.join(" ") };

    summaryText.value = data.summary_text || "";

    const links = [];
    if (data.result.escavador) {
      links.push({ href: api.downloadUrl(props.sessionId, "escavador"), label: `Baixar ${data.result.escavador.filename}` });
    }
    if (data.result.clientes) {
      links.push({ href: api.downloadUrl(props.sessionId, "clientes"), label: `Baixar ${data.result.clientes.filename}` });
    }
    if (data.result.financeiro) {
      links.push({ href: api.downloadUrl(props.sessionId, "financeiro"), label: `Baixar ${data.result.financeiro.filename}` });
    }
    if (data.result.resumo) {
      links.push({ href: api.downloadUrl(props.sessionId, "resumo"), label: `Baixar ${data.result.resumo.filename}` });
    }
    downloadLinks.value = links;
    previewResult.value = null;
  } catch (err) {
    applyStatus.value = { type: "error", message: `Deu um erro inesperado ao aplicar: ${err.message}` };
  } finally {
    applying.value = false;
  }
}

async function onCopySummary() {
  try {
    await navigator.clipboard.writeText(summaryText.value);
  } catch (err) {
    // fallback para navegadores sem permissao de clipboard
  }
  copyLabel.value = "Copiado!";
  setTimeout(() => { copyLabel.value = "Copiar resumo"; }, 1500);
}
</script>

<template>
  <section id="apply-section" class="card">
    <h2>13. Aplicar e baixar</h2>

    <!-- So aparece quando o servidor esta com a memoria ligada
         (PADRONIZADOR_MEMORIA=1). Desligada, oferecer "lembrar" seria prometer
         algo que nao vai acontecer. -->
    <label v-if="config.memoria" class="checkbox-line">
      <input type="checkbox" v-model="persistRules">
      Lembrar dessas decisões para a próxima planilha (recomendado)
    </label>
    <p v-else class="hint">
      Esta instalação não guarda nada: as decisões desta revisão valem só para
      as planilhas geradas agora e não ficam salvas em lugar nenhum.
    </p>

    <button type="button" :disabled="previewLoading" @click="onPreview">
      {{ previewLoading ? "Gerando prévia..." : "Visualizar mudanças" }}
    </button>
    <div v-if="previewError" class="error-msg">{{ previewError }}</div>

    <div v-if="previewResult" class="preview-block">
      <div class="diff-summary">
        <div class="stat-tile" v-if="previewResult.escavador">Escavador: <b>{{ previewResult.escavador.n_changes }}</b> célula(s)</div>
        <div class="stat-tile" v-if="previewResult.clientes">Clientes: <b>{{ previewResult.clientes.n_changes }}</b> linha(s)</div>
        <div class="stat-tile" v-if="previewResult.financeiro">Financeiro: <b>{{ previewResult.financeiro.n_changes }}</b> célula(s)</div>
      </div>

      <template v-for="kind in SHEET_KINDS" :key="kind">
        <template v-if="previewResult[kind]">
          <h3>{{ sheetLabel(kind) }} — {{ previewResult[kind].filename }}</h3>
          <div v-if="previewResult[kind].changes.length === 0" class="diff-empty">Nenhuma mudança nesta planilha.</div>
          <div v-else class="diff-table-wrap">
            <table class="diff-table">
              <thead>
                <tr>
                  <th>Linha</th>
                  <th>Coluna</th>
                  <th>Antes</th>
                  <th>Depois</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(ch, i) in previewResult[kind].changes" :key="i">
                  <td>{{ ch.row }}</td>
                  <td class="diff-col">{{ ch.coluna || "-" }}</td>
                  <td class="diff-before">{{ ch.before }}</td>
                  <td class="diff-after">{{ ch.after }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </template>

      <button type="button" :disabled="applying" @click="onApply">
        {{ applying ? "Aplicando..." : "Confirmar e aplicar" }}
      </button>
    </div>

    <div v-if="applyStatus" :class="applyStatus.type === 'ok' ? 'ok-msg' : 'error-msg'">{{ applyStatus.message }}</div>

    <div v-if="summaryText" id="summary-section">
      <label for="summary-textarea">Resumo do que foi padronizado (para colar na descrição)</label>
      <textarea id="summary-textarea" rows="12" readonly :value="summaryText"></textarea>
      <button type="button" class="secondary small" @click="onCopySummary">{{ copyLabel }}</button>
    </div>

    <div class="download-links">
      <a v-for="link in downloadLinks" :key="link.href" :href="link.href">{{ link.label }}</a>
    </div>
  </section>
</template>
