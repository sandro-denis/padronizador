<script setup>
import { reactive, computed, watch } from "vue";

const props = defineProps({
  onlyItems: { type: Array, required: true },
  conflicts: { type: Array, required: true },
  temPlanilhaClientes: { type: Boolean, default: false },
});

const onlyState = reactive({});
const conflictState = reactive({});

function initOnlyState() {
  for (const key of Object.keys(onlyState)) delete onlyState[key];
  for (const item of props.onlyItems) {
    onlyState[item.id] = {
      action: item.remembered || (props.temPlanilhaClientes ? "adicionar" : "ignorar"),
      // memoria global entre planilhas, nao "voce ja revisou isto aqui" - ver
      // o mesmo ajuste (e o motivo) em ClustersSection.vue.
      touched: false,
    };
  }
}
watch(() => [props.onlyItems, props.temPlanilhaClientes], initOnlyState, { immediate: true });

function initConflictState() {
  for (const key of Object.keys(conflictState)) delete conflictState[key];
  for (const item of props.conflicts) {
    conflictState[item.id] = {
      action: item.remembered || "manter",
      // memoria global entre planilhas, nao "voce ja revisou isto aqui" - ver
      // o mesmo ajuste (e o motivo) em ClustersSection.vue.
      touched: false,
    };
  }
}
watch(() => props.conflicts, initConflictState, { immediate: true });

function markOnlyTouched(id) {
  onlyState[id].touched = true;
}
function markConflictTouched(id) {
  conflictState[id].touched = true;
}

function sourceLabel(source) {
  return source === "advbox_pessoas" ? "cadastro de pessoas" : "parte de processo";
}

function restaurar(salvasOnly, salvasConflitos) {
  let n = 0;
  const porNorm = new Map((salvasOnly || []).map((d) => [d.norm, d]));
  for (const item of props.onlyItems) {
    const d = porNorm.get(item.norm);
    if (!d || !onlyState[item.id]) continue;
    onlyState[item.id].action = d.action;
    n++;
  }
  const porKey = new Map((salvasConflitos || []).map((d) => [d.key, d]));
  for (const item of props.conflicts) {
    const d = porKey.get(item.key);
    if (!d || !conflictState[item.id]) continue;
    conflictState[item.id].action = d.action;
    n++;
  }
  return n;
}

function collectOnlyDecisions() {
  return props.onlyItems.map((item) => ({
    norm: item.norm,
    action: onlyState[item.id].action,
  }));
}

function collectConflictDecisions() {
  return props.conflicts.map((item) => ({
    key: item.key,
    action: conflictState[item.id].action,
    advbox_value: item.advbox_value,
  }));
}

const touchedCount = computed(() => (
  Object.values(onlyState).filter((s) => s.touched).length +
  Object.values(conflictState).filter((s) => s.touched).length
));

defineExpose({ restaurar, collectOnlyDecisions, collectConflictDecisions, touchedCount });
</script>

<template>
  <section id="advbox-section">
    <h2>8. ADVBOX</h2>

    <h3>Conflitos de dados com o ADVBOX</h3>
    <p class="hint">
      Estes clientes têm o <b>mesmo nome</b> cadastrado na planilha de Clientes e na conta do ADVBOX, mas algum campo
      está com valor <b>diferente</b> nos dois lugares. O sistema nunca escolhe sozinho — decida qual valor vale.
    </p>
    <div v-if="conflicts.length === 0" class="hint">Nenhum conflito de dados encontrado entre a planilha de Clientes e o ADVBOX.</div>
    <div v-else>
      <div
        v-for="item in conflicts"
        :key="item.id"
        class="conflict-card"
        :class="{ 'is-touched': conflictState[item.id] && conflictState[item.id].touched }"
      >
        <div class="cluster-header">
          <span class="badge conflict">{{ item.field }}</span>
          <span v-if="item.remembered" class="badge badge-remembered">visto em outro processo</span>
        </div>
        <div class="variant-row"><span class="variant-text">{{ item.text }}</span></div>
        <div class="conflict-values" v-if="conflictState[item.id]">
          <div><b>Cadastro de Clientes</b>{{ item.local_value }}</div>
          <div><b>ADVBOX</b>{{ item.advbox_value }}</div>
        </div>
        <div class="action-row" v-if="conflictState[item.id]">
          <label>
            <input type="radio" :name="`advboxconflict-${item.id}`" value="usar_advbox" v-model="conflictState[item.id].action" @change="markConflictTouched(item.id)">
            Usar valor do ADVBOX
          </label>
          <label>
            <input type="radio" :name="`advboxconflict-${item.id}`" value="manter" v-model="conflictState[item.id].action" @change="markConflictTouched(item.id)">
            Manter valor atual
          </label>
        </div>
      </div>
    </div>

    <h3>Nomes que só existem na conta do ADVBOX</h3>
    <p class="hint">
      Esses nomes estão cadastrados na conta do ADVBOX (pessoas ou partes de processos), mas não aparecem — nem
      parecido — na sua planilha atual. Marque <b>adicionar</b> para incluir na planilha de Clientes, ou
      <b>ignorar</b> quando não fizer sentido (ex: um banco ou empresa que só aparece como parte contrária, não como
      cliente de verdade).
    </p>
    <p v-if="!temPlanilhaClientes" class="hint warning-hint">
      Você não enviou uma planilha de Clientes nesta sessão — os nomes abaixo são só informativos; para adicioná-los
      de verdade, envie a planilha de Clientes e analise de novo.
    </p>

    <div class="clusters-grid">
      <p v-if="onlyItems.length === 0">Todo mundo que existe na conta do ADVBOX já bate (ou é parecido) com algo nesta planilha.</p>
      <div
        v-for="item in onlyItems"
        :key="item.id"
        class="cluster-card"
        :class="{ 'is-touched': onlyState[item.id] && onlyState[item.id].touched }"
      >
        <div class="cluster-header">
          <span class="badge badge-advbox">ADVBOX · {{ sourceLabel(item.source) }}</span>
          <span v-if="item.remembered" class="badge badge-remembered">visto em outro processo</span>
        </div>

        <div class="variants-col" v-if="onlyState[item.id]">
          <div class="variant-row"><span class="variant-text">"{{ item.text }}"</span></div>
        </div>

        <div class="decision-col" v-if="onlyState[item.id]">
          <div class="action-row">
            <label>
              <input
                type="radio"
                :name="`advbox-${item.id}`"
                value="adicionar"
                :disabled="!temPlanilhaClientes"
                v-model="onlyState[item.id].action"
                @change="markOnlyTouched(item.id)"
              >
              Adicionar na planilha de Clientes
            </label>
            <label>
              <input type="radio" :name="`advbox-${item.id}`" value="ignorar" v-model="onlyState[item.id].action" @change="markOnlyTouched(item.id)">
              Ignorar
            </label>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
