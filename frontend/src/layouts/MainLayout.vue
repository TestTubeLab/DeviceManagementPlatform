<template>
  <el-container class="layout-container">
    <el-header class="header">
      <div class="header-left">
        <el-icon class="logo-icon"><Monitor /></el-icon>
        <span class="title">设备管理平台</span>
      </div>
      <div class="header-right">
        <el-badge :value="activeTaskCount" class="item" :hidden="activeTaskCount === 0">
          <el-button :icon="Bell" circle @click="showNotifications = true" />
        </el-badge>
        <el-dropdown @command="handleCommand">
          <div class="user-info">
            <el-avatar :size="32">
              <el-icon><User /></el-icon>
            </el-avatar>
            <span class="username">{{ username }}</span>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>
                <el-icon><User /></el-icon>
                {{ username }}
              </el-dropdown-item>
              <el-dropdown-item command="logout" divided>
                <el-icon><SwitchButton /></el-icon>
                退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-header>
    
    <el-container>
      <el-aside width="200px" class="sidebar">
        <el-menu
          :default-active="currentRoute"
          router
          class="sidebar-menu"
        >
          <el-menu-item index="/dashboard">
            <el-icon><DataLine /></el-icon>
            <span>监控仪表盘</span>
          </el-menu-item>
          <el-menu-item index="/devices">
            <el-icon><Monitor /></el-icon>
            <span>设备管理</span>
          </el-menu-item>
          <el-menu-item index="/projects">
            <el-icon><FolderOpened /></el-icon>
            <span>项目管理</span>
          </el-menu-item>
          <el-menu-item index="/tasks">
            <el-icon><List /></el-icon>
            <span>任务管理</span>
          </el-menu-item>
          <el-menu-item index="/frp">
            <el-icon><Connection /></el-icon>
            <span>FRP管理</span>
          </el-menu-item>
        </el-menu>
      </el-aside>
      
      <el-main class="main-content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
    
    <!-- 消息通知抽屉 -->
    <el-drawer v-model="showNotifications" title="进行中任务" direction="rtl" size="400px">
      <div v-if="activeTaskCount === 0" class="empty-notifications">
        <el-empty description="暂无进行中任务" />
      </div>
      <div v-else class="notifications-list">
        <el-card 
          v-for="task in activeDeployments" 
          :key="task.id"
          shadow="hover"
          class="notification-item"
        >
          <div class="task-info">
            <div class="task-header">
              <el-space size="small">
                <el-tag type="primary">项目部署</el-tag>
                <el-tag :type="getProjectDeploymentStatusType(task.status)">
                  {{ getProjectDeploymentStatusText(task.status) }}
                </el-tag>
              </el-space>
              <span class="task-device">{{ task.device_info?.name || task.device_info?.device_id }}</span>
            </div>
            <div class="task-detail">
              <span>{{ task.project_info?.name }} ({{ task.deployed_version }})</span>
            </div>
            <div class="task-time">
              {{ formatTime(task.created_at) }}
            </div>
          </div>
        </el-card>
      </div>
      <template #footer>
        <el-button type="primary" @click="$router.push('/tasks'); showNotifications = false">
          查看全部任务
        </el-button>
      </template>
    </el-drawer>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Monitor, DataLine, List, Bell, User, FolderOpened, SwitchButton, Connection } from '@element-plus/icons-vue'
import { logout, getStoredUser, clearAuth } from '@/api/auth'
import { getProjectDeployments, type ProjectDeployment } from '@/api/project'
import {
  ACTIVE_PROJECT_DEPLOYMENT_STATUS_QUERY,
  getProjectDeploymentStatusText,
  getProjectDeploymentStatusType,
} from '@/utils/projectDeploymentStatus'
import { ElMessage, ElMessageBox } from 'element-plus'
import dayjs from 'dayjs'

const route = useRoute()
const router = useRouter()
const showNotifications = ref(false)
const activeDeployments = ref<ProjectDeployment[]>([])
const activeTaskTotal = ref(0)

const currentRoute = computed(() => route.path)
const activeTaskCount = computed(() => activeTaskTotal.value)

// 获取用户名
const username = computed(() => {
  const user = getStoredUser()
  return user?.username || '用户'
})

const formatTime = (time: string) => {
  return dayjs(time).format('MM-DD HH:mm')
}

// 加载进行中的部署任务
const loadActiveDeployments = async () => {
  try {
    const res = await getProjectDeployments({ status: ACTIVE_PROJECT_DEPLOYMENT_STATUS_QUERY })
    activeDeployments.value = res.results || []
    activeTaskTotal.value = res.count ?? (res.results || []).length
  } catch (error) {
    console.error('加载进行中任务失败:', error)
  }
}

// 处理下拉菜单命令
const handleCommand = async (command: string) => {
  if (command === 'logout') {
    try {
      await ElMessageBox.confirm('确定要退出登录吗？', '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      })
      
      try {
        await logout()
      } catch {
        // 忽略登出 API 错误
      }
      
      clearAuth()
      ElMessage.success('已退出登录')
      router.push('/login')
    } catch {
      // 用户取消
    }
  }
}

let refreshTimer: number

// 初始加载任务
onMounted(() => {
  loadActiveDeployments()
  // 定期刷新任务数量（30秒）
  refreshTimer = setInterval(loadActiveDeployments, 30000)
})

onUnmounted(() => {
  clearInterval(refreshTimer)
})
</script>

<style scoped>
.layout-container {
  min-height: 100vh;
}

.header {
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.08);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo-icon {
  font-size: 28px;
  color: #409eff;
}

.title {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.header-right {
  display: flex;
  align-items: center;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: 16px;
  cursor: pointer;
}

.username {
  font-size: 14px;
  color: #303133;
}

.sidebar {
  background: #fff;
  border-right: 1px solid #e4e7ed;
}

.sidebar-menu {
  border-right: none;
  height: 100%;
}

.main-content {
  background: #f5f7fa;
  padding: 20px;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.empty-notifications {
  padding: 40px 0;
}

.notifications-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.notification-item {
  margin-bottom: 0;
}

.task-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-device {
  font-weight: 600;
  color: #303133;
}

.task-detail {
  font-size: 13px;
  color: #606266;
}

.task-time {
  font-size: 12px;
  color: #909399;
}
</style>

