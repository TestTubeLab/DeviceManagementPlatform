<template>
  <div class="image-registry">
    <el-card>
      <template #header>
        <div class="card-header">
          <span class="title">
            <el-icon><Box /></el-icon>
            Docker镜像仓库
          </span>
          <el-button type="primary" :icon="Upload" @click="showUploadDialog = true">
            上传镜像
          </el-button>
        </div>
      </template>

      <!-- 搜索栏 -->
      <div class="search-bar">
        <el-input
          v-model="searchText"
          placeholder="搜索镜像名称或标签"
          :prefix-icon="Search"
          clearable
          style="width: 300px"
        />
        <el-button :icon="Refresh" @click="loadImages">刷新</el-button>
      </div>

      <!-- 镜像列表表格 -->
      <el-table
        :data="filteredImages"
        v-loading="loading"
        stripe
        style="width: 100%; margin-top: 20px"
      >
        <el-table-column prop="name" label="镜像名称" min-width="150">
          <template #default="{ row }">
            <el-text tag="b">{{ row.name }}</el-text>
          </template>
        </el-table-column>

        <el-table-column prop="tag" label="版本标签" width="120">
          <template #default="{ row }">
            <el-tag type="success" size="small">{{ row.tag }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="full_name" label="完整名称" min-width="250" show-overflow-tooltip />

        <el-table-column prop="size_mb" label="大小" width="100" sortable>
          <template #default="{ row }">
            {{ row.size_mb }} MB
          </template>
        </el-table-column>

        <el-table-column prop="created_by" label="上传者" width="100" />

        <el-table-column prop="uploaded_at" label="上传时间" width="180" sortable>
          <template #default="{ row }">
            {{ formatDate(row.uploaded_at) }}
          </template>
        </el-table-column>

        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button
              type="primary"
              size="small"
              :icon="Promotion"
              @click="openDeployDialog(row)"
            >
              部署
            </el-button>
            <el-button
              type="danger"
              size="small"
              :icon="Delete"
              @click="confirmDelete(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 空状态 -->
      <el-empty v-if="!loading && images.length === 0" description="暂无镜像，请上传">
        <el-button type="primary" :icon="Upload" @click="showUploadDialog = true">
          上传镜像
        </el-button>
      </el-empty>
    </el-card>

    <!-- 上传镜像对话框 -->
    <el-dialog
      v-model="showUploadDialog"
      title="上传Docker镜像"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form :model="uploadForm" label-width="100px">
        <el-form-item label="镜像文件">
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :limit="1"
            :on-change="handleFileChange"
            :on-exceed="handleExceed"
            accept=".tar"
            drag
          >
            <el-icon class="el-icon--upload"><upload-filled /></el-icon>
            <div class="el-upload__text">
              拖拽文件到此处 或 <em>点击选择</em>
            </div>
            <template #tip>
              <div class="el-upload__tip">
                只支持 .tar 格式的Docker镜像文件，最大5GB
              </div>
            </template>
          </el-upload>
        </el-form-item>

        <el-form-item label="镜像名称">
          <el-input
            v-model="uploadForm.name"
            placeholder="留空则自动从镜像中提取"
          />
        </el-form-item>

        <el-form-item label="版本标签">
          <el-input
            v-model="uploadForm.tag"
            placeholder="例如: v1.0.2-beta 或 latest"
          />
        </el-form-item>

        <el-form-item label="描述">
          <el-input
            v-model="uploadForm.description"
            type="textarea"
            :rows="3"
            placeholder="可选：镜像描述信息"
          />
        </el-form-item>

        <!-- 上传进度 -->
        <el-form-item v-if="uploading">
          <el-progress
            :percentage="uploadProgress"
            :status="uploadProgress === 100 ? 'success' : undefined"
          />
          <div style="margin-top: 10px; color: #909399; font-size: 14px">
            {{ uploadStatusText }}
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showUploadDialog = false" :disabled="uploading">
          取消
        </el-button>
        <el-button
          type="primary"
          @click="handleUpload"
          :loading="uploading"
          :disabled="!uploadForm.file"
        >
          {{ uploading ? '上传中...' : '开始上传' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 部署到设备对话框 -->
    <el-dialog
      v-model="showDeployDialog"
      title="部署镜像到设备"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form :model="deployForm" label-width="100px">
        <el-form-item label="镜像信息">
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="镜像">
              {{ currentImage?.name }}:{{ currentImage?.tag }}
            </el-descriptions-item>
            <el-descriptions-item label="大小">
              {{ currentImage?.size_mb }} MB
            </el-descriptions-item>
          </el-descriptions>
        </el-form-item>

        <el-form-item label="目标设备" required>
          <el-select
            v-model="deployForm.deviceIds"
            multiple
            placeholder="选择要部署的设备"
            style="width: 100%"
            :loading="loadingDevices"
          >
            <el-option
              v-for="device in devices"
              :key="device.device_id"
              :label="`${device.name || device.device_id} (${device.ip_address})`"
              :value="device.device_id"
            >
              <span>{{ device.name || device.device_id }}</span>
              <el-tag
                :type="device.status === 'online' ? 'success' : 'info'"
                size="small"
                style="margin-left: 10px"
              >
                {{ device.status }}
              </el-tag>
            </el-option>
          </el-select>
        </el-form-item>

        <el-form-item label="容器名称">
          <el-input
            v-model="deployForm.containerName"
            placeholder="默认: middleware"
          />
        </el-form-item>

        <el-form-item label="端口映射">
          <el-input
            v-model="deployForm.ports"
            placeholder="例如: 8000:8000 (宿主机:容器)"
          />
          <div style="margin-top: 5px; color: #909399; font-size: 12px">
            格式: 宿主机端口:容器端口
          </div>
        </el-form-item>

        <el-form-item label="环境变量">
          <el-input
            v-model="deployForm.environment"
            type="textarea"
            :rows="3"
            placeholder="每行一个，格式: KEY=VALUE"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showDeployDialog = false">取消</el-button>
        <el-button
          type="primary"
          @click="handleDeploy"
          :loading="deploying"
          :disabled="deployForm.deviceIds.length === 0"
        >
          开始部署
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadInstance, UploadRawFile, UploadFile } from 'element-plus'
import {
  Upload,
  Delete,
  Promotion,
  Search,
  Refresh,
  Box,
  UploadFilled
} from '@element-plus/icons-vue'
import { getImages, uploadImage, deleteImage, pushImageToDevice } from '@/api/image'
import { getDevices } from '@/api/device'
import type { DockerImage, Device } from '@/types'

// 镜像列表
const images = ref<DockerImage[]>([])
const loading = ref(false)
const searchText = ref('')

// 上传相关
const showUploadDialog = ref(false)
const uploadRef = ref<UploadInstance>()
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadStatusText = ref('')
const uploadForm = ref({
  file: null as File | null,
  name: '',
  tag: '',
  description: ''
})

// 部署相关
const showDeployDialog = ref(false)
const currentImage = ref<DockerImage | null>(null)
const devices = ref<Device[]>([])
const loadingDevices = ref(false)
const deploying = ref(false)
const deployForm = ref({
  deviceIds: [] as string[],
  containerName: 'middleware',
  ports: '8000:8000',
  environment: ''
})

// 计算属性：过滤后的镜像列表
const filteredImages = computed(() => {
  if (!searchText.value) {
    return images.value
  }
  const keyword = searchText.value.toLowerCase()
  return images.value.filter(
    (img) =>
      img.name.toLowerCase().includes(keyword) ||
      img.tag.toLowerCase().includes(keyword)
  )
})

// 加载镜像列表
const loadImages = async () => {
  loading.value = true
  try {
    const response = await getImages()
    images.value = response.results || []
  } catch (error: any) {
    ElMessage.error('加载镜像列表失败: ' + (error.message || '未知错误'))
  } finally {
    loading.value = false
  }
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

// 文件选择变化
const handleFileChange = (file: UploadFile) => {
  if (file.raw) {
    uploadForm.value.file = file.raw
  }
}

// 文件数量超出限制
const handleExceed = () => {
  ElMessage.warning('一次只能上传一个镜像文件')
}

// 上传镜像
const handleUpload = async () => {
  if (!uploadForm.value.file) {
    ElMessage.warning('请选择镜像文件')
    return
  }

  uploading.value = true
  uploadProgress.value = 0
  uploadStatusText.value = '正在上传文件...'

  try {
    const formData = new FormData()
    formData.append('file', uploadForm.value.file)
    if (uploadForm.value.name) {
      formData.append('name', uploadForm.value.name)
    }
    if (uploadForm.value.tag) {
      formData.append('tag', uploadForm.value.tag)
    }
    if (uploadForm.value.description) {
      formData.append('description', uploadForm.value.description)
    }

    await uploadImage(formData, (percent) => {
      uploadProgress.value = percent
      if (percent < 100) {
        uploadStatusText.value = `正在上传文件... ${percent}%`
      } else {
        uploadStatusText.value = '文件上传完成，正在处理镜像...'
      }
    })

    ElMessage.success('镜像上传成功！')
    showUploadDialog.value = false
    
    // 重置表单
    uploadForm.value = {
      file: null,
      name: '',
      tag: '',
      description: ''
    }
    uploadRef.value?.clearFiles()

    // 刷新列表
    loadImages()
  } catch (error: any) {
    ElMessage.error('上传失败: ' + (error.response?.data?.error || error.message || '未知错误'))
  } finally {
    uploading.value = false
    uploadProgress.value = 0
    uploadStatusText.value = ''
  }
}

// 打开部署对话框
const openDeployDialog = async (image: DockerImage) => {
  currentImage.value = image
  showDeployDialog.value = true
  
  // 加载设备列表
  loadingDevices.value = true
  try {
    const response = await getDevices()
    devices.value = response.results || []
  } catch (error: any) {
    ElMessage.error('加载设备列表失败: ' + (error.message || '未知错误'))
  } finally {
    loadingDevices.value = false
  }
}

// 部署镜像
const handleDeploy = async () => {
  if (!currentImage.value) return
  if (deployForm.value.deviceIds.length === 0) {
    ElMessage.warning('请选择目标设备')
    return
  }

  deploying.value = true

  try {
    // 解析端口映射
    const ports: Record<string, number> = {}
    if (deployForm.value.ports) {
      const [hostPort, containerPort] = deployForm.value.ports.split(':')
      if (hostPort && containerPort) {
        ports[`${containerPort}/tcp`] = parseInt(hostPort)
      }
    }

    // 解析环境变量
    const environment: Record<string, string> = {}
    if (deployForm.value.environment) {
      const lines = deployForm.value.environment.split('\n')
      lines.forEach((line) => {
        const [key, ...valueParts] = line.split('=')
        if (key && valueParts.length > 0) {
          environment[key.trim()] = valueParts.join('=').trim()
        }
      })
    }

    const containerConfig: Record<string, any> = {}
    if (Object.keys(ports).length > 0) {
      containerConfig.ports = ports
    }
    if (Object.keys(environment).length > 0) {
      containerConfig.environment = environment
    }

    const response = await pushImageToDevice(currentImage.value.id, {
      device_ids: deployForm.value.deviceIds,
      container_name: deployForm.value.containerName || 'middleware',
      container_config: containerConfig
    })

    ElMessage.success(
      `成功创建 ${response.success} 个部署任务，失败 ${response.failed} 个`
    )
    
    showDeployDialog.value = false
    
    // 重置表单
    deployForm.value = {
      deviceIds: [],
      containerName: 'middleware',
      ports: '8000:8000',
      environment: ''
    }
  } catch (error: any) {
    ElMessage.error('部署失败: ' + (error.response?.data?.error || error.message || '未知错误'))
  } finally {
    deploying.value = false
  }
}

// 确认删除
const confirmDelete = (image: DockerImage) => {
  ElMessageBox.confirm(
    `确定要删除镜像 ${image.name}:${image.tag} 吗？此操作不可恢复。`,
    '删除确认',
    {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning'
    }
  )
    .then(() => {
      handleDelete(image.id)
    })
    .catch(() => {
      // 用户取消
    })
}

// 删除镜像
const handleDelete = async (id: number) => {
  try {
    await deleteImage(id)
    ElMessage.success('镜像已删除')
    loadImages()
  } catch (error: any) {
    ElMessage.error('删除失败: ' + (error.message || '未知错误'))
  }
}

// 页面加载时获取数据
onMounted(() => {
  loadImages()
})
</script>

<style scoped>
.image-registry {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.title {
  font-size: 18px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.search-bar {
  display: flex;
  gap: 10px;
  align-items: center;
}

.el-icon--upload {
  font-size: 67px;
  color: #c0c4cc;
  margin: 40px 0 16px;
}
</style>



