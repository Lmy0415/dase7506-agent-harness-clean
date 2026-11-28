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

## V5 最后一轮

| 验收项 | 状态 | 复核证据 |
| --- | --- | --- |
| 保留历史与冻结输入 | 通过 | 原 V3/V4 设置、题单和逐题表与历史提交一致。40 份原快照和 9 份新快照验证数据库与上下文哈希，任务族之间无交叉。 |
| 离线和无答案泄漏 | 通过 | [解析诊断](V5_DIAGNOSIS_ZH.md)、[字段审计](../results/harness_v5/guard_feature_audit.json)。预测与标签合并是不同进程；隔离不依赖操作系统权限沙箱。18 项测试通过。 |
| Guard 门槛、pilot 与正式 | 通过 | [首轮误判及修复后的指标](../results/harness_v5/guard_offline_metrics.csv)、[真实模拟器控制](../results/harness_v5/guard_simulator_control.json)、独立 pilot 16/16、正式 405/405。新 C5/G5 共 98 条参与正式配对，共享同一状态生成。全部核对 512 token 和 24 次调用上限。 |
| 分批分析和评分审计 | 通过 | [正式逐题](../results/harness_v5/branch_metrics.csv)、[配对区间](../results/harness_v5/paired.csv)、[独立评分审计](V5_EVALUATOR_AUDIT_ZH.md)。新族另报告。45 条终态做了独立复评，原分保持冻结。第 845 题的 5 条导入错误从原终态恢复，断言没变。 |
| 论文、中文说明和复算入口 | 通过 | [LaTeX](../paper/main.tex)、[6 页 PDF](../paper/report.pdf)、[Overleaf ZIP](../deliverables/overleaf_project.zip)、[中文说明](PROJECT_WALKTHROUGH_ZH.md)、[复算命令](../README.md)。ZIP 的 8 个成员实际解包编译并逐页核对。 |
| 费用、作者和远端 | 通过 | [费用账本汇总](../results/harness_v5/budget.json) 记录 5,591 个回执；含未结预留上界 3.775490670 USD，低于 10 USD。作者姓名、学号和单位保留待填。交付到现有 Private 仓库，保持其可见性。 |

## PACT 独立补充

| 验收项 | 证据 |
| --- | --- |
| 历史结果封存 | V3–V5 原有 405 条正式记录及配置保持原样。V5 论文和交付附件保留在历史提交。 |
| 真实提交边界及选样 | [题单](../protocol/pact_manifest.json) 固定 12 个历史家族和 2 个独立 pilot。14 个 POST 实际执行恰好一次，有 2xx 与真实状态变化，期间零模型调用。[边界核验](../results/pact/boundary_checks.csv)。 |
| 真实门禁与同样资源 | [组件控制](../results/pact/component_control.json) 在两边验证拒绝未提交，足够的独立请求能实际写入。[冻结设置](../protocol/pact_settings.json) 记录同一指纹、24 次调用、512 token 和两个费用封顶。 |
| 有限 pilot 与原分保留 | [首轮](../results/pact/pilot_first.csv) 12/12，唯一确认轮 12/12。[正式分支](../results/pact/branch_metrics.csv) 72/72。两轮及全部正式都统一记账。 |
| 独立评分与分层结果 | [分母和指标](../results/pact/summary.csv)、[配对结果](../results/pact/paired.csv)、[通信复核](../results/pact/blind_review.csv)、[引用敏感性](../results/pact/reference_sensitivity.csv)。主分按预冻结评分，独立审计单列。 |
| 论文与作者信息 | [LaTeX](../paper/main.tex)、[PDF](../paper/report.pdf)、[Overleaf 工程](../deliverables/overleaf_project.zip)、[中文研究说明](PACT_WALKTHROUGH_ZH.md)。作者姓名、学号及单位保留占位。 |
| 费用与交付 | [费用账本](../results/pact/budget.json) 核对 PACT 占用上界 0.372737148 USD 与项目 4.148227818 USD。通过只读仓库元数据和文件树核对 Private `main`。 |

## 最终论文审稿与本地交付（2026-11-28）

| 验收项 | 本次改动与理由 |
| --- | --- |
| 研究问题与样本口径 | 保留原题名。引言从状态校验降低回退但未改善严格成功率的历史发现出发，引出提交状态怎样改变正确处置，再列出三项贡献。全文区分 49 个独立任务族、405 条历史分支和 72 条 PACT 分支。PACT 复用其中 12 个任务族。 |
| 控制器与实验解释 | 加入 Pause、Assess、Classify、Triage 的单栏伪代码。说明 PACT 可以由程序直接报告并请示，比较涵盖完整系统，未单独测量自动化、门禁或模型推理各自的影响。 |
| 核心结果图与统计 | 直接读取冻结 [summary.csv](../results/pact/summary.csv) 核对六个分子分母。图中叠放不同形状的重合点，灰度下也能辨认。由逐题数据复算 5 胜、0 负及双侧精确 McNemar (p=0.0625)，同时报告 95% 家族 bootstrap 区间 [16.7, 66.7] 个百分点，说明精确检验未达到 0.05 阈值。保留替代引用敏感性结果 A/P/PACT 为 3/12、3/12、7/12。 |
| 负面证据与限制 | 保留 POST 独立工作完成率、第 300 题多加椅子的失败、三组 POST 未观测到未经授权补救、优先级仅一个正式家族，以及单模型、小样本和无用户回复。 |
| 引文 | 用 arXiv v2 核对 ImpasseBench 的六位作者。从该条目移除 Jiasheng Liu，补充 Rao 与 Georgeff 的 BDI 会议文献和 Schut 等的卷期、页码与 DOI。 [arXiv v2](https://arxiv.org/abs/2610.31895v2) · [BDI 会议原文](https://cdn.aaai.org/ICMAS/1995/ICMAS95-042.pdf) · [意图重审期刊记录](https://research.vu.nl/en/publications/the-theory-and-practice-of-intention-reconsideration/) |
| 论文与附件 | [LaTeX](../paper/main.tex)；[6 页 PDF](../paper/report.pdf)；[Overleaf ZIP](../deliverables/overleaf_project.zip)。ZIP 的 10 个成员与交付源码和图片一致，已从干净目录解包编译。逐页检查双栏和三张图。单独交付 [矢量图](../paper/figures/commitment_arr.pdf)、[600 dpi PNG](../paper/figures/commitment_arr.png) 和 [绘图脚本](../scripts/plot_commitment_arr.py)。 |
| 冻结与待填 | Harness、评分规则、冻结设置、历史结果和 API 账本一致，本轮模型调用为 0。修订成果在本地，GitHub 可见性保持 Private。作者姓名、学号和单位保留占位，待学生填写。 |

## 最终归档与提交准备（2026-11-28）

**项目状态：研究与工程交付完成，等待学生填写作者信息及正式课程提交。**

| 项目 | 最终验收证据 |
| --- | --- |
| AI Disclosure | [课程公告](../COURSE_REQUIREMENTS.md)未列出专用模板。英文声明位于 Conclusion 之后、References 之前，列明 ChatGPT 和 OpenAI Codex 对研究设计、实现、分析和写作的贡献，说明 DeepSeek Flash 为实际受评估的模型。 [论文源码](../paper/main.tex) |
| 正式样本与分支 | 49 个独立正式任务族。405 条历史分支加上 72 条 PACT 分支，共 477 条。PACT 的 12 个任务族均从历史样本中复用。 [历史逐分支记录](../results/harness_v5/branch_metrics.csv) · [PACT 逐分支记录](../results/pact/branch_metrics.csv) |
| 测试及费用 | 已有 27 项测试通过记录。累计 API 预算占用上界 4.148227818 USD，授权总上限 10 USD。归档没有新增模型调用。 [费用账本](../results/pact/budget.json) |
| 主要研究发现与局限 | 容错减少了结构回退，严格成功率持平。PACT 在本样本 POST 的 ARR 高于流程提示基线，同时完成的独立工作更少。样本复用、单模型和无用户回复限制了结论。 [中文项目说明](PROJECT_WALKTHROUGH_ZH.md) · [中文 PACT 研究说明](PACT_WALKTHROUGH_ZH.md) |
| 论文及 Overleaf | [6 页 PDF](../paper/report.pdf) · [LaTeX](../paper/main.tex) · [Overleaf ZIP](../deliverables/overleaf_project.zip)。10 个 ZIP 成员含完整源码、参考文献、生成表格与矢量图，从干净目录解包编译，核对了声明、分页和图表。 |
| 数据和复现入口 | [项目 README](../README.md) · [表格渲染脚本](../scripts/render_pact.py) · [构建脚本](../scripts/build_paper.py) · [核心矢量图](../paper/figures/commitment_arr.pdf) · [600 dpi PNG](../paper/figures/commitment_arr.png) · [绘图脚本](../scripts/plot_commitment_arr.py) |
| GitHub 交付 | 最终归档提交通过快进同步到 Private `main`。本地和远端保留历史，核对两端最新提交 SHA 与文件树。 [GitHub main](https://github.com/Lmy0415/dase7506-agent-harness-clean/tree/main) |
| 学生提交 | 在源码填入真实姓名、学号和单位后重新编译，核对课程系统内的提交要求和可能的额外 AI 声明表单，由学生正式上传。 |
