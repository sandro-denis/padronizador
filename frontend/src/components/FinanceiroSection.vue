<script setup>
import { reactive, computed, watch, ref, onMounted, onUnmounted } from "vue";

const props = defineProps({
  items: { type: Array, required: true },
});

const state = reactive({});

function initState() {
  for (const key of Object.keys(state)) delete state[key];
  for (const item of props.items) {
    state[item.id] = {
      // "mover" e o padrao: o nome nao existe em Processos nem em Clientes,
      // entao deixar na coluna do cliente criaria um cadastro fantasma na
      // importacao. Ainda assim nada e aplicado sem passar pela previa.
      action: item.remembered || "mover",
      // memoria global entre planilhas, nao "voce ja revisou isto aqui" -
      // mesmo ajuste (e motivo) de ClustersSection.vue.
      touched: false,
    };
  }
}
watch(() => props.items, initState, { immediate: true });

function markTouched(id) {
  state[id].touched = true;
}

function formatRowList(rows, maxShow = 6) {
  if (!rows || !rows.length) return "";
  if (rows.length <= maxShow) return rows.join(", ");
  return rows.slice(0, maxShow).join(", ") + ` e mais ${rows.length - maxShow}`;
}

function moverTodos() {
  for (const item of props.items) {
    state[item.id].action = "mover";
    state[item.id].touched = true;
  }
}

function manterTodos() {
  for (const item of props.items) {
    state[item.id].action = "manter";
    state[item.id].touched = true;
  }
}

const touchedCount = computed(() => Object.values(state).filter((s) => s.touched).length);

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
    touched: !!state[item.id].touched,
  }));
}

defineExpose({ restaurar, collectDecisions, touchedCount });

// Mesmo padrao das outras secoes: atalho so age com o mouse sobre a lista e
// nunca com foco em campo de texto.
const isHovered = ref(false);
function onKeydown(e) {
  if (!isHovered.value) return;
  const tag = document.activeElement?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  if (e.key === "A" && e.shiftKey) { e.preventDefault(); moverTodos(); }
  if (e.key === "I" && e.shiftKey) { e.preventDefault(); manterTodos(); }
}
onMounted(() => window.addEventListener("keydown", onKeydown));
onUnmounted(() => window.removeEventListener("keydown", onKeydown));
</script>

<template>
  <section id="financeiro-section" @mouseenter="isHovered = true" @mouseleave="isHovered = false">
    <h2>7. Financeiro sem cadastro</h2>
    <p class="hint">
      Estes nomes aparecem em lançamentos da planilha de <b>Financeiro</b>, mas não existem — nem iguais, nem parecidos —
      na planilha de Processos nem na de Clientes. Manter um nome assim na coluna <b>NOME DO CLIENTE</b> cria um cadastro
      fantasma na importação, então a sugestão é tirá-lo de lá e guardá-lo no <b>início da descrição</b> do lançamento
      (separado por <code>;</code>), sem perder a informação de quem era.
    </p>

    <div class="toolbar" v-if="items.length">
      <div class="bulk-actions">
        <button type="button" class="secondary small" @click="moverTodos">Mover todos para a descrição</button>
        <button type="button" class="secondary small" @click="manterTodos">Manter todos como estão</button>
        <span class="shortcut-hint"><kbd>Shift</kbd>+<kbd>A</kbd> mover tudo · <kbd>Shift</kbd>+<kbd>I</kbd> manter tudo (com o mouse sobre a lista)</span>
      </div>
    </div>

    <div class="clusters-grid">
      <p v-if="items.length === 0">Todos os nomes dos lançamentos financeiros existem na planilha de Processos ou na de Clientes.</p>
      <div
        v-for="item in items"
        :key="item.id"
        class="cluster-card"
        :class="{ 'is-touched': state[item.id] && state[item.id].touched }"
      >
        <div class="cluster-header">
          <span class="badge conflict">sem cadastro</span>
          <span class="badge reason">{{ item.count }}x no financeiro</span>
          <span v-if="item.remembered" class="badge badge-remembered">decisão lembrada</span>
        </div>

        <div class="variants-col" v-if="state[item.id]">
          <div class="variant-row"><span class="variant-text">"{{ item.text }}"</span></div>
          <div class="variant-row">
            <span class="variant-counts">Linha{{ item.rows.length > 1 ? "s" : "" }} {{ formatRowList(item.rows) }}</span>
          </div>
          <div class="variant-row" v-if="state[item.id].action === 'mover'">
            <span class="variant-text">Descrição ficará: <b>{{ item.descricao_preview }}</b></span>
          </div>
        </div>

        <div class="decision-col" v-if="state[item.id]">
          <div class="action-row">
            <label>
              <input type="radio" :name="`financeiro-${item.id}`" value="mover" v-model="state[item.id].action" @change="markTouched(item.id)">
              Mover para a descrição
            </label>
            <label>
              <input type="radio" :name="`financeiro-${item.id}`" value="manter" v-model="state[item.id].action" @change="markTouched(item.id)">
              Manter como está
            </label>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
