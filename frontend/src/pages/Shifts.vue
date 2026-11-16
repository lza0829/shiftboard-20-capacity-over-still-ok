<script setup>
import { onMounted, ref } from 'vue'
import { getJson, putJson } from '../api'

const rows = ref([])
const limits = ref({})
const err = ref('')
const okMsg = ref('')

async function refresh() {
  rows.value = await getJson('/api/shifts')
  const m = {}
  for (const s of rows.value) m[s.id] = s.inflight_limit
  limits.value = m
}

onMounted(async () => {
  try {
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
})

async function save(id) {
  err.value = ''
  okMsg.value = ''
  try {
    await putJson(`/api/shifts/${id}/capacity`, { inflight_limit: Number(limits.value[id]) })
    okMsg.value = `班次 #${id} 在途上限已保存`
    await refresh()
  } catch (e) {
    err.value = String(e.message || e)
  }
}
</script>

<template>
  <div>
    <h1>班次</h1>
    <p class="lead">每个班次有固定值班人；在途上限为正整数，完成交班前按“接班方当前在途 + 本单键数 ≤ 上限”预检，超限整单拒绝。</p>
    <p v-if="err" class="msg">{{ err }}</p>
    <p v-if="okMsg" class="msg ok">{{ okMsg }}</p>
    <div class="panel">
      <table>
        <thead><tr><th>编号</th><th>班次</th><th>值班人</th><th>状态</th><th>当前在途</th><th>在途上限</th><th>剩余差值（上限−在途）</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="s in rows" :key="s.id">
            <td>{{ s.id }}</td>
            <td>{{ s.name }}</td>
            <td>{{ s.keeper }}</td>
            <td>{{ s.status }}</td>
            <td>{{ s.inflight }}</td>
            <td>
              <input type="number" min="1" step="1" v-model.number="limits[s.id]" />
            </td>
            <td :class="{ 'num-danger': s.inflight_limit - s.inflight < 0 }">
              {{ s.inflight_limit - s.inflight }}
            </td>
            <td><button class="btn ghost" @click="save(s.id)">保存上限</button></td>
          </tr>
        </tbody>
      </table>
      <p class="src-note">当前在途由 batches 表 COUNT 同源派生，与交班预检快照、容量裁决接口同一口径，无独立容量计数器。</p>
    </div>
  </div>
</template>
