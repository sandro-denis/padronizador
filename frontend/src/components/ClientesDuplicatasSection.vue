<script setup>
import { reactive, watch } from "vue";

const props = defineProps({
  exactGroups: { type: Array, required: true },
  fuzzyGroups: { type: Array, required: true },
});

const FIELD_LABELS = {
  rg: "RG", data_nascimento: "Nascimento", estado_civil: "Estado civil",
  nacionalidade: "Nacionalidade", profissao: "Profissão", sexo: "Sexo",
  celular: "Celular", telefone: "Telefone", email: "E-mail",
  endereco: "Endereço", bairro: "Bairro", cidade: "Cidade", estado: "Estado",
  cep: "CEP", pais: "País", pis_pasep: "PIS/PASEP", ctps: "CTPS", cid: "CID",
  nome_mae: "Nome da mãe", origem: "Origem", anotacoes: "Anotações",
};
function fieldLabel(key) {
  return FIELD_LABELS[key] || key;
}

const rowDecisions = reactive({});

function initState() {
  for (const key of Object.keys(rowDecisions)) delete rowDecisions[key];
  for (const g of props.exactGroups) {
    for (const r of g.rows) {
      rowDecisions[r.row] = { remove: !r.suggested_keep, text: r.text };
    }
  }
  for (const g of props.fuzzyGroups) {
    for (const r of g.rows) {
      rowDecisions[r.row] = { remove: false, text: r.text };
    }
  }
}
watch(() => [props.exactGroups, props.fuzzyGroups], initState, { immediate: true });

function restaurar(salvas) {
  if (!salvas || !salvas.length) return 0;
  // aqui a chave estavel e o NUMERO DA LINHA: o mesmo arquivo reenviado tem
  // as mesmas linhas, e e por linha que a remocao e aplicada
  let n = 0;
  for (const d of salvas) {
    if (!rowDecisions[d.row]) continue;
    rowDecisions[d.row].remove = d.action === "remover";
    n++;
  }
  return n;
}

function statusLabel(status) {
  if (status === "mesmo_cpf") return "mesmo CPF — confirma ser a mesma pessoa";
  if (status === "cpf_diferente") return "CPF DIFERENTE — provavelmente não é a mesma pessoa";
  return "sem CPF nos dois lados — confira com cuidado";
}
function statusBadgeClass(status) {
  if (status === "mesmo_cpf") return "score-high";
  if (status === "cpf_diferente") return "conflict";
  return "score-mid";
}

function collectDecisions() {
  return Object.entries(rowDecisions).map(([row, d]) => ({
    row: Number(row),
    action: d.remove ? "remover" : "manter",
    text: d.text,
  }));
}

defineExpose({ restaurar, collectDecisions });
</script>

<template>
  <section id="clientes-duplicatas-section">
    <h2>4. Duplicatas na planilha de Clientes</h2>
    <p class="hint">
      Estas linhas parecem ser o <b>mesmo cliente cadastrado mais de uma vez</b> na sua planilha de Clientes.
      Compare os dados de cada linha abaixo e marque quais remover — por padrão já deixamos marcada pra remover a
      linha menos completa, mas a decisão final é sua.
    </p>

    <div v-if="exactGroups.length === 0 && fuzzyGroups.length === 0" class="hint">
      Nenhuma linha duplicada encontrada na planilha de Clientes.
    </div>

    <div class="clusters-grid">
      <div v-for="g in exactGroups" :key="`exact-${g.id}`" class="cluster-card">
        <div class="cluster-header">
          <span class="badge" :class="statusBadgeClass(g.status)">{{ statusLabel(g.status) }}</span>
          <span class="badge reason">{{ g.rows.length }} linhas</span>
        </div>
        <div class="dup-rows-grid">
          <div
            v-for="r in g.rows"
            :key="r.row"
            class="dup-row-card"
            :class="{ 'is-suggested-keep': r.suggested_keep, 'is-removing': rowDecisions[r.row] && rowDecisions[r.row].remove }"
          >
            <label class="dup-remove-toggle" v-if="rowDecisions[r.row]">
              <input type="checkbox" v-model="rowDecisions[r.row].remove">
              Remover esta linha
            </label>
            <div class="dup-row-title">
              Linha {{ r.row }}
              <span v-if="r.suggested_keep" class="badge badge-suggestion">sugestão: manter</span>
            </div>
            <div class="conflict-values">
              <div v-if="r.cpf"><b>CPF</b>{{ r.cpf }}</div>
              <div v-for="(val, key) in r.fields" :key="key"><b>{{ fieldLabel(key) }}</b>{{ val }}</div>
              <div v-if="!r.cpf && Object.keys(r.fields).length === 0" class="hint">Sem outros dados preenchidos nesta linha.</div>
            </div>
          </div>
        </div>
      </div>

      <div v-for="g in fuzzyGroups" :key="`fuzzy-${g.id}`" class="cluster-card">
        <div class="cluster-header">
          <span class="badge score-mid">nome parecido, não idêntico</span>
          <span class="badge reason">{{ g.score.toFixed(1) }}%</span>
        </div>
        <div class="dup-rows-grid">
          <div
            v-for="r in g.rows"
            :key="r.row"
            class="dup-row-card"
            :class="{ 'is-removing': rowDecisions[r.row] && rowDecisions[r.row].remove }"
          >
            <label class="dup-remove-toggle" v-if="rowDecisions[r.row]">
              <input type="checkbox" v-model="rowDecisions[r.row].remove">
              Remover esta linha
            </label>
            <div class="dup-row-title">Linha {{ r.row }} — {{ r.text }}</div>
            <div class="conflict-values">
              <div v-if="r.cpf"><b>CPF</b>{{ r.cpf }}</div>
              <div v-for="(val, key) in r.fields" :key="key"><b>{{ fieldLabel(key) }}</b>{{ val }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
