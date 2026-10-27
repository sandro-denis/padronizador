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
      action: item.remembered || "remove",
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

function reasonLabel(reason) {
  if (reason === "juiz") return "juiz/desembargador";
  if (reason === "institucional") return "referência institucional";
  return "tribunal/vara/comarca";
}

function restaurar(salvas) {
  if (!salvas || !salvas.length) return 0;
  const porNorm = new Map(salvas.map((d) => [d.norm, d]));
  let n = 0;
  for (const item of props.items) {
    const d = porNorm.get(item.norm);
    if (!d || !state[item.id]) continue;
    state[item.id].action = d.action;
    state[item.id].touched = !!d.touched;
    n++;
  }
  return n;
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

defineExpose({ restaurar, collectDecisions, touchedCount });
</script>

<template>
  <section id="court-judge-section">
    <h2>6. Tribunal / Vara / Comarca / Juiz</h2>
    <p class="hint">
      Estes valores parecem ser nomes de tribunal, vara, comarca, juiz, ou referências institucionais genéricas (como
      "justiça pública") — não nomes de cliente ou parte contrária de verdade. Provavelmente vieram de um
      preenchimento errado na planilha do Escavador.
    </p>

    <div class="clusters-grid">
      <p v-if="items.length === 0">Nenhum nome de tribunal, vara, comarca ou juiz encontrado.</p>
      <div
        v-for="item in items"
        :key="item.id"
        class="cluster-card"
        :class="{ 'is-touched': state[item.id] && state[item.id].touched }"
      >
        <div class="cluster-header">
          <span class="badge reason">{{ reasonLabel(item.reason) }}</span>
          <span v-if="item.n_cliente" class="badge score-mid">{{ item.n_cliente }}x cliente</span>
          <span v-if="item.n_parte_contraria" class="badge score-mid">{{ item.n_parte_contraria }}x parte contrária</span>
          <span v-if="item.remembered" class="badge badge-remembered">visto em outro processo</span>
        </div>

        <div class="variants-col" v-if="state[item.id]">
          <div class="variant-row"><span class="variant-text">"{{ item.text }}"</span></div>
          <div class="variant-row" v-if="item.cliente_rows.length">
            <span class="variant-text">Como Cliente: linha{{ item.cliente_rows.length > 1 ? "s" : "" }} {{ formatRowList(item.cliente_rows) }}</span>
          </div>
          <div class="variant-row" v-if="item.parte_rows.length">
            <span class="variant-text">Como Parte Contrária: linha{{ item.parte_rows.length > 1 ? "s" : "" }} {{ formatRowList(item.parte_rows) }}</span>
          </div>
        </div>

        <div class="decision-col" v-if="state[item.id]">
          <div class="action-row">
            <label>
              <input type="radio" :name="`courtjudge-${item.id}`" value="remove" v-model="state[item.id].action" @change="markTouched(item.id)">
              Remover
            </label>
            <label>
              <input type="radio" :name="`courtjudge-${item.id}`" value="skip" v-model="state[item.id].action" @change="markTouched(item.id)">
              Manter como está
            </label>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
