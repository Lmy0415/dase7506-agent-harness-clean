# DASE7506 Clean Start V3 — 使用说明

## 给学生：你只需做这几步

1. 解压项目包到全新目录，例如 `~/Desktop/DASE7506/AgentHarnessV3/`。不要放进旧仓库、不要克隆旧项目。
2. 打开 Codex，选择这个目录为 workspace，开启一个新 thread。确认 GitHub 登录身份，若允许创建新私有仓库就明确授权。
3. 如需付费 API，按所用 provider 官方说明在本地设置环境变量或 `.env`。先保证 `.gitignore` 生效。不要把 key 放到 `PROJECT_CONFIG.md`、聊天、提交记录或论文里。
4. 在 `PROJECT_CONFIG.md` 填自己的总预算（例如 5 USD 只是建议，按你愿意支付的金额填写）；可在对话中明确授权让 Codex 更新。作者信息可以稍后补充。没有预算时 Codex 先完成免费工作。
5. 将 `GOAL.txt` 的整行（含 `/goal`）复制到支持 Goals 的 Codex 输入框。如果该版本没有 Goals，用普通消息发送去掉 `/goal` 的同一内容，要求按 PLAN 自主推进。不要另发 V1/V2 或复制旧对话。
6. 运行过程看 `PROGRESS.md`，不必每次说“继续”。阶段结束时 Codex 会记录实际结果。注意 Codex 的权限/预算限制及宿主是否支持持久进程。

可选启动授权消息（请把数字换成你自己的真实预算，且仅在确实同意时发送）：

> 这是全新项目。授权在我的 GitHub 账户下新建一个私有仓库 dase7506-agent-harness-clean（如重名使用新名称，不覆盖旧仓库）；本次所有实验付费模型 API 总上限为 USD [填写金额]。密钥已在本地配置（如果尚未配置，请如实告诉 Codex）。请将授权写入 PROJECT_CONFIG.md。读取当前目录文件，立即从阶段 0 开始，不要重新给我一份计划。

使用 /goal 前可先发这条授权；也可以先填配置再直接发 Goal。仅有 API Key 不代表已经授权消费任何额度。

## 文件地图

| 文件 | 用途 |
|---|---|
| `START_HERE.md` | 给学生的启动说明 |
| `PLAN.md` | 完整新实验协议，阶段任务、为什么、验收和退路 |
| `AGENTS.md` | 给 Codex 的持久工作规则，控制过度工程化和请求消耗 |
| `GOAL.txt` | 一条可复制的持久 Goal |
| `COURSE_REQUIREMENTS.md` | 原始课程通知和学生追加的交付要求 |
| `PROJECT_CONFIG.md` | 预算、模型、仓库、作者信息等授权 |
| `PROGRESS.md` | 初始进度与每阶段中文反馈模板 |
| `reference/literature_review.xlsx` | 原始组内研究设计与文献记录，仅参考；PLAN 优先 |
| `.gitignore` | 防止密钥、环境和大型原始数据被误提交 |

官方资料：
- Goals: https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex
- AGENTS.md: https://developers.openai.com/cookbook/examples/codex/iterating-development-workflows-with-codex
- Overleaf IEEE Conference: https://www.overleaf.com/latex/templates/ieee-conference-template/grfzhhncsfqn

## 何时算完成

不是 C 的成功率超越 B，而是按协议完成真实实验与分析，提交论文 PDF、LaTeX 工程 ZIP、可复现代码、中文说明。请自行检查作者信息及课程系统截止时间，最后由学生确认并提交。
