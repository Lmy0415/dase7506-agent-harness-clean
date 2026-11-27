# PACT 相关工作核对

- InterventionBench 在运行中注入改口，用 AppWorld 和 WebArena 测目标变更。本研究复用其 AppWorld 前缀，追加真实提交前后的同题配对。 [Lee 等，Findings of EMNLP 2026](https://aclanthology.org/2026.findings-emnlp.698/)
- DynaRev 按网页任务的语义里程碑注入改口，并分析保留浏览器状态的指令重写。PACT 进一步固定一个具体工具请求，只改变它是否实际提交。 [Zhang 等，arXiv:2610.40133](https://arxiv.org/abs/2610.40133)
- Revision Absorber 从可逆性和补偿成本出发回滚冲突执行。PACT 把用户是否授权补救作为单独条件，在未回复时继续独立工作。 [Zhai、Li 和 Wang，arXiv:2604.23283](https://arxiv.org/abs/2604.23283)
- AgentAbstain 用应执行与应停止的配对任务测适当弃权，ImpasseBench 用证据充分的时间点衡量何时升级给人。PACT 的配对改动是同一操作是否已提交，另外观察部分工作停止时其他授权事项能否继续。 [Liu 等，arXiv:2607.10059](https://arxiv.org/abs/2607.10059) · [Chen 等，arXiv:2610.31895](https://arxiv.org/abs/2610.31895)
- BDI 的意图重新考虑研究早已关注何时重审承诺。这里的贡献是具体的提交边界、处置指标和执行门禁比较。软件只调度显式优先级和依赖。 [Schut、Wooldridge 和 Parsons，JAETI 2004](https://www.cs.ox.ac.uk/people/michael.wooldridge/pubs/jetai2004.pdf)
