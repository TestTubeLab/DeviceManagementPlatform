<template>
  <div class="project-manage">
    <div class="page-header">
      <h2 class="page-title">项目管理</h2>
      <el-button type="primary" :icon="Plus" @click="showCreateDialog = true">
        创建项目
      </el-button>
    </div>

    <!-- 项目列表 -->
    <el-card shadow="never">
      <el-table :data="projects" v-loading="loading" style="width: 100%">
        <el-table-column prop="name" label="项目名称" width="200" />
        <el-table-column prop="version" label="版本" width="100" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.status === 'active'" type="success">活跃</el-tag>
            <el-tag v-else-if="row.status === 'draft'" type="info">草稿</el-tag>
            <el-tag v-else type="warning">归档</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Docker镜像" width="200">
          <template #default="{ row }">
            <span v-if="row.local_image_name">
              <el-tag size="small" type="success">本地</el-tag>
              {{ row.local_image_name }}
            </span>
            <span v-else-if="row.docker_image_info">
              <el-tag size="small">平台</el-tag>
              {{ row.docker_image_info.name }}:{{ row.docker_image_info.tag }}
            </span>
            <span v-else class="text-gray">未设置</span>
          </template>
        </el-table-column>
        <el-table-column prop="git_repo" label="代码仓库" min-width="250" show-overflow-tooltip />
        <el-table-column label="已部署设备" width="120" align="center">
          <template #default="{ row }">
            <el-tag>{{ row.deployed_devices_count || 0 }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="viewProject(row)">详情</el-button>
            <el-button size="small" type="primary" @click="showDeployDialog(row)">部署</el-button>
            <el-button size="small" @click="editProject(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 创建/编辑项目对话框 -->
    <el-dialog
      v-model="showCreateDialog"
      :title="editingProject ? '编辑项目' : '创建项目'"
      width="800px"
    >
      <el-form :model="projectForm" label-width="120px">
        <el-form-item label="项目名称" required>
          <el-input v-model="projectForm.name" placeholder="如：XX医院CT检测" />
        </el-form-item>
        
        <el-form-item label="版本号" required>
          <el-input v-model="projectForm.version" placeholder="如：v1.0.0" />
        </el-form-item>
        
        <el-form-item label="项目描述">
          <el-input
            v-model="projectForm.description"
            type="textarea"
            :rows="3"
            placeholder="简要描述项目用途"
          />
        </el-form-item>
        
        <el-form-item label="状态">
          <el-radio-group v-model="projectForm.status">
            <el-radio label="draft">草稿</el-radio>
            <el-radio label="active">活跃</el-radio>
            <el-radio label="archived">归档</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-divider content-position="left">Docker镜像配置</el-divider>
        
        <el-alert type="info" :closable="false" style="margin-bottom: 16px">
          <template #title>
            <strong>推荐方式</strong>：使用设备预装镜像（如 newserver:latest），避免传输大文件
          </template>
        </el-alert>
        
        <el-form-item label="本地镜像名">
          <el-input 
            v-model="projectForm.local_image_name" 
            placeholder="设备预装镜像名称，如：newserver:latest"
          />
          <div class="form-tip">设备上已有的镜像，直接使用不拉取（推荐）</div>
        </el-form-item>
        
        <el-form-item label="或选择平台镜像">
          <el-select v-model="projectForm.docker_image" placeholder="从平台上传的镜像" clearable filterable>
            <el-option
              v-for="image in dockerImages"
              :key="image.id"
              :label="`${image.name}:${image.tag}`"
              :value="image.id"
            />
          </el-select>
          <div class="form-tip">平台托管的镜像（需要设备拉取，较慢）</div>
        </el-form-item>
        
        <el-form-item label="容器名称">
          <el-input v-model="projectForm.container_name" placeholder="如：middleware" />
        </el-form-item>
        
        <el-divider content-position="left">容器运行参数</el-divider>
        
        <el-form-item label="GPU支持">
          <el-switch v-model="projectForm.container_config.runtime_nvidia" active-text="启用NVIDIA Runtime" />
          <div class="form-tip">如需使用GPU，请开启此选项（需设备已安装nvidia-container-toolkit）</div>
        </el-form-item>
        
        <el-form-item label="网络模式">
          <el-radio-group v-model="projectForm.container_config.network_mode">
            <el-radio label="host">主机网络 (host)</el-radio>
            <el-radio label="">桥接网络 (bridge)</el-radio>
          </el-radio-group>
          <div class="form-tip">主机网络可直接使用宿主机端口</div>
        </el-form-item>
        
        <el-form-item label="特权模式">
          <el-switch v-model="projectForm.container_config.privileged" active-text="启用特权模式" />
          <div class="form-tip">访问摄像头、串口等硬件设备需要特权模式</div>
        </el-form-item>

        <el-divider content-position="left">代码配置（二选一）</el-divider>
        
        <el-alert type="info" :closable="false" style="margin-bottom: 16px">
          <template #title>
            <strong>推荐方式</strong>：使用代码包，避免Git网络问题
          </template>
        </el-alert>
        
        <el-form-item label="代码包">
          <el-select v-model="projectForm.code_package" placeholder="选择已上传的代码包" clearable filterable style="width: 70%">
            <el-option
              v-for="pkg in codePackages"
              :key="pkg.id"
              :label="`${pkg.name} (${pkg.version}) - ${pkg.size_mb}MB`"
              :value="pkg.id"
            />
          </el-select>
          <el-button style="margin-left: 8px" @click="showCodeUploadDialog = true">上传新包</el-button>
        </el-form-item>
        
        <el-form-item label="代码挂载路径">
          <el-input v-model="projectForm.code_mount_path" placeholder="宿主机上的代码目录，如：/opt/project-code" />
          <div class="form-tip">代码包会解压到此目录，容器启动时挂载</div>
        </el-form-item>

        <el-divider content-position="left">或使用Git（备用）</el-divider>
        
        <el-form-item label="Git仓库地址">
          <el-input
            v-model="projectForm.git_repo"
            placeholder="如：https://github.com/your/project.git（国内可能较慢）"
          />
        </el-form-item>
        
        <el-form-item label="分支">
          <el-input v-model="projectForm.git_branch" placeholder="如：main" />
        </el-form-item>
        
        <el-divider content-position="left">容器运行配置</el-divider>
        
        <el-form-item label="工作目录">
          <el-input v-model="projectForm.work_dir" placeholder="容器内工作目录，如：/work" />
        </el-form-item>
        
        <el-form-item label="启动命令">
          <el-input
            v-model="projectForm.start_command"
            type="textarea"
            :rows="2"
            placeholder="如：/start.sh 或 python main.py"
          />
        </el-form-item>
      </el-form>
      
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSaveProject">保存</el-button>
      </template>
    </el-dialog>

    <!-- 部署到设备对话框 -->
    <el-dialog v-model="showDeployDialogVisible" title="部署项目到设备" width="600px">
      <div v-if="deployingProject">
        <div class="deploy-info">
          <p><strong>项目：</strong>{{ deployingProject.name }} ({{ deployingProject.version }})</p>
          <p><strong>镜像：</strong>
            <span v-if="deployingProject.local_image_name">
              <el-tag size="small" type="success">本地</el-tag>
              {{ deployingProject.local_image_name }}
            </span>
            <span v-else-if="deployingProject.docker_image_info">
              <el-tag size="small">平台</el-tag>
              {{ deployingProject.docker_image_info.full_name }}
            </span>
            <span v-else class="text-gray">未设置</span>
          </p>
          <p><strong>代码：</strong>
            <span v-if="deployingProject.code_package_info">
              {{ deployingProject.code_package_info.name }} ({{ deployingProject.code_package_info.version }})
            </span>
            <span v-else-if="deployingProject.git_repo">{{ deployingProject.git_repo }}</span>
            <span v-else class="text-gray">未设置</span>
          </p>
          <p><strong>启动命令：</strong>{{ deployingProject.start_command }}</p>
        </div>
        
        <el-divider />
        
        <el-form label-width="100px">
          <el-form-item label="选择设备">
            <el-select
              v-model="selectedDevices"
              multiple
              placeholder="选择要部署的设备"
              style="width: 100%"
            >
              <el-option
                v-for="device in devices"
                :key="device.device_id"
                :label="`${device.name || device.device_id} (${device.ip_address})`"
                :value="device.device_id"
              >
                <span>{{ device.name || device.device_id }}</span>
                <span style="float: right; color: #8492a6; font-size: 13px">
                  {{ device.status === 'online' ? '🟢 在线' : '🔴 离线' }}
                </span>
              </el-option>
            </el-select>
          </el-form-item>
        </el-form>
      </div>
      
      <template #footer>
        <el-button @click="showDeployDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          @click="handleDeploy"
          :disabled="selectedDevices.length === 0"
        >
          开始部署
        </el-button>
      </template>
    </el-dialog>

    <!-- 项目详情对话框 -->
    <el-dialog v-model="showDetailDialog" title="项目详情" width="900px">
      <div v-if="viewingProject">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="项目名称">{{ viewingProject.name }}</el-descriptions-item>
          <el-descriptions-item label="版本">{{ viewingProject.version }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag v-if="viewingProject.status === 'active'" type="success">活跃</el-tag>
            <el-tag v-else-if="viewingProject.status === 'draft'" type="info">草稿</el-tag>
            <el-tag v-else type="warning">归档</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="已部署设备">
            {{ viewingProject.deployed_devices_count || 0 }} 台
          </el-descriptions-item>
          <el-descriptions-item label="Docker镜像" :span="2">
            <span v-if="viewingProject.local_image_name">
              <el-tag size="small" type="success">本地预装</el-tag>
              {{ viewingProject.local_image_name }}
            </span>
            <span v-else-if="viewingProject.docker_image_info">
              <el-tag size="small">平台托管</el-tag>
              {{ viewingProject.docker_image_info.full_name }}
            </span>
            <span v-else class="text-gray">未设置</span>
          </el-descriptions-item>
          <el-descriptions-item label="代码包" :span="2">
            <span v-if="viewingProject.code_package_info">
              {{ viewingProject.code_package_info.name }} ({{ viewingProject.code_package_info.version }})
              - {{ viewingProject.code_package_info.size_mb }}MB
            </span>
            <span v-else class="text-gray">未设置</span>
          </el-descriptions-item>
          <el-descriptions-item label="代码挂载路径">
            {{ viewingProject.code_mount_path || '/opt/project-code' }}
          </el-descriptions-item>
          <el-descriptions-item label="容器名称">
            {{ viewingProject.container_name }}
          </el-descriptions-item>
          <el-descriptions-item label="Git仓库(备用)" :span="2">
            {{ viewingProject.git_repo || '未设置' }}
          </el-descriptions-item>
          <el-descriptions-item label="分支">{{ viewingProject.git_branch }}</el-descriptions-item>
          <el-descriptions-item label="工作目录">{{ viewingProject.work_dir }}</el-descriptions-item>
          <el-descriptions-item label="启动命令" :span="2">
            <code>{{ viewingProject.start_command }}</code>
          </el-descriptions-item>
          <el-descriptions-item label="描述" :span="2">
            {{ viewingProject.description || '无' }}
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">
            {{ formatTime(viewingProject.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="更新时间">
            {{ formatTime(viewingProject.updated_at) }}
          </el-descriptions-item>
        </el-descriptions>

        <el-divider content-position="left">项目配置</el-divider>
        
        <el-table :data="viewingProject.configs" style="width: 100%">
          <el-table-column prop="key" label="配置键" width="200" />
          <el-table-column prop="value" label="配置值">
            <template #default="{ row }">
              <span v-if="row.is_secret">******</span>
              <span v-else>{{ row.value }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="描述" />
        </el-table>
        
        <el-button
          style="margin-top: 16px"
          @click="showConfigDialog(viewingProject)"
        >
          编辑配置
        </el-button>
      </div>
    </el-dialog>

    <!-- 代码包上传对话框 -->
    <el-dialog v-model="showCodeUploadDialog" title="上传代码包" width="500px">
      <el-form :model="codeUploadForm" label-width="100px">
        <el-form-item label="代码包文件" required>
          <el-upload
            :auto-upload="false"
            :show-file-list="true"
            :limit="1"
            accept=".zip,.tar.gz,.tgz"
            @change="handleCodeFileChange"
          >
            <el-button type="primary">选择文件</el-button>
            <template #tip>
              <div class="el-upload__tip">支持 .zip, .tar.gz, .tgz 格式</div>
            </template>
          </el-upload>
        </el-form-item>
        
        <el-form-item label="包名称" required>
          <el-input v-model="codeUploadForm.name" placeholder="如：MiddlewareServer" />
        </el-form-item>
        
        <el-form-item label="版本号" required>
          <el-input v-model="codeUploadForm.version" placeholder="如：v1.0.0" />
        </el-form-item>
        
        <el-form-item label="更新说明">
          <el-input
            v-model="codeUploadForm.description"
            type="textarea"
            :rows="2"
            placeholder="简要描述此版本的更新内容"
          />
        </el-form-item>
        
        <el-progress
          v-if="isUploading"
          :percentage="codeUploadProgress"
          :stroke-width="10"
          style="margin-top: 16px"
        />
      </el-form>
      
      <template #footer>
        <el-button @click="showCodeUploadDialog = false" :disabled="isUploading">取消</el-button>
        <el-button type="primary" @click="handleUploadCodePackage" :loading="isUploading">
          {{ isUploading ? '上传中...' : '上传' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 配置编辑对话框 -->
    <el-dialog v-model="showConfigDialogVisible" title="编辑项目配置" width="700px">
      <el-button
        type="primary"
        size="small"
        :icon="Plus"
        @click="addConfig"
        style="margin-bottom: 16px"
      >
        添加配置项
      </el-button>
      
      <el-table :data="configList" style="width: 100%">
        <el-table-column label="配置键" width="180">
          <template #default="{ row }">
            <el-input v-model="row.key" placeholder="KEY" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="配置值" width="180">
          <template #default="{ row }">
            <el-input v-model="row.value" placeholder="value" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="描述" width="180">
          <template #default="{ row }">
            <el-input v-model="row.description" placeholder="说明" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="敏感" width="80" align="center">
          <template #default="{ row }">
            <el-checkbox v-model="row.is_secret" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ $index }">
            <el-button
              type="danger"
              size="small"
              :icon="Delete"
              @click="configList.splice($index, 1)"
            />
          </template>
        </el-table-column>
      </el-table>
      
      <template #footer>
        <el-button @click="showConfigDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSaveConfig">保存配置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Plus, Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getProjects,
  createProject,
  updateProject,
  deleteProject,
  deployProjectToDevices,
  setProjectConfig,
  type Project,
  type ProjectConfig
} from '@/api/project'
import { getDevices } from '@/api/device'
import { getImages } from '@/api/image'
import { getCodePackages, uploadCodePackage, type CodePackage } from '@/api/codePackage'
import dayjs from 'dayjs'

const loading = ref(false)
const projects = ref<Project[]>([])
const devices = ref<any[]>([])
const dockerImages = ref<any[]>([])
const codePackages = ref<CodePackage[]>([])

const showCreateDialog = ref(false)
const showDeployDialogVisible = ref(false)
const showDetailDialog = ref(false)
const showConfigDialogVisible = ref(false)
const showCodeUploadDialog = ref(false)

// 代码包上传
const codeUploadForm = ref({
  name: '',
  version: 'v1.0.0',
  description: '',
  file: null as File | null
})
const codeUploadProgress = ref(0)
const isUploading = ref(false)

const editingProject = ref<Project | null>(null)
const deployingProject = ref<Project | null>(null)
const viewingProject = ref<Project | null>(null)
const configuringProject = ref<Project | null>(null)

const selectedDevices = ref<string[]>([])
const configList = ref<ProjectConfig[]>([])

const projectForm = ref({
  name: '',
  description: '',
  version: 'v1.0.0',
  status: 'active' as const,
  docker_image: null as number | null,
  local_image_name: '',  // 本地预装镜像名
  code_package: null as number | null,
  code_mount_path: '/opt/project-code',
  git_repo: '',
  git_branch: 'main',
  work_dir: '/work',
  start_command: '/work/MiddlewareServer/start.sh',  // 默认启动脚本路径
  container_name: 'middleware',  // 默认容器名
  container_config: {
    runtime_nvidia: true,      // 默认启用GPU
    network_mode: 'host',      // 默认使用host网络
    privileged: true,          // 默认启用特权模式
    restart_policy: 'unless-stopped'
  } as Record<string, any>
})

const formatTime = (time: string) => {
  return dayjs(time).format('YYYY-MM-DD HH:mm:ss')
}

const resetProjectForm = () => {
  projectForm.value = {
    name: '',
    description: '',
    version: 'v1.0.0',
    status: 'active',
    docker_image: null,
    local_image_name: '',
    code_package: null,
    code_mount_path: '/opt/project-code',
    git_repo: '',
    git_branch: 'main',
    work_dir: '/work',
    start_command: '/work/MiddlewareServer/start.sh',
    container_name: 'middleware',
    container_config: {
      runtime_nvidia: true,
      network_mode: 'host',
      privileged: true,
      restart_policy: 'unless-stopped'
    }
  }
}

// 转换前端表单到后端格式
const prepareProjectData = () => {
  const formData = { ...projectForm.value }
  const config = formData.container_config as Record<string, any>
  
  // 转换容器配置格式
  formData.container_config = {
    runtime: config.runtime_nvidia ? 'nvidia' : '',
    network_mode: config.network_mode || '',
    privileged: config.privileged || false,
    restart_policy: config.restart_policy || 'unless-stopped'
  }
  
  return formData
}

const loadProjects = async () => {
  loading.value = true
  try {
    const data = await getProjects()
    projects.value = data.results
  } catch (error) {
    ElMessage.error('加载项目列表失败')
  } finally {
    loading.value = false
  }
}

const loadDevices = async () => {
  try {
    const data = await getDevices()
    devices.value = data.results
  } catch (error) {
    console.error('加载设备列表失败:', error)
  }
}

const loadDockerImages = async () => {
  try {
    const data = await getImages()
    dockerImages.value = data.results
  } catch (error) {
    console.error('加载镜像列表失败:', error)
  }
}

const loadCodePackages = async () => {
  try {
    const data = await getCodePackages()
    codePackages.value = data.results
  } catch (error) {
    console.error('加载代码包列表失败:', error)
  }
}

const handleCodeFileChange = (file: any) => {
  codeUploadForm.value.file = file.raw
  // 自动从文件名提取包名
  if (!codeUploadForm.value.name) {
    const name = file.name.replace(/\.(zip|tar\.gz|tgz)$/, '')
    codeUploadForm.value.name = name
  }
}

const handleUploadCodePackage = async () => {
  if (!codeUploadForm.value.file) {
    ElMessage.warning('请选择代码包文件')
    return
  }
  if (!codeUploadForm.value.name) {
    ElMessage.warning('请输入包名称')
    return
  }

  isUploading.value = true
  codeUploadProgress.value = 0

  try {
    const result = await uploadCodePackage(
      codeUploadForm.value.file,
      codeUploadForm.value.name,
      codeUploadForm.value.version,
      codeUploadForm.value.description,
      (progress) => {
        codeUploadProgress.value = progress
      }
    )

    ElMessage.success('代码包上传成功')
    showCodeUploadDialog.value = false
    
    // 重置表单
    codeUploadForm.value = {
      name: '',
      version: 'v1.0.0',
      description: '',
      file: null
    }
    
    // 刷新列表并选中新上传的包
    await loadCodePackages()
    projectForm.value.code_package = result.id
  } catch (error) {
    ElMessage.error('上传失败')
  } finally {
    isUploading.value = false
    codeUploadProgress.value = 0
  }
}

const editProject = (project: Project) => {
  editingProject.value = project
  const config = project.container_config || {}
  projectForm.value = {
    name: project.name,
    description: project.description,
    version: project.version,
    status: project.status,
    docker_image: project.docker_image,
    local_image_name: project.local_image_name || '',
    code_package: project.code_package,
    code_mount_path: project.code_mount_path || '/opt/project-code',
    git_repo: project.git_repo,
    git_branch: project.git_branch,
    work_dir: project.work_dir,
    start_command: project.start_command,
    container_name: project.container_name,
    container_config: {
      runtime_nvidia: config.runtime === 'nvidia' || config.runtime_nvidia || false,
      network_mode: config.network_mode || '',
      privileged: config.privileged || false,
      restart_policy: config.restart_policy || 'unless-stopped'
    }
  }
  showCreateDialog.value = true
}

const viewProject = (project: Project) => {
  viewingProject.value = project
  showDetailDialog.value = true
}

const showDeployDialog = (project: Project) => {
  deployingProject.value = project
  selectedDevices.value = []
  showDeployDialogVisible.value = true
}

const showConfigDialog = (project: Project) => {
  configuringProject.value = project
  configList.value = project.configs ? [...project.configs] : []
  showConfigDialogVisible.value = true
}

const addConfig = () => {
  configList.value.push({
    key: '',
    value: '',
    description: '',
    is_secret: false
  })
}

const handleSaveProject = async () => {
  if (!projectForm.value.name || !projectForm.value.version) {
    ElMessage.warning('请填写项目名称和版本')
    return
  }

  // 验证必须指定镜像（本地镜像或平台镜像）
  if (!projectForm.value.local_image_name && !projectForm.value.docker_image) {
    ElMessage.warning('请指定本地镜像名称或选择平台镜像')
    return
  }

  try {
    const projectData = prepareProjectData()
    
    if (editingProject.value) {
      await updateProject(editingProject.value.id, projectData)
      ElMessage.success('项目更新成功')
    } else {
      await createProject(projectData)
      ElMessage.success('项目创建成功')
    }
    
    showCreateDialog.value = false
    editingProject.value = null
    resetProjectForm()
    
    await loadProjects()
  } catch (error) {
    ElMessage.error('保存项目失败')
  }
}

const handleDeploy = async () => {
  if (!deployingProject.value || selectedDevices.value.length === 0) {
    return
  }

  try {
    const result = await deployProjectToDevices(
      deployingProject.value.id,
      selectedDevices.value
    )
    
    ElMessage.success(`已创建 ${result.success} 个部署任务`)
    
    if (result.failed > 0) {
      ElMessage.warning(`${result.failed} 个设备部署失败`)
    }
    
    showDeployDialogVisible.value = false
  } catch (error) {
    ElMessage.error('创建部署任务失败')
  }
}

const handleSaveConfig = async () => {
  if (!configuringProject.value) return

  // 过滤掉空的配置项
  const validConfigs = configList.value.filter(c => c.key && c.value)

  try {
    await setProjectConfig(configuringProject.value.id, validConfigs)
    ElMessage.success('配置已保存')
    showConfigDialogVisible.value = false
    await loadProjects()
  } catch (error) {
    ElMessage.error('保存配置失败')
  }
}

const handleDelete = async (project: Project) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除项目 "${project.name}" 吗？此操作不可恢复！`,
      '删除确认',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'error'
      }
    )

    await deleteProject(project.id)
    ElMessage.success('项目已删除')
    await loadProjects()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('删除项目失败')
    }
  }
}

onMounted(() => {
  loadProjects()
  loadDevices()
  loadDockerImages()
  loadCodePackages()
})
</script>

<style scoped>
.project-manage {
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

.text-gray {
  color: #909399;
}

.deploy-info {
  padding: 16px;
  background-color: #f5f7fa;
  border-radius: 4px;
}

.deploy-info p {
  margin: 8px 0;
}

code {
  padding: 2px 6px;
  background-color: #f5f7fa;
  border-radius: 3px;
  font-family: 'Courier New', monospace;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
</style>

