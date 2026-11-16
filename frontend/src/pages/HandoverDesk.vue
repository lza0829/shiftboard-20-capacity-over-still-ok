<script setup>
import { onMounted, ref } from 'vue'
import { getJson, postJson } from '../api'

const shifts = ref([])
const fromId = ref(1)
const toId = ref(2)
const current = ref(null)
const precheck = ref(null)
const verdict = ref(null)
const lastDone = ref(null)
const msg = ref('')
const ok = ref(false)

async function refresh() {
  shifts.value = await getJson('/api/shifts')
  const logs = await getJson('/api/handovers')
  const active = logs.find((h) => h.status === '进行中') || null
  current.value = active ? await getJson(`/api/handovers/${active.id}`) : null
  if (current.value) {
    precheck.value = await getJson(`/api/handovers/${current.value.id}/precheck`)
    // 容量裁决只读接口：预检快照 vs 事后在途实数（同源于批次表）
    verdict.value = await getJson(`/api/handovers/${current.value.id}/capacity-verdict`)
  } else {
    precheck.value = null
    verdict.value = null
  }
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
      <h2>容量预检（实时预览，未固化）· 交班单 #{{ current.id }}</h2>
      <p class="lead" style="margin-bottom:8px">
        接班方 {{ precheck.to_shift_name }}：当前在途 {{ precheck.当前在途 }} + 本单 {{ precheck.本单键数 }} 键
        = {{ precheck.当前在途 + precheck.本单键数 }} / 上限 {{ precheck.上限 }}，差值 {{ precheck.差值 }}
        <span class="tag" :class="{ on: precheck.差值 >= 0, danger: precheck.差值 < 0 }">{{ precheck.裁决 }}</span>
      </p>
      <table>
        <thead>
          <tr><th>预检字段</th><th>接班方当前在途</th><th>本单将过户键数</th><th>在途上限</th><th>差值（上限−在途−键数）</th></tr>
        </thead>
        <tbody>
          <tr>
            <td>数值（与批次在途数同源派生）</td>
            <td>{{ precheck.当前在途 }}</td>
            <td>{{ precheck.本单键数 }}</td>
            <td>{{ precheck.上限 }}</td>
            <td :class="{ 'num-danger': precheck.差值 < 0 }">{{ precheck.差值 }}</td>
          </tr>
        </tbody>
      </table>
      <p class="src-note">当前在途与本单键数均由 batches 表实时 COUNT 派生，不经过任何独立容量计数器。</p>
    </div>

    <div class="panel" v-if="verdict">
      <h2>容量裁决只读对照 · 交班单 #{{ verdict.handover_id }} · {{ verdict.交班单状态 }}</h2>
      <template v-if="verdict.预检快照">
        <p class="lead" style="margin-bottom:8px">
          固化裁决：<span class="tag" :class="{ on: verdict.预检快照.decision === '通过', danger: verdict.预检快照.decision === '拒绝' }">{{ verdict.预检快照.decision }}</span>
          <span v-if="verdict.预检快照.reason" class="reason-text">—— {{ verdict.预检快照.reason }}</span>
        </p>
        <table>
          <thead>
            <tr><th>预检快照字段（完成时同事务固化）</th><th>值</th></tr>
          </thead>
          <tbody>
            <tr><td>接班方当前在途</td><td>{{ verdict.预检快照.current_inflight }}</td></tr>
            <tr><td>本单清单键数</td><td>{{ verdict.预检快照.item_count }}</td></tr>
            <tr><td>在途上限</td><td>{{ verdict.预检快照.capacity_limit }}</td></tr>
            <tr><td>差值</td><td :class="{ 'num-danger': verdict.预检快照.headroom < 0 }">{{ verdict.预检快照.headroom }}</td></tr>
            <tr><td>裁决 / 原因</td><td>{{ verdict.预检快照.decision }}｜{{ verdict.预检快照.reason || '—' }}</td></tr>
            <tr><td>固化时间</td><td>{{ verdict.预检快照.created_at }}</td></tr>
          </tbody>
        </table>
        <h3 class="sub-h">事后在途实数对照（批次表实时派生）</h3>
        <table>
          <thead>
            <tr>
              <th>预检预判接班方在途</th><th>事后接班方在途实数</th><th>差值(事后−预判)</th>
              <th>预检上限</th><th>当前上限</th><th>上限是否改动</th><th>事后是否超容</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>{{ verdict.对照.预检预判接班方在途 }}</td>
              <td>{{ verdict.对照.事后接班方在途实数 }}</td>
              <td :class="{ 'num-danger': verdict.对照['在途差值(事后-预判)'] !== 0 }">
                {{ verdict.对照['在途差值(事后-预判)'] }}
              </td>
              <td>{{ verdict.对照.预检上限 }}</td>
              <td>{{ verdict.对照.当前上限 }}</td>
              <td>{{ verdict.对照.上限是否被改动 ? '是' : '否' }}</td>
              <td>
                <span class="tag" :class="{ danger: verdict.对照.事后是否超容, on: !verdict.对照.事后是否超容 }">
                  {{ verdict.对照.事后是否超容 ? '超容' : '未超容' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </template>
      <template v-else>
        <p class="lead" style="margin-bottom:8px">尚无固化预检快照（交班单未完成或曾整单回滚），仅展示事后实数。</p>
        <table>
          <thead><tr><th>接班方在途实数</th><th>当前上限</th><th>剩余差值</th></tr></thead>
          <tbody>
            <tr>
              <td>{{ verdict.事后实数.接班方在途实数 }}</td>
              <td>{{ verdict.事后实数.当前上限 }}</td>
              <td :class="{ 'num-danger': verdict.事后实数.剩余差值 < 0 }">{{ verdict.事后实数.剩余差值 }}</td>
            </tr>
          </tbody>
        </table>
      </template>
      <p class="src-note">只读接口 GET /api/handovers/{{ verdict.handover_id }}/capacity-verdict；事后实数与班次在途数同源于 batches 表 COUNT。</p>
    </div>

    <div class="panel" v-if="lastDone && lastDone.precheck">
      <h2>上一次完成响应 · 交班单 #{{ lastDone.id }} · {{ lastDone.status }}</h2>
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
