# Xray-Web 架构演进与产品重构需求文档 (PRD)

> **版本**：v2.1-planning  
> **制定时间**：2026-09  
> **文档状态**：已批准 · 准备实施  
> **核心定位**：极轻量、高可靠、带高级极客 UX 的 Xray-core 本地 Web 控制台

---

## 1. 背景与重构动因 (Background & Objectives)

### 1.1 现状与优势
本项目已具备超越普通玩具项目的系统防御力：
- **事务级配置引擎**：内存沙箱预演、原生 `xray -test` 拦截、原子写入与失败回滚。
- **物理隔离测速**：独立端口 + 临时核心进程，不干扰活跃连接，支持实时 SSE 与随时中断。
- **本地安全防线**：单 Host/Origin 强校验、`sec-fetch-site` 阻断、Basic Auth 恒定时间比对。
- **极客 UX 交互**：直通/分流双端口、WSL 桥接宿主机 IP 自动发现与终端命令一键生成、三栏规则可视化。

### 1.2 核心痛点与架构债
1. **伪轻量化陷阱**：前端在浏览器运行时加载 3MB+ 的 Tailwind JIT 编译器，造成首屏延迟与不必要的内存浪费。
2. **前端 Setup 大面团**：`static/js/app.js` 膨胀至近 1500 行，业务逻辑杂糅，缺乏模块化。
3. **后端 Fat Controller**：`main.py` 膨胀至 560+ 行，API 路由层杂糅业务拼接逻辑，缺乏模块解耦。
4. **强耦合 Systemd**：缺乏对纯进程模式的降级支持，限制了 Docker、WSL1、Alpine 等环境的使用。
5. **开源门面治理**：构建压缩包误入 Git 追踪、历史 AI 审查过程文件挤占根目录。

---

## 2. 总体演进架构设计 (Target Architecture)

```text
┌─────────────────────────────────────────────────────────────┐
│                       Browser Frontend                      │
│   Pure ESM Vue 3 (No Bundler) + Precompiled Static CSS      │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ Composables: useNodes | useRouting | useSpeedtest   │   │
│   │              useSubscriptions | useSystem           │   │
│   └─────────────────────────────────────────────────────┘   │
└──────────────────────────────┬──────────────────────────────┘
                               │ REST / SSE (Same-Origin & Host Checked)
┌──────────────────────────────▼──────────────────────────────┐
│                    FastAPI Core Service                     │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ LocalAccessMiddleware (Host, Origin, CSRF, Basic Auth) │ │
│  └────────────────────────────┬───────────────────────────┘ │
│                               │                             │
│  ┌────────────────────────────▼───────────────────────────┐ │
│  │ Routers: /nodes  /routing  /subscriptions  /logs  /sys │ │
│  └────────────────────────────┬───────────────────────────┘ │
│                               │                             │
│  ┌────────────────────────────▼───────────────────────────┐ │
│  │ Domain Core: Store | RoutingManager | SpeedTest        │ │
│  │              Parser | Transactional Config Manager     │ │
│  └────────────────────────────┬───────────────────────────┘ │
│                               │                             │
│  ┌────────────────────────────▼───────────────────────────┐ │
│  │ Runtime Adapter: SystemdRuntime | SubprocessRuntime    │ │
│  └────────────────────────────┬───────────────────────────┘ │
└───────────────────────────────┼─────────────────────────────┘
                                │ System Calls / IPC
                ┌───────────────┴───────────────┐
                │                               │
       ┌────────▼────────┐             ┌────────▼────────┐
       │ systemd service │             │ Ephemeral Xray  │
       │ (Active Core)   │             │ Probing Cores   │
       └─────────────────┘             └─────────────────┘
```

---

## 3. 详细实施任务拆解 (Implementation Milestones)

### Phase 1: 前端真·轻量化与组件解耦 (Frontend Pure Lightweight)

#### P1-1: 剥离运行时 Tailwind JIT，改用预编译纯静态 CSS
- **现状**：`static/index.html` 引入 `static/js/tailwind.js`（浏览器端 JIT 运行时编译，体积超 3MB）。
- **目标**：实现零 JS 样式编译，浏览器直读纯 CSS，首屏样式 0 闪烁，体积缩减 99%。
- **方案**：
  - 提取所有 HTML 和 JS 中的 Tailwind 类名。
  - 使用 Tailwind CLI 离线生成高度精简的 `static/css/app.min.css`（目标体积 < 30KB）。
  - 从 `index.html` 移除 `tailwind.js` 依赖。
- **验收标准**：
  - 前端静态依赖彻底移除 `static/js/tailwind.js`。
  - 页面样式、响应式布局、深色模式 100% 还原且无视觉破坏。

#### P1-2: 拆解 `app.js` 1500 行 Setup 大面团（原生 ESM 方案）
- **现状**：`static/js/app.js` 单文件 1460 行，所有状态和逻辑堆叠在单一 setup 闭包中。
- **目标**：不引入 Vite/Webpack 等重型 Node.js 打包器，采用现代浏览器原生 `<script type="module">` 拆分。
- **方案**：
  - 创建 `static/js/composables/` 目录：
    - `useSystem.js`：系统状态轮询、端口状态、宿主桥接 IP、动态终端命令复制。
    - `useNodes.js`：节点列表、选择/批量操作、节点双击快速切换、地址脱敏。
    - `useSpeedtest.js`：Real Ping 测速、流式峰值下载测速、SSE 事件监听与全链路取消。
    - `useRouting.js`：三栏规则编辑、自动分类、默认出站模式、保存与脏状态追踪。
    - `useSubscriptions.js`：订阅管理、更新、删除、水平滚动条物理转换。
    - `useToast.js`：全局浮动提示消息。
  - 主入口 `app.js` 仅负责组合 composables 并挂载根实例。
- **验收标准**：
  - `tests/frontend.test.cjs` 15 项测试继续全绿通过。
  - 主入口 `app.js` 行数精简至 100 行以内。
  - 保持无需任何前端构建命令，直接刷新浏览器即生效。

#### P1-3: 暗黑界面对比度与微交互视觉调优
- **现状**：极端暗黑场景下背景与卡片分界微弱，在部分低素质屏幕下辨识度受限。
- **目标**：微调色彩层级，提升卡片边缘对比度与行动按钮（CTA）的聚焦度。

---

### Phase 2: 后端架构解耦与 Fat Controller 拆解 (Backend Decoupling)

#### P2-1: 拆分 `main.py` 为模块化 APIRouter
- **现状**：`main.py` 包含 560+ 行，集成了所有领域接口、请求体校验、长文本逻辑判断。
- **方案**：
  - 建立 `routers/` 目录：
    - `routers/nodes.py`：节点 CRUD、导入、切换、单节点/批量测速。
    - `routers/routing.py`：分流规则、三栏分类、模式切换。
    - `routers/subscriptions.py`：订阅源拉取、解析、更新与同步。
    - `routers/system.py`：核心状态、端口获取与修改、健康检查。
    - `routers/logs.py`：Access/Error 日志查询、清空与 SSE 实时流。
  - `main.py` 仅保留 FastAPI 实例构建、中间件挂载、静态资源托管与异常处理器。
- **验收标准**：
  - 现有 `tests/test_api.py` 及全套 60 个单元测试 100% 通过。
  - API 路径、入参、响应字段保持 100% 向后兼容。

#### P2-2: 业务文案与消息格式化剥离
- **现状**：节点导入、订阅更新时的提示字符串直接硬编码在路由方法中。
- **方案**：抽取至 `core/messages.py` 或领域管理类内部，降低 Controller 复杂度。

---

### Phase 3: 运行时解耦（Runtime Adapter Pattern）

#### P3-1: 抽象 `AbstractRuntime` 协议
- **现状**：`core/runtime.py` 内部死锁在 `systemctl` / `sudo systemctl` 命令。
- **方案**：
  - 定义抽象基类 `BaseRuntime`：
    ```python
    class BaseRuntime(ABC):
        def is_active(self) -> bool: ...
        def restart(self) -> None: ...
        def stop(self) -> None: ...
        def validate(self, candidate: Any) -> None: ...
        def write(self, content: bytes) -> None: ...
        def read(self) -> Optional[bytes]: ...
        def backup(self, content: Optional[bytes]) -> None: ...
    ```

#### P3-2: 现有 `SystemdRuntime` 沉淀与规范化
- 保留完整的 systemd 系统模式与 `--user` 模式支持，继续保留权限探测与原子安装机制。

#### P3-3: 新增 `SubprocessRuntime`（独立子进程守护模式）
- **痛点**：Docker、WSL1、Alpine Linux 或受限 Linux 环境下没有 systemd，导致程序无法工作。
- **方案**：
  - 实现 `SubprocessRuntime`：直接通过 Python `subprocess.Popen` 启动 Xray 二进制，管理其生命周期与 PID。
  - 自动健康检测与子进程保活（Crash Auto-restart）。
  - 支持通过环境变量 `XRAY_RUNTIME=systemd|process|auto` 自动无感降级或手动指定。
- **验收标准**：
  - 在无 systemd 环境下能够平稳启动、停止与切换节点。
  - 增加针对 `SubprocessRuntime` 的完整单元测试。

---

### Phase 4: 协议解析稳健性与契约加固 (Parser Hardening)

#### P4-1: 建立明确的分享链接契约矩阵
- 规范化支持清单并在文档中公开承诺：
  - **VLESS**：Reality、TLS、ML-KEM PQ、WS、gRPC、HTTPUpgrade、XHTTP/SplitHTTP
  - **VMess**：Standard VMess (AEAD)、WS、TCP、TLS
  - **Trojan**：Standard Trojan、TLS、gRPC、WS
  - **Shadowsocks**：Legacy AEAD、Shadowsocks 2022 系列（blake3/aes-128-gcm/aes-256-gcm）

#### P4-2: 增强解析异常边界防御
- 强化 URL 双重编码、非标准 Base64 补齐、Emoji/特殊字符备注、不合规端口号的容错与降级拦截。

---

### Phase 5: GitHub 开源门面与工程治理 (Repo Hygiene)

#### P5-1: 仓库文件大扫除
- 移除 `dist/xray-web-source.zip`，并在 `.gitignore` 中彻底屏蔽 `dist/`、`*.zip`、`*.tar.gz`。
- 创建 `docs/internals/` 目录，将过程文档（`CODE_REVIEW.md`、`REVIEW_2026-09-15.md`、`IMPLEMENTATION_PLAN.md`）归档沉淀，保持项目根目录整洁专业。

#### P5-2: CI/CD 自动化集成
- 保持 `.github/workflows/check.yml` 全自动流水线：
  - Python 3.10 / 3.12 跨版本矩阵测试
  - 自动运行 60+ 单元测试
  - 自动运行 Node.js 15+ 前端逻辑测试
  - 静态 Shell 脚本语法检查 (`bash -n`)

#### P5-3: 完善面向社区的 README.md 与贡献指南
- 增补多架构运行指南（WSL / Systemd / Docker 子进程模式）。
- 明确端口映射图、安全建议以及支持的客户端/协议范围。

---

## 4. 实施排期与分步执行规划 (Execution Plan)

| 阶段序号 | 任务名称 | 预计改动范围 | 风险等级 |
| :--- | :--- | :--- | :--- |
| **Step 1** | **仓库文件大扫除与工程治理** (Phase 5) | 移除非源码文件、归档历史 Markdown | 极低 |
| **Step 2** | **前端剥离运行时 Tailwind 并生成纯静态 CSS** (P1-1) | `static/index.html`, `static/css/` | 低 |
| **Step 3** | **前端 app.js 解耦为原生 ESM Composables** (P1-2, P1-3) | `static/js/composables/`, `app.js` | 中（需回归测试） |
| **Step 4** | **后端 main.py 拆分 APIRouter** (Phase 2) | `routers/`, `main.py` | 低（有完整 API 测试兜底） |
| **Step 5** | **运行时解耦与子进程守护模式** (Phase 3) | `core/runtime.py`, `config.py` | 中 |
| **Step 6** | **端到端完整回归验证与版本发布** | 全套自动化测试 + 页面交互手动复核 | 极低 |

---

## 5. 质量底线 (Quality Gates)

1. **测试零失败**：每一次改动提交，必须保证原有的 60 个 Python 单元测试和 15 个 Node 前端逻辑测试 100% 通过。
2. **零新增运行时依赖**：生产环境绝对不引入 Node.js 运行环境；前端保持纯静态文件分发。
3. **安全契约不打折**：任何重构不得削弱现有的同源校验、Host 校验、安全标头与原子回滚机制。
