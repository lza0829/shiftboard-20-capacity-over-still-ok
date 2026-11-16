<script setup>
import { onMounted, ref } from 'vue'
import { getJson, postJson } from '../api'

const shifts = ref([])
const fromId = ref(1)
const toId = ref(2)
const current = ref(null)
const precheck = ref(null)
const lastDone = ref(null)
const msg = ref('')
const ok = ref(false)

async function refresh() {
  shifts.value = await getJson('/api/shifts')
  const logs = await getJson('/api/handovers')
  const active = logs.find((h) => h.status === '进行中') || null
  current.value = active ? await getJson(`/api/handovers/${active.id}`) : null
  precheck.value = current.value ? await getJson(`/api/handovers/${current.value.id}/precheck`) : null
}

onMounted(async () => {
  try {
    await refresh()
  } catch (e) {
    msg.value = String(e.message || e)
  }
})

async function start() {
  msg.value = ''
  ok.value = false
  lastDone.value = null
  try {
    const res = await postJson('/api/handovers/start', {
      from_shift_id: Number(fromId.value),
      to_shift_id: Number(toId.value),
    })
    ok.value = true
    msg.value = `已开交班单 #${res.id}，清单 ${res.batch_count} 批`
    await refresh()
  } catch (e) {
    msg.value = String(e.message || e)
  }
}

async function complete() {
  if (!current.value) return
  msg.value = ''
  ok.value = false
  try {
    const res = await postJson(`/api/handovers/${current.value.id}/complete`)
    lastDone.value = res
    ok.value = res.status === '已完成'
    msg.value = res.status === '已完成'
      ? `交班单 #${res.id} 已完成，${res.batch_count} 批已过户`
      : `交班单 #${res.id} ${res.status}：${res.reason || '未通过'}`
    await refresh()
  } catch (e) {
    msg.value = String(e.message || e)
  }
}
</script>

<template>
  <div>
    <h1>交班办理</h1>
    <p class="lead">同一时刻只允许一单进行中的交班；完成前先按接班方在途上限预检，超限整单拒绝、零过户，裁决依据落库可查。</p>

    <div class="panel">
      <div class="row">
        <label>交班方
          <select v-model.number="fromId">
            <option v-for="s in shifts" :key="s.id" :value="s.id">{{ s.name }} · {{ s.keeper }}</option>
          </select>
        </label>
        <label>接班方
          <select v-model.number="toId">
            <option v-for="s in shifts" :key="'t'+s.id" :value="s.id">{{ s.name }} · {{ s.keeper }}（在途 {{ s.inflight }}/{{ s.inflight_limit }}）</option>
          </select>
        </label>
        <button class="btn" :disabled="!!current" @click="start">发起交班</button>
        <button class="btn ghost" :disabled="!current" @click="complete">完成交班</button>
      </div>
      <p class="msg" :class="{ ok }">{{ msg }}</p>
    </div>

    <div class="panel" v-if="current && precheck">
      <h2>容量预检（实时）· 交班单 #{{ current.id }}</h2>
      <p class="lead" style="margin-bottom:0">
        接班方 {{ precheck.to_shift_name }}：当前在途 {{ precheck.当前在途 }} + 本单 {{ precheck.本单键数 }} 键
        = {{ precheck.当前在途 + precheck.本单键数 }} / 上限 {{ precheck.上限 }}，差值 {{ precheck.差值 }}
        <span class="tag on">{{ precheck.差值 >= 0 ? precheck.裁决 : '通过' }}</span>
      </p>
    </div>

    <div class="panel" v-if="lastDone && lastDone.precheck">
      <h2>预检裁决（已落库）· 交班单 #{{ lastDone.id }} · {{ lastDone.status }}</h2>
      <p class="lead" style="margin-bottom:0">
        裁决 {{ lastDone.precheck.decision }}：当前在途 {{ lastDone.precheck.current_inflight }}
        + 清单 {{ lastDone.precheck.item_count }} 键 / 上限 {{ lastDone.precheck.capacity_limit }}，
        差值 {{ lastDone.precheck.headroom }}
        <span v-if="lastDone.precheck.reason">—— {{ lastDone.precheck.reason }}</span>
      </p>
    </div>

    <div class="panel" v-if="current">
      <h2>当前交班单 #{{ current.id }} · {{ current.status }}</h2>
      <p class="lead" style="margin-bottom:12px">
        {{ current.from_shift_name }} → {{ current.to_shift_name }} · 清单 {{ current.batch_count }} 批
      </p>
      <table>
        <thead><tr><th>业务键</th><th>标题</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="b in current.items || []" :key="b.id">
            <td>{{ b.biz_key }}</td>
            <td>{{ b.title }}</td>
            <td>{{ b.status }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
