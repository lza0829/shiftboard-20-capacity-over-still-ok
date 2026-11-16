<script setup>
import { onMounted, ref } from 'vue'
import { getJson } from '../api'

const rows = ref([])
const err = ref('')

onMounted(async () => {
  try {
    rows.value = await getJson('/api/batches')
  } catch (e) {
    err.value = String(e.message || e)
  }
})
</script>

<template>
  <div>
    <h1>在途批次</h1>
    <p class="lead">批次归属当前值班班次；交班完成后，在途批次应整批过户到接班方。</p>
    <p v-if="err" class="msg">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr><th>业务键</th><th>标题</th><th>归属班次</th><th>状态</th><th>备注</th></tr>
        </thead>
        <tbody>
          <tr v-for="b in rows" :key="b.id">
            <td>{{ b.biz_key }}</td>
            <td>{{ b.title }}</td>
            <td>{{ b.owner_shift_name || '—' }}</td>
            <td><span class="tag" :class="{ on: b.status === '在途' }">{{ b.status }}</span></td>
            <td>{{ b.note || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
