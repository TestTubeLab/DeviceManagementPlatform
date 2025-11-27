# 设备管理平台 - 前端

## 🚀 快速开始

### 安装依赖

```bash
npm install
```

### 启动开发服务器

```bash
npm run dev
```

访问: http://localhost:5173

### 构建生产版本

```bash
npm run build
```

## 📁 项目结构

```
frontend/
├── src/
│   ├── api/              # API 服务层
│   │   ├── request.ts   # Axios 配置
│   │   ├── device.ts    # 设备相关 API
│   │   ├── task.ts      # 任务相关 API
│   │   └── log.ts       # 日志相关 API
│   ├── components/       # 通用组件
│   │   ├── DeviceCard.vue      # 设备卡片
│   │   └── StatusBadge.vue     # 状态标签
│   ├── layouts/          # 布局组件
│   │   └── MainLayout.vue      # 主布局
│   ├── router/           # 路由配置
│   │   └── index.ts
│   ├── stores/           # 状态管理(Pinia)
│   │   ├── device.ts    # 设备状态
│   │   └── task.ts      # 任务状态
│   ├── types/            # TypeScript 类型定义
│   │   └── index.ts
│   ├── views/            # 页面视图
│   │   ├── Dashboard.vue        # 监控仪表盘
│   │   ├── DeviceList.vue       # 设备列表
│   │   ├── DeviceDetail.vue     # 设备详情
│   │   ├── DeployCenter.vue     # 部署中心
│   │   └── TaskManage.vue       # 任务管理
│   ├── App.vue
│   └── main.ts
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts
```

## 🎨 主要功能

### 1. 监控仪表盘
- 实时设备统计
- 设备状态分布图表
- 最近上线设备列表
- 最近任务列表

### 2. 设备管理
- 设备列表展示（卡片式）
- 设备状态筛选
- 设备搜索
- 添加新设备
- 查看设备详情
- 实时资源监控（CPU/内存/磁盘）

### 3. 部署中心
- 批量设备选择
- 部署配置管理
- 一键部署
- 部署进度跟踪

### 4. 任务管理
- 部署任务列表
- 更新任务列表
- 任务状态追踪
- 任务详情查看

## 🛠️ 技术栈

- **框架**: Vue 3 + TypeScript
- **构建工具**: Vite 5
- **UI 组件库**: Element Plus
- **状态管理**: Pinia
- **路由**: Vue Router 4
- **HTTP 客户端**: Axios
- **图表库**: ECharts 5
- **日期处理**: dayjs

## ⚙️ 配置说明

### API 代理配置

`vite.config.ts` 中已配置开发环境 API 代理:

```typescript
server: {
  port: 5173,
  proxy: {
    '/api': {
      target: 'http://127.0.0.1:8080',  // Django 后端地址
      changeOrigin: true,
    },
  },
}
```

### 环境变量

创建 `.env.local` 文件配置环境变量:

```env
# API 基础地址 (生产环境)
VITE_API_BASE_URL=http://your-server-ip:8080/api
```

## 📝 开发指南

### 添加新页面

1. 在 `src/views/` 下创建新的 Vue 组件
2. 在 `src/router/index.ts` 中添加路由配置
3. 在 `MainLayout.vue` 的菜单中添加入口

### 添加新 API

1. 在 `src/api/` 下创建或编辑 API 文件
2. 使用 `request` 实例发起请求
3. 在 `src/types/` 中定义数据类型

### 状态管理

使用 Pinia 管理全局状态:

```typescript
import { useDeviceStore } from '@/stores/device'

const deviceStore = useDeviceStore()
await deviceStore.loadDevices()
```

## 🐛 故障排查

### 端口被占用

```bash
# Windows
netstat -ano | findstr :5173
taskkill /F /PID <PID>

# Linux/Mac
lsof -ti:5173 | xargs kill -9
```

### API 请求失败

1. 检查 Django 后端是否运行（http://127.0.0.1:8080/api/）
2. 检查 CORS 配置是否正确
3. 打开浏览器开发者工具查看网络请求

### 依赖安装问题

```bash
# 清除缓存重新安装
rm -rf node_modules package-lock.json
npm install
```

## 📄 许可证

MIT



