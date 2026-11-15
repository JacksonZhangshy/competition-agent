# 竞赛辅助服务智能体

面向学生、指导教师和竞赛管理人员的学科竞赛全流程辅助系统。整合竞赛规程、管理制度与历年参赛数据，提供知识问答、竞赛推荐、备赛规划、材料评审、经费单据辅助、数据统计与导出。

后端 Python + FastAPI + SQLAlchemy，检索为自建 BM25 + 向量混合索引，工作流为自研 StateGraph 引擎（接口与 LangGraph 对齐），前端 Vue 3 + ECharts。

---

## 快速开始

```bash
# 1. 安装依赖（建议在虚拟环境中）
pip install -r requirements.txt

# 2. 初始化：建表 + 样例数据 + 知识库文档 + 索引
python scripts/init_all.py

# 3. 启动
python run.py
```

浏览器打开 `http://127.0.0.1:8000`，接口文档在 `/api/docs`。

首次运行若提示缺少前端依赖，执行一次：

```bash
python scripts/fetch_vendor.py
```

（该脚本把 Vue 与 ECharts 下载到 `frontend/vendor/`，之后可离线运行。）

---

## 配置大模型

系统在**没有配置大模型时也能完整运行**：问答会走"原文抽取"分支，只重组检索到的原句，不生成新内容，适合离线演示与效果对比。

接入真实模型：复制 `.env.example` 为 `.env`，填写：

```ini
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-xxxxxxxx
# 可选，留空使用厂商默认
LLM_MODEL=deepseek-chat
```

支持 `deepseek` / `qwen` / `doubao` / `openai` / `ollama` / `mock`，均为 OpenAI 兼容协议，也可直接把 `LLM_BASE_URL` 指向任意兼容服务。

改完重启服务，左侧栏底部状态会变为绿色。

---

## 目录结构

```
competition-agent/
├── run.py                    启动入口
├── requirements.txt
├── .env.example              配置模板
├── backend/
│   ├── main.py               FastAPI 应用
│   ├── config.py             配置（读 .env，标准库实现）
│   ├── database.py           引擎与会话
│   ├── models.py             数据模型
│   ├── llm.py                大模型客户端 + 本地向量
│   ├── rag/                  解析 / 切块 / 混合索引 / 导入
│   ├── agent/                工作流引擎 / 工具 / Prompt / 编排
│   ├── services/             统计 / 经费 / 导出
│   └── routers/              HTTP 接口
├── frontend/                 Vue 3 单页应用（无需构建）
├── data/
│   ├── knowledge/            知识库原始文件
│   ├── uploads/
│   ├── outputs/              导出的 Excel / Word
│   └── app.db                SQLite 数据库
├── scripts/                  初始化 / 数据生成 / 自测 / 前端依赖
└── docs/                     交付文档
```

---

## 需求对照

| 需求 | 实现位置 |
| --- | --- |
| 1 知识问答（带原文追溯） | `agent/workflows.py` → `build_qa`；页面「知识问答」 |
| 2 竞赛推荐 | `build_recommend` + 工具 `recommend_candidates`；页面「竞赛推荐」 |
| 3 备赛辅助 | `build_prep`；页面「备赛辅助」 |
| 4 材料评审 | `build_review`；页面「材料评审」 |
| 5 预算申请 | `build_budget` + `services/budget.py`；页面「经费辅助」 |
| 6 借款辅助 | `build_loan`；同上 |
| 7 报销辅助 | `build_reimburse`；同上 |
| 8 数据统计 | `build_stats` + `services/stats.py`；页面「数据统计」 |
| 9 可视化分析 | 前端 ECharts（年度趋势、获奖分布、维度对比） |
| 10 结果导出 | `services/export.py`（Excel 台账、Word 预算/借款/报销单） |
| RAG 与引用溯源 | `rag/`，检索结果带文件名、页码、片段序号 |
| 结构化数据优先 | 所有统计走 SQL 聚合，不经过模型 |
| 可扩展不固化 | 赛项规则在 `Edition.rules_json`，开支标准在 `system_config` 表 |

---

## 自测

两套脚本，都不需要联网：

```bash
python scripts/selftest.py           # 54 项：纯算法，只依赖标准库
python scripts/test_integration.py   # 59 项：连数据库，跑通 8 条工作流与全部导出
```

- `selftest.py` 覆盖分词、向量、切块、工作流引擎、抽取式回答、备赛排期规则、统计维度识别、金额大写。
- `test_integration.py` 覆盖真实数据下的完整链路：问答能否正确拒答、预算总额是否等于明细之和、
  统计分组求和是否等于总计、导出的 Word/Excel 是否真的能打开。

两套都是 `python xxx.py` 直接跑，最后打印 `通过 N/N`，失败时退出码为 1，可接入 CI。

---

## 文档

- `docs/部署与使用说明.md` — 安装、使用、上线、接入真实数据
- `docs/Agent工作流与Prompt说明.md` — 节点编排、工具清单、全部提示词
- `docs/数据库设计.md` — 表结构、字段、统计口径
- `docs/测试报告.md` — 测试项、结果、缺陷记录
- `docs/典型应用案例.md` — 四个可复现的操作剧本

---

## 说明

样例数据为程序生成的演示数据（`scripts/seed.py`，固定随机种子，可复现），不含任何真实师生信息。接入学院真实数据时替换该脚本或走导入接口，见部署说明第 6 节。
