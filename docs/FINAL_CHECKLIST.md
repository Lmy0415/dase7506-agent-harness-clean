# 最终验收清单

按 [PLAN.md](../PLAN.md) 第 11 节逐项核对。所有原始模型轨迹和模拟世界均留在当前工作区。

| 项目 | 状态 | 查验的证据 |
| --- | --- | --- |
| 干净新项目、来源、依赖及运行命令 | 通过 | 当前仓库从零初始化。README 固定 InterventionBench 提交和 AppWorld 版本，[环境锁](../requirements.txt) 记录实际依赖。 |
| 官方模拟器与真实模型交互 | 通过 | 两道真实调试题验证状态恢复。DeepSeek 返回原生工具调用，模拟器记录成功写入、拒绝写入和无效果重复。 |
| A/B/C 同起点，D 独立 | 通过 | 验证 32 个正式 checkpoint 的数据库文件哈希、历史、计划与未提交请求。96 个 A/B/C 分支与题单状态和历史一致，32 个 D 独立执行。正式 128/128 条评分。 |
| Pilot 分离，配置及题单先冻结，失败保留 | 通过 | 核对任务族无交集及文件落盘顺序。[设置](../protocol/settings.json) 早于正式筛查，[题单](../protocol/formal_manifest.json) 早于所有正式后缀。原 B 失败尝试留在本地。 |
| 逐题、轨迹、用量、排除和配对可重建 | 通过 | 从本地数据库与轨迹生成 [分支表](../results/branch_metrics.csv)、[筛查表](../results/screening_cases.csv)、[费用](../results/cost_breakdown.csv) 和 [配对表](../results/paired.csv)。四个代表性任务复核到具体工具状态和断言。 |
| 主要结果、分层、D、成本、案例和局限 | 通过 | A/B/C 严格成功 22/32、19/32、21/32，D 修订终态 22/32。论文报告 26 Swap、6 Drop、三个对比区间和评分语义差异。六条部分 Drop 的保留要求有额外的事后重叠断言审计，正式分数保持冻结。 |
| 中文阶段反馈及白话说明 | 通过 | [阶段反馈](../PROGRESS.md) 与 [白话说明](PROJECT_WALKTHROUGH_ZH.md) 可追溯到题单、案例和结果。 |
| 英文 IEEE LaTeX、真实引用、PDF 与结果一致 | 通过 | [LaTeX 正文](../paper/main.tex)、[参考文献](../paper/references.bib) 和 [5 页 PDF](../paper/report.pdf)。逐页检查标题、流程图、统计表和参考文献。四个核心测试通过。 |
| Overleaf ZIP 解压编译、私有仓库 | 通过 | [ZIP](../deliverables/overleaf_project.zip) 含 6 个源文件，根目录为 `main.tex`，实际从解压内容编译。已核验 [新私有 GitHub 仓库](https://github.com/Lmy0415/dase7506-agent-harness-clean) 的 `main` 收到交付提交 `4acde9ff8098`。 |
| 作者、课程提交与授权费用 | 通过 | 作者姓名、学号和单位已标为待补，学生确认课程系统的提交时间。峰价上界加未结预留共 1.508799012 美元，低于 10 美元。 |

运行 `python -m pytest -q tests` 可重检核心逻辑。完整复算、论文编译和 Overleaf 上传见 [README](../README.md)。

## Harness V4 最终核对

| 验收项 | 状态 | 证据 |
| --- | --- | --- |
| 原批次完整保留与追加题单先冻结 | 通过 | 原 12 个冻结文件哈希匹配，原 32 题题单和结果与 `41cdd22` 一致。追加题单覆盖 8 个新家族，四组 32/32 条齐全。两批无交集。 |
| 试跑隔离、失败记录及冻结 | 通过 | 8 个 pilot 家族与正式集无交集。首轮 24 条，确认 16 条。正式 763 的网络错误尝试留档，单独恢复后有评分。 |
| 同起点、同模型、同评分 | 通过 | 40 个 checkpoint 的数据库和对话指纹逐项核对。新增 120 条从对应原起点恢复，每题每分支最多 24 次调用、每次最多 512 输出 token。所有回执为同一 model 标识与服务指纹。 |
| R、C+、C++ 无裁判输入 | 通过 | 新策略只使用用户消息、可见对话、旧计划和可见工具回执。隔离核验、官方修订全文及评分标注不会进入新策略。8 项离线测试通过，实测 pilot 控制拦截前后状态指纹一致。 |
| 实测结果与范围披露 | 通过 | [正式分支表](../results/harness_v4/branch_metrics.csv) 280/280 评分。[配对表](../results/harness_v4/paired.csv) 含批次、Swap/Drop 分层和同任务族区间。D 独立参照。[拦截审计](../results/harness_v4/guard_audit.csv) 记录正式 0 次拦截，误拦率无可判定分母。 |
| 案例和中文说明 | 通过 | [案例索引](../results/harness_v4/case_index.csv) 对应 3 条正式轨迹和 1 条独立 pilot 控制。[中文说明](PROJECT_WALKTHROUGH_ZH.md) 逐题解释结果及其局限。 |
| IEEE 论文、结果和 ZIP | 通过 | [LaTeX](../paper/main.tex)、[PDF](../paper/report.pdf)、[Overleaf ZIP](../deliverables/overleaf_project.zip)。ZIP 的 8 个成员实际解包编译，逐页查看 6 页 PDF，表格与脱敏数据重建一致。 |
| 费用和作者信息 | 通过 | [累计账本汇总](../results/harness_v4/budget.json) 含 4,062 条回执，加未结预留占用上界 2.770144776 美元，低于原 10 美元。作者姓名、学号及单位仍留给学生填写。 |

远端交付使用现有 [GitHub 仓库](https://github.com/Lmy0415/dase7506-agent-harness-clean)。提交前检查远端为 Private，并从 GitHub 核对主分支的提交。
