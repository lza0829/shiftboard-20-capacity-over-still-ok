<script setup>
import { onMounted, ref } from 'vue'
import { getJson } from '../api'

const rows = ref([])
const prechecks = ref({})
const err = ref('')

onMounted(async () => {
  try {
    rows.value = await getJson('/api/handovers')
    // 预检报告表按交班单 id 落库，取回后按 handover_id 关联展示
    const list = await getJson('/api/handovers/prechecks')
    const m = {}
    for (const p of list) m[p.handover_id] = p
    prechecks.value = m
  } catch (e) {
    err.value = String(e.message || e)
  }
})
</script>

<template>
  <div>
    <h1>交班记录</h1>
    <p class="lead">每单交班留档：双方班次、清单批次数、最终状态，以及完成时同事务固化的容量预检快照。</p>
    <p v-if="err" class="msg">{{ err }}</p>
    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>单号</th><th>交班方</th><th>接班方</th><th>批次数</th><th>状态</th><th>原因</th>
            <th>预检·当前在途</th><th>预检·清单键数</th><th>预检·上限</th><th>预检·差值</th><th>预检裁决</th>
            <th>开始</th><th>结束</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="h in rows" :key="h.id">
            <td>#{{ h.id }}</td>
            <td>{{ h.from_shift_name }}</td>
            <td>{{ h.to_shift_name }}</td>
            <td>{{ h.batch_count }}</td>
            <td>{{ h.status }}</td>
            <td>{{ h.reason || '—' }}</td>
            <template v-if="prechecks[h.id]">
              <td>{{ prechecks[h.id].current_inflight }}</td>
              <td>{{ prechecks[h.id].item_count }}</td>
              <td>{{ prechecks[h.id].capacity_limit }}</td>
              <td :class="{ 'num-danger': prechecks[h.id].headroom < 0 }">{{ prechecks[h.id].headroom }}</td>
              <td>
                <span class="tag" :class="{
                  on: prechecks[h.id].decision === '通过',
                  danger: prechecks[h.id].decision === '拒绝',
                }">{{ prechecks[h.id].decision }}</span>
              </td>
            </template>
            <template v-else>
              <td colspan="5" class="muted-cell">未固化（进行中或曾整单回滚）</td>
            </template>
            <td>{{ h.started_at }}</td>
            <td>{{ h.finished_at || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p class="src-note">预检快照字段取自 capacity_prechecks 表；其中「当前在途」完成时与批次表在途数同源派生。</p>
    </div>
  </div>
</template>
