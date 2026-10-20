<script setup>
import { reactive, ref, computed, watch, onMounted, onUnmounted } from "vue";

import { config } from "../config";

const props = defineProps({
  clusters: { type: Array, required: true },
});

const state = reactive({});
const filter = ref("all");

function initState() {
  for (const key of Object.keys(state)) delete state[key];
  for (const c of props.clusters) {
    const remembered = c.remembered_canonical;
    const isRememberedCustom = !!remembered && !c.variants.some((v) => v.text === remembered);
    state[c.id] = {
      action: remembered ? "merge" : (c.cpf_conflict ? "ignore" : "merge"),
      canonical: remembered && !isRememberedCustom ? remembered : c.suggested_canonical,
      useCustom: isRememberedCustom,
      customCanonical: isRememberedCustom ? remembered : c.suggested_canonical,
      excluded: new Set(),
      // `remembered_canonical` e memoria GLOBAL entre planilhas/clientes (ex:
      // um nome de parte contraria ja resolvido num processo de outro
      // cliente) - so preenche o valor sugerido, nao significa que VOCE
      // revisou este grupo NESTA planilha. Comecar com touched=true fazia o
      // card aparecer com o carimbo de "conferido" e sumir dos "Pendentes"
      // antes de qualquer clique seu, mesmo sendo a primeira vez que voce via
      // aquele cliente - so vira true quando voce mexe de verdade (ver
      // AcaoValidationSection, que ja fazia certo).
      touched: false,
    };
  }
}
watch(() => props.clusters, initState, { immediate: true });

function markTouched(id) {
  state[id].touched = true;
}

function toggleExclude(id, norm, checked) {
  if (checked) state[id].excluded.add(norm);
  else state[id].excluded.delete(norm);
  markTouched(id);
}

function onCanonicalChange(c, value) {
  if (value === "__custom__") {
    state[c.id].useCustom = true;
  } else {
    state[c.id].useCustom = false;
    state[c.id].canonical = value;
  }
  markTouched(c.id);
}

function reasonLabel(reason) {
  const map = {
    exact: "idêntico",
    fuzzy: "parecido",
    subset: "nome incompleto/abreviado",
    subset_initial: "inicial abreviada",
    mesmo_cpf: "mesmo CPF",
    confirmado: "confirmado antes",
    mesmo_prenome_sobrenome: "mesmo nome/sobrenome, meio diferente",
    mesma_celula: "mesma célula/linha",
    marca_comum: "mesma marca, filial diferente",
    mesmo_normalizado: "grafia inconsistente (acento/maiúscula)",
  };
  return map[reason] || reason;
}

function scoreClass(score) {
  if (score >= 95) return "score-high";
  if (score >= 88) return "score-mid";
  return "score-low";
}

function formatRowList(rows, maxShow = 6) {
  if (rows.length <= maxShow) return rows.join(", ");
  return rows.slice(0, maxShow).join(", ") + ` e mais ${rows.length - maxShow}`;
}

function variantLocation(v) {
  const parts = [];
  const rowsCliente = v.rows_cliente || [];
  const rowsParte = v.rows_parte || [];
  const rowsClientes = v.rows_clientes || [];
  if (rowsCliente.length) {
    parts.push(`Cliente: linha${rowsCliente.length > 1 ? "s" : ""} ${formatRowList(rowsCliente)}`);
  }
  if (rowsParte.length) {
    parts.push(`Parte contrária: linha${rowsParte.length > 1 ? "s" : ""} ${formatRowList(rowsParte)}`);
  }
  if (rowsClientes.length) {
    parts.push(`Clientes: linha${rowsClientes.length > 1 ? "s" : ""} ${formatRowList(rowsClientes)}`);
  }
  if (v.count_advbox) {
    parts.push("ADVBOX");
  }
  return parts.join(" · ");
}

const filteredClusters = computed(() => props.clusters.filter((c) => {
  if (filter.value === "pending") return !state[c.id]?.touched;
  if (filter.value === "conflict") return c.cpf_conflict;
  return true;
}));

function acceptAllPending() {
  for (const c of props.clusters) {
    if (!state[c.id].touched) {
      state[c.id].action = "merge";
      state[c.id].touched = true;
    }
  }
}

function ignoreAllPending() {
  for (const c of props.clusters) {
    if (!state[c.id].touched) {
      state[c.id].action = "ignore";
      state[c.id].touched = true;
    }
  }
}

function collectDecisions() {
  return props.clusters.map((c) => {
    const s = state[c.id];
    const canonical = s.useCustom ? s.customCanonical : s.canonical;
    const excludedMembers = c.variants.filter((v) => s.excluded.has(v.norm)).map((v) => v.norm);
    const keptMembers = c.members.filter((n) => !excludedMembers.includes(n));
    return {
      cluster_id: c.id,
      members: keptMembers,
      excluded_members: excludedMembers,
      action: s.action,
      canonical,
      // so o que o usuario realmente decidiu vira regra guardada - ver app.py
      touched: !!s.touched,
    };
  });
}

const touchedCount = computed(() => Object.values(state).filter((s) => s.touched).length);

defineExpose({ collectDecisions, touchedCount });

// Atalhos: so agem enquanto o mouse esta sobre a secao (evita disparar
// enquanto o usuario digita em outro card na tela) e nunca com foco em
// campo de texto (senao "i" de "digitar nome" viraria um atalho).
const isHovered = ref(false);
function onKeydown(e) {
  if (!isHovered.value) return;
  const tag = document.activeElement?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  if (e.key === "A" && e.shiftKey) { e.preventDefault(); acceptAllPending(); }
  if (e.key === "I" && e.shiftKey) { e.preventDefault(); ignoreAllPending(); }
}
onMounted(() => window.addEventListener("keydown", onKeydown));
onUnmounted(() => window.removeEventListener("keydown", onKeydown));
</script>

<template>
  <section id="clusters-section" @mouseenter="isHovered = true" @mouseleave="isHovered = false">
    <h2>3. Revise os grupos encontrados</h2>
    <p class="hint">
      Cada grupo abaixo é um conjunto de nomes que o sistema acha que são a <b>mesma pessoa</b> escrita de formas
      diferentes — inclusive grafias vindas da conta do ADVBOX, marcadas com o selo
      <span class="badge badge-advbox">ADVBOX</span>. Escolha o nome final (ou digite um) e confirme. Se não for a
      mesma pessoa, marque "não é a mesma pessoa"<span v-if="config.memoria"> — o sistema vai lembrar disso da próxima
      vez</span>.
    </p>

    <div class="toolbar">
      <div class="filter-tabs">
        <button type="button" class="filter-tab" :class="{ active: filter === 'all' }" @click="filter = 'all'">Todos</button>
        <button type="button" class="filter-tab" :class="{ active: filter === 'pending' }" @click="filter = 'pending'">Pendentes</button>
        <button type="button" class="filter-tab" :class="{ active: filter === 'conflict' }" @click="filter = 'conflict'">Conflitos de CPF</button>
      </div>
      <div class="bulk-actions">
        <button type="button" class="secondary small" @click="acceptAllPending">Aceitar sugestão nos pendentes</button>
        <button type="button" class="secondary small" @click="ignoreAllPending">Ignorar todos os pendentes</button>
        <span class="shortcut-hint"><kbd>Shift</kbd>+<kbd>A</kbd> aceitar · <kbd>Shift</kbd>+<kbd>I</kbd> ignorar (com o mouse sobre a lista)</span>
      </div>
    </div>

    <div class="clusters-grid">
      <p v-if="clusters.length === 0">Nenhum grupo de nomes parecidos encontrado.</p>
      <div
        v-for="c in filteredClusters"
        :key="c.id"
        class="cluster-card"
        :class="{ 'is-touched': state[c.id] && state[c.id].touched }"
      >
        <div class="cluster-header">
          <span class="badge badge-confidence" :class="scoreClass(c.score)">{{ c.score.toFixed(1) }}%</span>
          <span v-for="r in c.reasons" :key="r" class="badge reason">{{ reasonLabel(r) }}</span>
          <span v-if="c.has_advbox" class="badge badge-advbox">ADVBOX</span>
          <span v-if="c.cpf_conflict" class="badge conflict">CONFLITO DE CPF</span>
          <span v-if="c.remembered_canonical" class="badge badge-remembered">nome já visto em outro processo</span>
        </div>

        <div class="variants-col" v-if="state[c.id]">
          <div
            v-for="v in c.variants"
            :key="v.text"
            class="variant-row"
            :class="{ 'variant-excluded': state[c.id].excluded.has(v.norm) }"
          >
            <label class="variant-exclude" title="Não faz parte deste grupo - excluir da fusão">
              <input
                type="checkbox"
                :checked="state[c.id].excluded.has(v.norm)"
                @change="toggleExclude(c.id, v.norm, $event.target.checked)"
              >
            </label>
            <span class="variant-text">{{ v.text }}</span>
            <span class="variant-counts">{{ variantLocation(v) }}</span>
          </div>
        </div>

        <div class="decision-col" v-if="state[c.id]">
          <div class="canonical-row">
            <label>Nome final:</label>
            <select
              :value="state[c.id].useCustom ? '__custom__' : state[c.id].canonical"
              @change="onCanonicalChange(c, $event.target.value)"
            >
              <option v-for="v in c.variants" :key="v.text" :value="v.text">{{ v.text }}</option>
              <option value="__custom__">Outro (digitar)...</option>
            </select>
            <input
              v-if="state[c.id].useCustom"
              type="text"
              placeholder="nome final..."
              v-model="state[c.id].customCanonical"
              @input="markTouched(c.id)"
            >
          </div>

          <div class="action-row">
            <label>
              <input type="radio" :name="`action-${c.id}`" value="merge" v-model="state[c.id].action" @change="markTouched(c.id)">
              Aplicar (é a mesma pessoa)
            </label>
            <label>
              <input type="radio" :name="`action-${c.id}`" value="ignore" v-model="state[c.id].action" @change="markTouched(c.id)">
              Não é a mesma pessoa
            </label>
          </div>
        </div>

        <div v-if="c.cpf_conflict" class="conflict-warning">
          Atenção: esses nomes têm CPFs diferentes ({{ c.cpfs.join(", ") }}) — provavelmente são pessoas diferentes,
          não homônimos. Revise com cuidado antes de aplicar.
        </div>
      </div>
    </div>
  </section>
</template>
