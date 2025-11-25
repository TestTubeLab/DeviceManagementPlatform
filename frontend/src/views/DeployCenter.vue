<template>
  <div class="deploy-center">
    <h2 class="page-title">部署中心</h2>

    <el-card shadow="hover">
      <template #header>
        <span class="card-title">批量部署</span>
      </template>

      <el-steps :active="currentStep" align-center finish-status="success">
        <el-step title="选择镜像" />
        <el-step title="选择设备" />
        <el-step title="容器配置" />
        <el-step title="确认部署" />
      </el-steps>

      <!-- 步骤1：选择镜像 -->
      <div v-if="currentStep === 0" class="step-content">
        <div style="width: 100%; max-width: 800px">
          <el-alert
            title="从镜像仓库选择要部署的Docker镜像"
            type="info"
            :closable="false"
            style="margin-bottom: 20px"
          />
          
          <el-form label-width="100px">
            <el-form-item label="选择镜像" required>
              <el-select
                v-model="selectedImageId"
                placeholder="请选择镜像"
                style="width: 100%"
                :loading="loadingImages"
                @change="handleImageChange"
              >
                <el-option
                  v-for="image in images"
                  :key="image.id"
                  :label="`${image.name}:${image.tag} (${image.size_mb} MB)`"
                  :value="image.id"
                >
                  <div style="display: flex; justify-content: space-between; align-items: center">
                    <span>{{ image.name }}:{{ image.tag }}</span>
                    <el-tag size="small" type="info">{{ image.size_mb }} MB</el-tag>
                  </div>
                </el-option>
              </el-select>
            </el-form-item>

            <!-- 显示选中镜像的详细信息 -->
            <el-form-item v-if="selectedImage" label="镜像信息">
              <el-descriptions :column="2" border size="small">
                <el-descriptions-item label="镜像名称">
                  {{ selectedImage.name }}
                </el-descriptions-item>
                <el-descriptions-item label="版本标签">
                  <el-tag type="success">{{ selectedImage.tag }}</el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="完整名称" :span="2">
                  <el-text type="info">{{ selectedImage.full_name }}</el-text>
                </el-descriptions-item>
                <el-descriptions-item label="文件大小">
                  {{ selectedImage.size_mb }} MB
                </el-descriptions-item>
                <el-descriptions-item label="上传时间">
                  {{ formatDate(selectedImage.uploaded_at) }}
                </el-descriptions-item>
                <el-descriptions-item label="上传者">
                  {{ selectedImage.created_by }}
                </el-descriptions-item>
                <el-descriptions-item label="描述" :span="2">
                  {{ selectedImage.description || '无' }}
                </el-descriptions-item>
              </el-descriptions>
            </el-form-item>
          </el-form>

          <!-- 如果没有镜像，提示上传 -->
          <el-empty v-if="!loadingImages && images.length === 0" description="暂无可用镜像">
            <el-button type="primary" @click="$router.push('/images')">
              前往镜像仓库上传
            </el-button>
          </el-empty>
        </div>
      </div>

      <!-- 步骤2：选择设备 -->
      <div v-if="currentStep === 1" class="step-content">
        <el-transfer
          v-model="selectedDeviceIds"
          :data="deviceOptions"
          :titles="['可用设备', '已选设备']"
          :button-texts="['移除', '添加']"
          filterable
          filter-placeholder="搜索设备"
        />
      </div>

      <!-- 步骤3：容器配置 -->
      <div v-if="currentStep === 2" class="step-content">
        <div style="width: 100%; max-width: 800px">
          <el-form :model="deployConfig" label-width="150px">
            <el-form-item label="容器名称" required>
              <el-input v-model="deployConfig.container_name" placeholder="middleware" />
              <div style="margin-top: 5px; color: #909399; font-size: 12px">
                容器在设备上的名称，默认: middleware
              </div>
            </el-form-item>

            <el-form-item label="端口映射">
              <el-input v-model="deployConfig.ports" placeholder="8000:8000" />
              <div style="margin-top: 5px; color: #909399; font-size: 12px">
                格式: 宿主机端口:容器端口，例如 8000:8000
              </div>
            </el-form-item>

            <el-form-item label="环境变量">
              <el-input
                v-model="deployConfig.environment"
                type="textarea"
                :rows="4"
                placeholder="每行一个，格式: KEY=VALUE&#10;例如:&#10;ENV=production&#10;DEBUG=false"
              />
            </el-form-item>

            <el-form-item label="数据卷挂载">
              <el-input
                v-model="deployConfig.volumes"
                type="textarea"
                :rows="3"
                placeholder="每行一个，格式: 宿主机路径:容器路径&#10;例如:&#10;/data/config:/app/config&#10;/data/logs:/app/logs"
              />
            </el-form-item>

            <el-form-item label="重启策略">
              <el-select v-model="deployConfig.restart_policy" style="width: 100%">
                <el-option label="总是重启 (always)" value="always" />
                <el-option label="失败时重启 (on-failure)" value="on-failure" />
                <el-option label="除非停止 (unless-stopped)" value="unless-stopped" />
                <el-option label="不重启 (no)" value="no" />
              </el-select>
            </el-form-item>
          </el-form>
        </div>
      </div>

      <!-- 步骤4：确认部署 -->
      <div v-if="currentStep === 3" class="step-content">
        <div style="width: 100%; max-width: 1000px">
          <el-alert
            title="请确认部署信息"
            type="warning"
            :closable="false"
            style="margin-bottom: 20px"
          >
            <template #default>
              <div>镜像: <strong>{{ selectedImage?.name }}:{{ selectedImage?.tag }}</strong></div>
              <div>目标设备: <strong>{{ selectedDevices.length }}</strong> 台</div>
              <div>容器名称: <strong>{{ deployConfig.container_name }}</strong></div>
            </template>
          </el-alert>

          <!-- 部署详情 -->
          <el-descriptions title="部署详情" :column="2" border style="margin-bottom: 20px">
            <el-descriptions-item label="镜像名称">
              {{ selectedImage?.name }}:{{ selectedImage?.tag }}
            </el-descriptions-item>
            <el-descriptions-item label="镜像大小">
              {{ selectedImage?.size_mb }} MB
            </el-descriptions-item>
            <el-descriptions-item label="容器名称">
              {{ deployConfig.container_name }}
            </el-descriptions-item>
            <el-descriptions-item label="端口映射">
              {{ deployConfig.ports || '无' }}
            </el-descriptions-item>
            <el-descriptions-item label="重启策略">
              {{ deployConfig.restart_policy }}
            </el-descriptions-item>
            <el-descriptions-item label="环境变量">
              {{ deployConfig.environment ? '已配置' : '无' }}
            </el-descriptions-item>
          </el-descriptions>

          <!-- 目标设备列表 -->
          <h4 style="margin: 20px 0 10px">目标设备列表</h4>
          <el-table :data="selectedDevices" border>
            <el-table-column prop="device_id" label="设备ID" width="180" />
            <el-table-column prop="name" label="设备名称" />
            <el-table-column prop="ip_address" label="IP地址" width="140" />
            <el-table-column label="当前状态" width="100">
              <template #default="{ row }">
                <StatusBadge :status="row.status" />
              </template>
            </el-table-column>
            <el-table-column prop="current_version" label="当前版本" width="120" />
          </el-table>
        </div>
      </div>

      <div class="step-actions">
        <el-button v-if="currentStep > 0" @click="currentStep--">上一步</el-button>
        <el-button v-if="currentStep < 3" type="primary" @click="nextStep">下一步</el-button>
        <el-button v-if="currentStep === 3" type="primary" @click="startDeploy" :loading="deploying">
          开始部署
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useDeviceStore } from '@/stores/device'
import { getImages } from '@/api/image'
import { createDeploymentTask } from '@/api/task'
import StatusBadge from '@/components/StatusBadge.vue'
import type { DockerImage } from '@/types'

const deviceStore = useDeviceStore()

const currentStep = ref(0)
const selectedImageId = ref<number | null>(null)
const selectedImage = ref<DockerImage | null>(null)
const images = ref<DockerImage[]>([])
const loadingImages = ref(false)
const selectedDeviceIds = ref<number[]>([])
const deploying = ref(false)

const deployConfig = ref({
  container_name: 'middleware',
  ports: '8000:8000',
  environment: '',
  volumes: '',
  restart_policy: 'always'
})

// 加载镜像列表
const loadImages = async () => {
  loadingImages.value = true
  try {
    const response = await getImages()
    images.value = response.results || []
  } catch (error: any) {
    ElMessage.error('加载镜像列表失败: ' + (error.message || '未知错误'))
  } finally {
    loadingImages.value = false
  }
}

// 镜像选择变化
const handleImageChange = (imageId: number) => {
  selectedImage.value = images.value.find(img => img.id === imageId) || null
}

// 格式化日期
const formatDate = (dateString: string) => {
  const date = new Date(dateString)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const deviceOptions = computed(() => {
  return deviceStore.devices.map(device => ({
    key: device.id,
    label: `${device.name || device.device_id} (${device.ip_address})`,
    disabled: device.status === 'deploying' || device.status === 'updating',
  }))
})

const selectedDevices = computed(() => {
  return deviceStore.devices.filter(d => selectedDeviceIds.value.includes(d.id))
})

const nextStep = () => {
  // 步骤1：选择镜像
  if (currentStep.value === 0) {
    if (!selectedImageId.value) {
      ElMessage.warning('请选择要部署的镜像')
      return
    }
  }
  
  // 步骤2：选择设备
  if (currentStep.value === 1) {
    if (selectedDeviceIds.value.length === 0) {
      ElMessage.warning('请至少选择一台设备')
      return
    }
  }

  // 步骤3：容器配置
  if (currentStep.value === 2) {
    if (!deployConfig.value.container_name) {
      ElMessage.warning('请输入容器名称')
      return
    }
  }

  currentStep.value++
}

const startDeploy = async () => {
  if (!selectedImage.value) {
    ElMessage.error('未选择镜像')
    return
  }

  deploying.value = true
  
  try {
    // 解析端口映射
    const ports: Record<string, number> = {}
    if (deployConfig.value.ports) {
      const [hostPort, containerPort] = deployConfig.value.ports.split(':')
      if (hostPort && containerPort) {
        ports[`${containerPort}/tcp`] = parseInt(hostPort)
      }
    }

    // 解析环境变量
    const environment: Record<string, string> = {}
    if (deployConfig.value.environment) {
      const lines = deployConfig.value.environment.split('\n')
      lines.forEach((line) => {
        const [key, ...valueParts] = line.split('=')
        if (key && valueParts.length > 0) {
          environment[key.trim()] = valueParts.join('=').trim()
        }
      })
    }

    // 解析数据卷
    const volumes: Record<string, any> = {}
    if (deployConfig.value.volumes) {
      const lines = deployConfig.value.volumes.split('\n')
      lines.forEach((line) => {
        const [hostPath, containerPath] = line.split(':')
        if (hostPath && containerPath) {
          volumes[hostPath.trim()] = {
            bind: containerPath.trim(),
            mode: 'rw'
          }
        }
      })
    }

    // 构建容器配置
    const containerConfig: Record<string, any> = {}
    if (Object.keys(ports).length > 0) {
      containerConfig.ports = ports
    }
    if (Object.keys(environment).length > 0) {
      containerConfig.environment = environment
    }
    if (Object.keys(volumes).length > 0) {
      containerConfig.volumes = volumes
    }
    if (deployConfig.value.restart_policy) {
      containerConfig.restart_policy = { Name: deployConfig.value.restart_policy }
    }

    // 创建部署任务
    const tasks = selectedDevices.value.map(device =>
      createDeploymentTask({
        device: device.id,
        image: selectedImage.value!.id,
        target_version: selectedImage.value!.tag,
        container_name: deployConfig.value.container_name,
        container_config: containerConfig,
        registry_url: selectedImage.value!.full_name.split('/')[0]
      })
    )

    await Promise.all(tasks)
    
    ElMessage.success(`成功创建 ${tasks.length} 个部署任务`)
    
    // 重置表单
    currentStep.value = 0
    selectedImageId.value = null
    selectedImage.value = null
    selectedDeviceIds.value = []
    deployConfig.value = {
      container_name: 'middleware',
      ports: '8000:8000',
      environment: '',
      volumes: '',
      restart_policy: 'always'
    }
  } catch (error: any) {
    ElMessage.error('部署任务创建失败: ' + (error.response?.data?.error || error.message || '未知错误'))
  } finally {
    deploying.value = false
  }
}

onMounted(() => {
  deviceStore.loadDevices()
  loadImages()
})
</script>

<style scoped>
.deploy-center {
  padding: 0;
}

.page-title {
  margin: 0 0 20px 0;
  font-size: 24px;
  font-weight: 600;
  color: #303133;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.step-content {
  margin: 40px 0;
  min-height: 300px;
  display: flex;
  justify-content: center;
  align-items: center;
}

.step-actions {
  display: flex;
  justify-content: center;
  gap: 12px;
  margin-top: 20px;
}

:deep(.el-transfer) {
  width: 100%;
}

:deep(.el-transfer-panel) {
  width: 40%;
}
</style>

