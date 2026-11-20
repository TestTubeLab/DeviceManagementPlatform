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

### 5. 系统日志

- 侧栏 FRP 管理下方的 `/system-logs` 对所有已登录用户开放，包含平台日志和设备日志。
- 平台日志默认查询最近 24 小时，支持时间、级别、模块、操作人、结果、关键词筛选及详情查看；每页默认 50 条，最多 100 条。编辑筛选后点击查询，应用时回到第一页，输入过程中不创建请求。
- 设备日志支持平台已保存的容器日志（离线设备也可读取）、业务文件列表/读取/搜索/原始 ZIP 下载，以及 Agent、FRPC、Docker、系统 journal。当前内容可复制或下载 TXT，日志均按纯文本展示。
- 服务 journal 需要 Agent >= 1.7.3；旧版或未知版本显示手动升级按钮，调用现有 `updateAgent`，不会自动升级。设备离线时禁止远程操作。
- 手动刷新为默认方式；自动刷新需手动开启，间隔 10 秒，页面隐藏、浏览器断网、设备离线、筛选尚未应用或请求进行中时暂停。默认时间窗口随刷新滚动，手动选择的范围保持固定。切换设备、来源、标签或离开页面会取消日志请求并丢弃过期结果。取消只停止浏览器等待，已提交的设备任务仍可能完成。

实现入口为 `src/views/SystemLogs.vue`、`src/components/system-logs/` 和 `src/api/systemLogs.ts`，无新增依赖。平台 API 使用 `GET /api/system-logs/` 和 `GET /api/system-logs/{id}/`；`getLogsPage` 保留 `/api/logs/` 的 DRF `count/results` 分页，现有 `api/log.ts#getLogs` 继续返回数组，并显式请求 100 条以保持原有上限。已知模块与操作显示中文，未知值原样显示。日期时间发送 ISO 字符串；业务文件搜索沿用现有接口的本地日期范围（按天）。

业务日志继续使用 `list_logs/read_log/search_logs/download_log/log_task_result`；服务采集使用 `POST /api/devices/{device_id}/service_logs/`，发送 `source/start_time/end_time/lines/level/keyword`，默认 500 行，上限 2000 行。设备路由沿用现有 `device_id` 标识，新任务 ID 为 UUID 字符串，同时兼容历史数字 ID。任务创建和轮询共用 AbortSignal，每秒查询一次，整个操作最多等待 60 秒，失败或超时显示可重试错误。日志 API 复用共享请求客户端和 Token 认证；共享错误拦截器对 Axios 取消直接拒绝，不弹全局错误提示。

验证：`npm run build`。联调时检查筛选/翻页、四种 journal 来源、业务读取/搜索/ZIP、离线与旧版 Agent、失败/超时、快速切换设备/来源/标签、隐藏页面的自动刷新暂停，以及日志中 HTML 标签仅作为文本显示。

系统日志 QA 步骤（使用合成数据与可控的 Agent 任务结果）：

1. 以普通登录用户打开 `/system-logs`，确认菜单位于 FRP 下方、默认最近 24 小时、每页 50 条。检查模块/操作的中文标签与未知值回退，查看详情后复制和下载 TXT。
2. 翻到第二页，编辑关键词，确认输入不产生请求；点击查询后请求 `page=1`。逐项验证时间、级别、模块、操作人、结果与关键词，切换每页 100 条及重置。
3. 设备日志选择离线设备，确认保存日志可查询与导出 TXT，业务和 journal 操作禁用。选择旧版/未知版本 Agent，确认 journal 不可采集，只有手动点击升级才创建更新请求；刷新设备状态后重新判断能力。
4. 在线设备分别采集 Agent、FRPC、Docker、系统日志，检查默认 500 行、最多 2000 行、ISO 时间参数、UUID 任务 ID、每秒轮询及采集时间/行数/截断提示。任务中重复点击不产生第二个请求。
5. 业务日志获取文件列表、选择文件读取、关键词搜索，确认结果显示 `date/file:line_num`；检查读取/搜索的截断提示。下载原始 ZIP，复制/下载当前 TXT，核对内容。
6. 对任务模拟 failed、持续 pending 超过 60 秒、请求断网，确认错误可见、加载结束并可重试。请求中切换设备/来源/标签或离开页面，确认停止等待、旧响应不覆盖新内容、取消不弹全局错误、无未处理 Promise 错误。
7. 默认不开启自动刷新；开启后每 10 秒刷新。隐藏页面、浏览器断网、设备离线、编辑未提交的筛选或请求未完成时确认暂停，恢复后继续。默认 24 小时时间窗口随刷新前移。
8. 用含 `<script>`、`<img onerror>` 的合成日志确认只显示文本。桌面、390px、320px 检查固定日志区内部滚动、日期弹层、设备/来源下拉框关闭后页面无横向溢出。紧凑侧栏仅用于系统日志页，菜单保留可访问名称。

设备详情保留原日志中心入口，读取行数为 1–2000，截断结果会显示提示。列表、读取、搜索和 ZIP 下载复用系统日志的 60 秒总期限及取消机制；关闭、切换设备、离开页面或选择另一文件会停止旧请求并丢弃过期结果。`api/device.ts` 的日志任务 ID 和 `LogTaskCreated.task_id` 均兼容 `string | number`，创建及结果查询函数接受可选的 `AbortSignal`，已有无信号调用保持兼容。取消仅停止浏览器等待，已创建的设备任务仍可能执行。

定向回归检查使用项目现有 Vue、TypeScript 和 Node 内置测试工具，无新增依赖：在 `frontend/` 执行 `node --test tests/release-regressions.test.cjs`，随后执行 `npm run build`。检查运行实际组件 setup 和共享日志请求代码，以合成 API、可控时钟及 Vue 服务端渲染验证 11 秒任务完成、60 秒超时、取消和过期响应、任务 ID/行数边界、列表/搜索/ZIP、配置纯文本展示、资源刷新期间的编辑草稿和任务详情更新。此脚本不代替真实设备及浏览器联调。

已知限制：旧设备、项目、任务列表和部分选择器尚未完整处理超过 100 条的分页；本次修复不改变该范围，新系统日志的设备选择器已遍历分页。

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



