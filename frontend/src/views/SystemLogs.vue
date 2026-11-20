<template>
  <div class="system-logs">
    <h2>系统日志</h2>
    <el-card shadow="hover" class="system-log-card">
      <el-tabs v-model="tab">
        <el-tab-pane label="平台日志" name="platform" />
        <el-tab-pane label="设备日志" name="device" />
      </el-tabs>
      <PlatformLogs v-if="tab === 'platform'" />
      <DeviceLogs v-else />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import PlatformLogs from '@/components/system-logs/PlatformLogs.vue'
import DeviceLogs from '@/components/system-logs/DeviceLogs.vue'
const tab = ref('platform')
</script>

<style scoped>
.system-logs { min-width: 0; width: 100%; }
h2 { color: #303133; font-size: 24px; margin-bottom: 20px; }
.system-logs :deep(.log-toolbar) { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin: 12px 0; }
.system-logs :deep(.log-status) { color: #909399; font-size: 13px; }
.system-logs :deep(.log-alert) { margin: 12px 0; }
.system-logs :deep(.log-text) { height: 420px; overflow: auto; background: #1e1e1e; color: #d4d4d4; padding: 16px; white-space: pre-wrap; overflow-wrap: anywhere; font: 13px/1.65 Consolas, monospace; border-radius: 4px; }
.system-logs :deep(.el-pagination) { margin-top: 16px; flex-wrap: wrap; gap: 8px; }
.system-logs :deep(.log-filters .el-form-item) { margin-bottom: 12px; margin-right: 16px; }
.system-logs :deep(.log-filters .el-select) { width: 150px; }
.system-logs :deep(.log-filters .el-input) { width: 190px; }
.system-logs :deep(.log-table-pane) { height: 420px; }
.system-logs :deep(.log-content-pane .log-text) { height: 100%; }
@media (min-width: 761px) {
  .system-logs { display: flex; flex-direction: column; flex: 1; min-height: 600px; }
  h2 { flex-shrink: 0; }
  .system-log-card { display: flex; flex-direction: column; flex: 1; min-height: 0; }
  .system-log-card :deep(.el-card__body) { display: flex; flex-direction: column; flex: 1; min-height: 0; }
  .system-log-card :deep(.el-tabs) { flex-shrink: 0; }
  .system-logs :deep(.log-panel) { display: flex; flex-direction: column; flex: 1; min-height: 0; }
  .system-logs :deep(.log-panel > *) { flex-shrink: 0; }
  .system-logs :deep(.log-panel > .log-table-pane),
  .system-logs :deep(.log-panel > .log-content-pane) { flex: 1; min-height: 180px; height: auto; }
  .system-logs :deep(.log-content-pane .el-empty) { height: 100%; }
}
@media (max-width: 760px) {
  .system-logs :deep(.log-filters .el-form-item) { display: flex; margin-right: 0; }
  .system-logs :deep(.log-filters .el-form-item__content) { min-width: 0; }
  .system-logs :deep(.log-filters .el-date-editor) { width: 100%; min-width: 0; }
  .system-logs :deep(.log-text) { height: 340px; }
  .system-logs :deep(.log-content-pane) { height: 340px; }
}
</style>

<style>
@media (max-width: 760px) {
  .system-log-dates.el-picker__popper { max-width: calc(100vw - 24px); }
  .system-log-dates .el-date-range-picker { width: min(340px, calc(100vw - 24px)); max-height: 75vh; overflow: auto; }
  .system-log-dates .el-date-range-picker__content { float: none; width: 100%; }
  .system-log-dates .el-date-range-picker__time-header { display: flex; flex-wrap: wrap; }
  .system-log-dates .el-date-range-picker__time-header > .el-date-range-picker__editors-wrap { width: 100%; }
}
</style>
