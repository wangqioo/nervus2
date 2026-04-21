# Nervus2

> 连接所有 App 的神经系统 — 第二代

Nervus2 是一个运行在边缘设备上的个人 AI 神经系统。它不是一个被动等待调用的助手，而是一个持续运行、持续感知的后台智能层。系统自动从你使用的 App 中提取信号，推断你的状态，并将这些洞察共享给所有 App，让每一个 App 都能感知"你是谁"。

目标硬件：**NVIDIA Jetson Orin Nano 8GB**，全本地运行，零云依赖。

---

## V1 vs V2 架构对比

| | V1 | V2 |
|---|---|---|
| 核心智能 | Arbor Core（语义路由 + 动态规划） | **Personal Model**（20 个用户维度） |
| App 如何接收信息 | 订阅原始 NATS 事件 | 订阅维度状态更新 |
| 跨 App 洞察 | 无 | **Insight Engine**（每小时跨维度关联分析） |
| LLM 调用位置 | Arbor Core 实时路由时 | Model Updater 定期批处理（5分钟一次） |
| Arbor Core 职责 | 路由 + 语义决策 | 仅快速路由（规则匹配，<100ms） |

---

## 系统架构

```
感知层 (Apps)
    |
    v  NATS Events
Arbor Core v2
 ├─ FastRouter  ──→  Flow Executor  ──→  Apps (intake)
 └─ DimDispatcher ──→  Apps (on_dimension)
    ^                      ^
    |                      |
    | pm.dimension.updated.*
    |
Personal Model Service (port 8100)
 ├─ Model Updater  (每 5 分钟)
 │   NATS事件缓冲 → LLM推理 → 更新20个维度
 │
 ├─ Insight Engine (每 1 小时)
 │   读取所有维度 → 跨维度关联分析 → 存储洞察
 │
 └─ REST API
     GET  /dimensions          列出所有维度及当前状态
     GET  /dimensions/:id      单个维度详情
     GET  /dimensions/:id/history  时间序列历史
     GET  /insights            最近洞察列表
     POST /query               自然语言提问
     POST /corrections         用户修正推理
     GET  /status              系统快照
     GET  /cold-start          冷启动进度

基础设施
 ├─ NATS JetStream   事件总线
 ├─ Redis            维度当前状态（热存储）
 ├─ PostgreSQL + pgvector  维度历史快照 + 语义检索
 ├─ llama.cpp        本地 LLM（Qwen3.5-4B）
 └─ Faster-Whisper   本地语音转文字
```

---

## Personal Model — 20 个维度

Personal Model 是 V2 的核心。它持续追踪你的 20 个生活维度，每个维度都有置信度、更新时间和历史快照。

### 健康 Health
| 维度 | 说明 | 刷新周期 |
|---|---|---|
| `nutrition_24h` | 过去 24h 卡路里与宏量营养素 | 24h |
| `sleep_last_night` | 昨晚睡眠时长与质量 | 24h |
| `sleep_pattern_14d` | 14 天睡眠趋势 | 6h |
| `activity_today` | 今日运动强度与步数 | 3h |

### 认知 Cognition
| 维度 | 说明 | 刷新周期 |
|---|---|---|
| `cognitive_load_now` | 当前脑力负荷 | 1h |
| `focus_quality_today` | 今日深度工作质量 | 6h |
| `stress_indicator` | 当前压力水平 | 2h |
| `energy_level_now` | 当前能量水平 | 2h |

### 知识 Knowledge
| 维度 | 说明 | 刷新周期 |
|---|---|---|
| `active_topics` | 当前正在学习的主题 | 24h |
| `knowledge_graph_state` | 知识图谱概览 | 12h |
| `reading_velocity` | 内容消费速率与类型 | 24h |

### 时间/行为 Temporal
| 维度 | 说明 | 刷新周期 |
|---|---|---|
| `daily_routine` | 检测到的每日作息规律 | 6h |
| `weekly_pattern` | 每周行为模式 | 24h |
| `upcoming_context` | 未来 24h 日程上下文 | 1h |
| `location_context` | 当前位置情境（家/工作/出行） | 4h |

### 社交 Social
| 维度 | 说明 | 刷新周期 |
|---|---|---|
| `social_rhythm` | 近期社交互动频率与质量 | 12h |
| `key_relationships` | 最近活跃的关系 | 24h |
| `communication_load` | 消息与会议量 | 2h |

### 幸福感 Wellbeing
| 维度 | 说明 | 刷新周期 |
|---|---|---|
| `mood_indicator` | 当前情绪状态 | 3h |
| `life_satisfaction_trend` | 14 天生活满意度趋势 | 24h |

---

## 冷启动

系统需要一段时间来积累数据，分三个阶段：

| 阶段 | 时间 | 行为 |
|---|---|---|
| Phase 0 | Day 0–3 | 仅积累事件，不推理 |
| Phase 1 | Day 3–14 | 开始推理，置信度较低（~45%） |
| Phase 2 | Day 15+ | 全量运行，置信度正常（~85%） |

可通过 `GET /cold-start` 查看当前进度。

---

## 目录结构

```
nervus2/
├── personal-model/          # V2 核心服务 (port 8100)
│   ├── model/
│   │   ├── dimensions.py    # 20个维度定义
│   │   ├── state.py         # Redis 当前状态管理
│   │   └── snapshot.py      # PostgreSQL 历史快照
│   ├── workers/
│   │   ├── model_updater.py # 5分钟更新循环
│   │   └── insight_engine.py# 每小时洞察分析
│   ├── api/
│   │   ├── dimensions_api.py
│   │   ├── query_api.py     # 自然语言提问
│   │   ├── corrections_api.py
│   │   └── status_api.py
│   └── infra/               # NATS / Redis / PostgreSQL / LLM 客户端
│
├── arbor-core/              # V2 精简路由引擎 (port 8090)
│   ├── router/
│   │   ├── fast_router.py   # 规则匹配路由 (<100ms)
│   │   └── registry.py      # App 注册与 Action 调度
│   ├── executor/
│   │   ├── flow_loader.py   # JSON Flow 加载与热重载
│   │   └── flow_executor.py # Flow 执行引擎
│   ├── infra/
│   │   └── dim_dispatcher.py# 维度更新扇出到订阅 App
│   └── flows/
│       └── core_flows.json  # 6 个预定义 Flow
│
├── apps/
│   ├── calorie-tracker/     # 食物识别 + 卡路里追踪 (port 8001)
│   ├── knowledge-base/      # 语义知识库 + RAG (port 8004)
│   └── meeting-notes/       # 会议转录 + 洞察 (port 8002)
│
├── nervus-sdk/              # V2 Python SDK
│   └── nervus_sdk/
│       ├── app.py           # NervusApp 装饰器 API
│       ├── model.py         # PersonalModelClient
│       ├── bus.py           # NATS SynapseBus
│       ├── context.py       # Redis Context Graph
│       ├── memory.py        # PostgreSQL MemoryGraph
│       └── llm.py           # 本地 LLM 客户端
│
├── infra/
│   ├── postgres/init.sql    # 数据库 Schema（含 pgvector）
│   ├── nats/nats.conf       # NATS JetStream 配置
│   └── redis/redis.conf     # Redis 配置（限制 512MB）
│
├── tests/                   # 74 个单元测试
├── docker-compose.yml
└── .env.example
```

---

## 快速开始

### 前置要求

- Docker & Docker Compose
- Qwen3.5-4B GGUF 模型文件（放入 `llama-models` volume）

### 1. 准备配置

```bash
git clone https://github.com/wangqioo/nervus2.git
cd nervus2
cp .env.example .env
```

### 2. 放入模型文件

```bash
# 将 qwen3.5-4b-q4_k_m.gguf 放入 Docker volume
# Jetson 上推荐使用 Q4_K_M 量化版本（~2.8GB）
docker volume create nervus2_llama-models
# 将模型文件复制到 volume 对应路径
```

### 3. 启动基础设施

```bash
# 先启动基础设施，等待就绪
docker compose up nats redis postgres -d

# 确认就绪
docker compose ps
```

### 4. 启动全服务

```bash
docker compose up -d
```

### 5. 验证运行

```bash
# Personal Model 状态
curl http://localhost:8100/status

# 冷启动进度
curl http://localhost:8100/cold-start

# 所有维度列表
curl http://localhost:8100/dimensions

# Arbor Core 状态
curl http://localhost:8090/health
```

---

## 内存预算（Jetson Orin Nano 8GB）

| 服务 | 内存限制 |
|---|---|
| llama.cpp (Qwen3.5-4B Q4_K_M) | 3200 MB |
| Faster-Whisper | 600 MB |
| PostgreSQL | 512 MB |
| Redis | 640 MB |
| NATS JetStream | 128 MB |
| Personal Model | 256 MB |
| Arbor Core | 128 MB |
| Apps (3x) | ~100 MB × 3 |
| **合计** | **~6.1 GB** |

---

## 使用 nervus-sdk v2 开发 App

```python
from nervus_sdk import NervusApp, Event
import uvicorn

app = NervusApp(
    app_id="my-app",
    name="My App",
    description="示例 App",
)

# 订阅维度更新（V2 新特性）
@app.on_dimension("stress_indicator", min_confidence=0.6)
async def on_stress(state: dict, confidence: float):
    level = state.get("level")
    if level in ("high", "acute"):
        # 用户压力较大，调整 App 行为
        ...

# 订阅原始 NATS 事件（V1 兼容）
@app.on("health.calorie.meal_logged")
async def on_meal(event: Event):
    calories = event.payload.get("calories")
    ...

# 声明 Action（可由 Arbor Core 调用）
@app.action("get_summary", description="返回今日摘要")
async def get_summary(params: dict) -> dict:
    return {"summary": "..."}

# 查询 Personal Model
@app.state
async def get_state() -> dict:
    answer = await app.model.query("我今天状态怎么样？")
    return {"ai_insight": answer}

if __name__ == "__main__":
    uvicorn.run(app.build_fastapi(), host="0.0.0.0", port=8010)
```

### PersonalModelClient API

```python
# 读取单个维度
dim = await app.model.get_dimension("stress_indicator")

# 读取所有健康维度
health_dims = await app.model.get_all_dimensions(category="health")

# 自然语言提问
result = await app.model.query("为什么我最近总是很累？")
print(result["answer"])

# 提交用户修正
await app.model.submit_correction(
    dim_id="sleep_last_night",
    corrected_value={"duration_hours": 7.5, "quality_score": 8},
    note="实际睡了7.5小时，系统低估了",
)

# 获取最近洞察
insights = await app.model.get_insights(limit=5)
```

---

## API 参考

### Personal Model Service (port 8100)

```
GET  /dimensions                    # 所有维度及当前状态
GET  /dimensions?category=health    # 按分类筛选
GET  /dimensions/{dim_id}           # 单个维度详情
GET  /dimensions/{dim_id}/history   # 时间序列历史（支持 since 参数）
GET  /insights                      # 最近跨维度洞察
POST /query                         # 自然语言提问
     Body: {"question": "...", "include_insights": true}
POST /corrections                   # 提交修正
     Body: {"dim_id": "...", "corrected_value": {...}, "note": "..."}
GET  /corrections                   # 修正历史
GET  /health                        # 健康检查
GET  /status                        # 完整系统快照
GET  /cold-start                    # 冷启动进度
```

### Arbor Core (port 8090)

```
POST /register                      # 注册 App
GET  /list                          # 已注册 App 列表
GET  /{app_id}                      # 单个 App 详情
GET  /notifications                 # 通知列表
POST /notifications                 # 创建通知
POST /notifications/{id}/read       # 标记已读
GET  /health                        # 健康检查
GET  /status                        # 系统状态
GET  /flows                         # 已加载 Flow 列表
```

---

## 运行测试

```bash
# 安装测试依赖
pip install pytest pydantic

# 运行全部测试（74个，无需 NATS/Redis/PostgreSQL）
python -m pytest tests/ -v
```

测试覆盖：
- 维度注册表与 NATS 通配符匹配
- 冷启动阶段边界条件
- FlowLoader 规则匹配与校验
- FlowExecutor JSONPath 参数解析
- nervus-sdk v2 数据模型与约束

---

## 与 V1 的关系

本项目是对 [nervus-core](https://github.com/wangqioo/nervus-core) 的完全重写，基于 [nervus](https://github.com/wangqioo/nervus) 中定义的 V2 架构设计。

主要改变：

- **移除** SemanticRouter 和 DynamicRouter — 这两个组件在 V1 中每次事件都要调用 LLM，延迟高、资源消耗大
- **新增** Personal Model — 将 LLM 调用从"实时路由"改为"定期批处理"，在 Jetson 硬件上更高效
- **新增** Insight Engine — V1 中不存在跨 App 的关联分析能力
- **新增** `@app.on_dimension()` — App 不再需要自己解析原始事件来判断用户状态
- **修复** V1 中 App 数据孤岛问题 — 维度作为共享状态层，所有 App 读写同一份用户画像

---

## License

MIT
