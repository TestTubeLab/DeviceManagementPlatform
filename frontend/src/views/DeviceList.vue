<template>
  <div class="device-list">
    <div class="page-header">
      <h2 class="page-title">设备管理</h2>
      <el-button type="primary" :icon="Plus" @click="showAddDialog = true">
        添加设备
      </el-button>
    </div>

    <!-- 筛选和搜索 -->
    <el-card shadow="never" class="filter-card">
      <el-form :inline="true">
        <el-form-item label="状态筛选">
          <el-select v-model="filterStatus" placeholder="全部状态" clearable @change="filterDevices">
            <el-option label="在线" value="online" />
            <el-option label="离线" value="offline" />
            <el-option label="等待部署" value="waiting" />
            <el-option label="部署中" value="deploying" />
            <el-option label="更新中" value="updating" />
            <el-option label="异常" value="error" />
          </el-select>
        </el-form-item>
        <el-form-item label="搜索">
          <el-input
            v-model="searchText"
            placeholder="设备ID或IP地址"
            :prefix-icon="Search"
            clearable
            @input="filterDevices"
          />
        </el-form-item>
        <el-form-item>
          <el-button :icon="Refresh" @click="refresh">刷新</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 设备网格 -->
    <el-row :gutter="20" class="device-grid" v-loading="deviceStore.loading">
      <el-col :span="6" v-for="device in filteredDevices" :key="device.id">
        <DeviceCard :device="device" @click="goToDetail(device.device_id)" />
      </el-col>
    </el-row>

    <!-- 空状态 -->
    <el-empty
      v-if="!deviceStore.loading && filteredDevices.length === 0"
      description="暂无设备"
    />

    <!-- 添加设备对话框 -->
    <el-dialog v-model="showAddDialog" title="添加设备" width="500px">
      <el-form :model="newDevice" label-width="100px">
        <el-form-item label="设备ID" required>
          <el-input v-model="newDevice.device_id" placeholder="dev_xxx" />
        </el-form-item>
        <el-form-item label="设备名称">
          <el-input v-model="newDevice.name" placeholder="可选" />
        </el-form-item>
        <el-form-item label="安装位置">
          <el-input v-model="newDevice.location" placeholder="可选" />
        </el-form-item>
        <el-form-item label="MAC地址">
          <el-input v-model="newDevice.mac_address" placeholder="00:11:22:33:44:55" />
        </el-form-item>
        <el-form-item label="IP地址">
          <el-input v-model="newDevice.ip_address" placeholder="192.168.1.100" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="addDevice">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Search, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useDeviceStore } from '@/stores/device'
import { createDevice } from '@/api/device'
import DeviceCard from '@/components/DeviceCard.vue'
import type { Device } from '@/types'

const router = useRouter()
const deviceStore = useDeviceStore()

const filterStatus = ref('')
const searchText = ref('')
const showAddDialog = ref(false)
const newDevice = ref({
  device_id: '',
  name: '',
  location: '',
  mac_address: '',
  ip_address: '',
  status: 'waiting' as const,
})

const filteredDevices = computed(() => {
  let devices = deviceStore.devices

  if (filterStatus.value) {
    devices = devices.filter(d => d.status === filterStatus.value)
  }

  if (searchText.value) {
    const search = searchText.value.toLowerCase()
    devices = devices.filter(d =>
      d.device_id.toLowerCase().includes(search) ||
      d.ip_address.toLowerCase().includes(search) ||
      (d.name && d.name.toLowerCase().includes(search))
    )
  }

  return devices
})

const filterDevices = () => {
  // 触发计算属性重新计算
}

const refresh = () => {
  deviceStore.loadDevices()
  ElMessage.success('刷新成功')
}

const goToDetail = (deviceId: string) => {
  router.push(`/devices/${deviceId}`)
}

const addDevice = async () => {
  if (!newDevice.value.device_id) {
    ElMessage.warning('请输入设备ID')
    return
  }

  try {
    await createDevice(newDevice.value as Partial<Device>)
    ElMessage.success('设备添加成功')
    showAddDialog.value = false
    newDevice.value = {
      device_id: '',
      name: '',
      location: '',
      mac_address: '',
      ip_address: '',
      status: 'waiting',
    }
    await deviceStore.loadDevices()
  } catch (error) {
    ElMessage.error('设备添加失败')
  }
}

onMounted(() => {
  deviceStore.loadDevices()
})
</script>

<style scoped>
.device-list {
  padding: 0;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  color: #303133;
}

.filter-card {
  margin-bottom: 20px;
}

.device-grid {
  margin-top: 20px;
}

.device-grid .el-col {
  margin-bottom: 20px;
}
</style>



