# 用户配置（只填少量信息；其余交给 Codex）

本文件的配置优先于 PLAN 的建议默认值。没有填的项目不可假定已有付费/远端授权。学生可以编辑本文件，或者在启动消息中明确授权并让 Codex 更新它。

| 项目 | 值 |
|---|---|
| 项目 | DASE7506 Clean Start V3 及同一项目的 Harness V4 扩展 |
| 课程截止 | 2026-12-10（具体时间以课程系统为准） |
| 新仓库名 | `dase7506-agent-harness-clean` |
| GitHub owner | `Lmy0415` |
| 创建新私有远端仓库授权 | 用户于 2026-11-27 明确授权新建 `Lmy0415/dase7506-agent-harness-clean`，可见性必须为 Private |
| API provider | DeepSeek 官方 API（`https://api.deepseek.com`），用户于 2026-11-27 指定 |
| Model ID | `deepseek-flash`（官方当日对应 `DeepSeek-V4.1-Flash-1017`），非思考模式、原生工具调用。正式冻结前核对服务版本 |
| API Key | `DEEPSEEK_API_KEY`，从本地环境变量或 Git 忽略的 `.env` 读取 |
| 本项目全部模型 API 调用总费用上限（USD） | 10.00，用户于 2026-11-27 明确授权，所有阶段共用同一硬上限 |
| Formal target | 40 个独立基础任务；资源紧张优先 24–30；更少时如实报告并说明 |
| V4 正式比较 | 原 32 个任务族加同协议扩样的 8 个任务族。R、C+、C++ 复用 checkpoint，已有有效 A/B/C/D 不重复计费 |
| Pilot | 6–10 个独立基础任务，目标 8 |
| D 难度对照 | 优先全体；预算受限预先冻结均衡 12 题子集 |
| 作者、学号、组员、单位 | 待学生提供真实信息（人数最多 5 人）；禁止猜测 |
| PDF/Overleaf | 必须交付本地编译 PDF + 可上传 ZIP；在线上传仅在用户明确授权且权限可用时 |

## 预算说明

10.00 USD 覆盖模型 API 连通检查、pilot、候选筛查、正式分支、D 对照及所有重试。所有请求共用一本费用账，按 API 回执和官方价格核算实际费用。发出请求前按最坏情况预留费用，已结算费用与所有未结算预留之和不得超过 10.00 USD。无法确定可计费上限或余额不足时停止计费调用。旧项目的预算不转移到本项目。

DeepSeek Flash 官方价格，2026-11-27 核对。高峰每百万 token 分别为 0.006 USD（输入缓存命中）、0.30 USD（输入未命中）和 1.20 USD（输出）。非高峰价减半。预算预留和结算上界统一使用高峰价。[DeepSeek 定价表](https://api-docs.deepseek.com/quick_start/pricing/)
