import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { DeploymentTask, UpdateTask } from '@/types'
import { getDeploymentTasks, getUpdateTasks } from '@/api/task'

export const useTaskStore = defineStore('task', () => {
  const deploymentTasks = ref<DeploymentTask[]>([])
  const updateTasks = ref<UpdateTask[]>([])
  const loading = ref(false)

  // 加载部署任务列表
  const loadDeploymentTasks = async () => {
    loading.value = true
    try {
      deploymentTasks.value = await getDeploymentTasks()
    } catch (error) {
      console.error('加载部署任务失败:', error)
    } finally {
      loading.value = false
    }
  }

  // 加载更新任务列表
  const loadUpdateTasks = async () => {
    loading.value = true
    try {
      updateTasks.value = await getUpdateTasks()
    } catch (error) {
      console.error('加载更新任务失败:', error)
    } finally {
      loading.value = false
    }
  }

  // 获取进行中的任务数
  const pendingTasksCount = () => {
    const deploymentPending = deploymentTasks.value.filter(
      t => !['completed', 'failed'].includes(t.status)
    ).length
    const updatePending = updateTasks.value.filter(
      t => !['success', 'failed'].includes(t.status)
    ).length
    return deploymentPending + updatePending
  }

  return {
    deploymentTasks,
    updateTasks,
    loading,
    loadDeploymentTasks,
    loadUpdateTasks,
    pendingTasksCount,
  }
})


