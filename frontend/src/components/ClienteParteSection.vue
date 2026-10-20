<script setup>
import { reactive, computed, watch } from "vue";

const props = defineProps({
  items: { type: Array, required: true },
});

const state = reactive({});

function initState() {
  for (const key of Object.keys(state)) delete state[key];
  for (const item of props.items) {
    state[item.id] = {
      action: item.remembered || "skip",
      // memoria global entre planilhas, nao "voce ja revisou isto aqui" - ver
      // o mesmo ajuste (e o motivo) em ClustersSection.vue.
      touched: false,
    };
  }
}
watch(() => props.items, initState, { immediate: true });

function markTouched(id) {
  state[id].touched = true;
}

function formatRowList(rows, maxShow = 6) {
  if (rows.length <= maxShow) return rows.join(", ");
  return rows.slice(0, maxShow).join(", ") + ` e mais ${rows.length - maxShow}`;
}

function collectDecisions() {
  return props.items.map((item) => ({
    norm: item.norm,
    action: state[item.id].action,
    // so grava regra do que o usuario realmente decidiu - ver app.py
    touched: !!state[item.id].touched,
  }));
}

const touchedCount = computed(() => Object.values(state).filter((s) => s.touched).length);

defineExpose({ collectDecisions, touchedCount });
</script>

<template>
  <section id="cliente-parte-section">
    <h2>5. Cliente × Parte Contrária</h2>
    <p class="hint">
      Estes nomes aparecem ao mesmo tempo como <b>Cliente</b> e como <b>Parte Contrária</b> em processos diferentes —
      pode ser coincidência de nome ou um erro de preenchimento. Revise e escolha o que fazer.
    </p>

    <div class="clusters-grid">
      <p v-if="items.length === 0">Nenhum nome aparece como Cliente e como Parte Contrária ao mesmo tempo.</p>
      <div
        v-for="item in items"
        :key="item.id"
        class="cluster-card"
        :class="{ 'is-touched': state[item.id] && state[item.id].touched }"
      >
        <div class="cluster-header">
          <span class="badge score-mid">{{ item.n_cliente }}x cliente</span>
          <span class="badge score-mid">{{ item.n_parte_contraria }}x parte contrária</span>
          <span v-if="item.same_row" class="badge reason">mesma linha</span>
          <span v-if="item.remembered" class="badge badge-remembered">visto em outro processo</span>
        </div>

        <div class="variants-col" v-if="state[item.id]">
          <div class="variant-row"><span class="variant-text">"{{ item.text }}"</span></div>
          <div class="variant-row">
            <span class="variant-text">Como Cliente: linha{{ item.cliente_rows.length > 1 ? "s" : "" }} {{ formatRowList(item.cliente_rows) }}</span>
          </div>
          <div class="variant-row">
            <span class="variant-text">Como Parte Contrária: linha{{ item.parte_rows.length > 1 ? "s" : "" }} {{ formatRowList(item.parte_rows) }}</span>
          </div>
        </div>

        <div class="decision-col" v-if="state[item.id]">
          <div class="action-row">
            <label>
              <input type="radio" :name="`clienteparte-${item.id}`" value="only_parte" v-model="state[item.id].action" @change="markTouched(item.id)">
              Manter só em Parte Contrária
            </label>
            <label>
              <input type="radio" :name="`clienteparte-${item.id}`" value="only_cliente" v-model="state[item.id].action" @change="markTouched(item.id)">
              Manter só em Cliente
            </label>
            <label>
              <input type="radio" :name="`clienteparte-${item.id}`" value="skip" v-model="state[item.id].action" @change="markTouched(item.id)">
              Não alterar
            </label>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
