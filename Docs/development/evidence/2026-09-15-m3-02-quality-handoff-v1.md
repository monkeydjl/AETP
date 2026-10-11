# M3-02 Task 质量迁移 v1 候选交接

- 工作项 M3-02 仍 in_progress；本批 pending_review。执行者 /root，独立 reviewer 只复用 /root/m1_reviewer。未使用 ClaudeLink、新代理或 Git/安装/网络/全局配置动作。
- 写集：新增 src/aetp/quality/、tests/m3/quality* 与 test_task_quality*；共享修改为 domain/models.py、core/commands.py、core/projection.py、governance/contracts.py、acceptance/records.py、runtime/service.py、runtime/projection.py、collaboration/service.py；另有本批设计、计划、证据、示例、backlog/status/MEMORY。精确输入见 snapshot。
- 规则：enroll/rework 固定工作 revision；真实 document.write 的完整成果集合进入正式轮次。Review 不取得作者 Lease；Verification 使用指定同行的独立 QA Task。证据先全量收集再判定适用性，保留原始结果与逐次使用记录。
- 完成：当前 human_owner 明确声明这个具体 Task 的 standalone_fixed_json_document 范围，仍需显式 LOW/auto Governance 许可与新证据检查。系统未自动识别真实集成需求。先 task.integration_exempted 保持 VERIFIED，再 task.completed 退役 Lease/Binding；第二 reducer 消费首事实预验证的续接证明。
- 实际修复：旧 requeue 曾能把 COMPLETED/CANCELLED 恢复为 pending；新增终止态守卫覆盖入口与纯 reducer。回放回执曾允许无效摘要、拒绝事实缺错误码；新质量游标已拒绝。所有 RED 与非零输出保留。首批 M3-02-R1 过时注释已在本批更正，旧门保持关闭。
- 作者功能验证：M3 209、M2 167、M1 85、M0 156，共 617 方法；compile 退出 0。准备 27 项及 render/check 由冻结报告引用实际结果；准备检查不计完整 Conformance。
- 示例 artifacts/m3-02-quality-demo-v1.json/.md：125 Events / 59 Commands；结果丢失恢复 INCONCLUSIVE → block/rework → FAILED/REJECTED → rework → PASSED/VERIFIED → 显式豁免 COMPLETED。两库 250 前缀；旧 8 库 530 前缀均只读重放一致，29 个执行/I/O 守卫零调用，库字节保持。
- 原始命令、cwd、起止时刻、退出码与输入 blobs：2026-09-15-m3-02-quality-development.jsonl 和 quality-runs/。submission_green_v1、review_evidence_green_v1 的夹具问题另行披露，不能改写成产品 RED；终态/回放失败为实际产品回归。
- 基线 .tmp/m3-q-base/ 保留 498 文件、7 pins、首批 418 冻结输入；MEMORY 只追加。历史首批报告永久保留 pending，由独立报告另行接受。新候选也不可回写为 accepted。
- 独立复现：PYTHONPATH=src；python -m unittest discover -s tests/m3 -t . -v；其他 suites 与准备命令见固定报告。作者审计入口为 2026-09-15-m3-02-quality-audit.py。独立运行必须在隔离副本，不更改主候选。
- 四项本批条件：正式加入与提交/独立质量阶段；版本化证据适用性/不升级历史；具体 Task 显式豁免/终态退役；回滚、幂等、竞争、因果与新旧纯 Replay。正式 reviewer 结论尚待生成。
- 未覆盖：真实 git.merge/分支保护/commit 系统验证、Mission 逐条验收与 human_owner Approval、Bootstrap、真实模型调用与费用、TEST-028 自主交付、通用 OS sandbox、待审后完全脱离作者 Session 的权限模型。
- 状态保持 19 done / 1 in_progress；phase preparation、product completion 0、Bootstrap not_started、完整 Conformance 28 registered / 0 passed、完整 M1 not_accepted。M3-02 原三个条件未缩减。
- 下一步：原 reviewer 对固定候选独立复核；有阻断先归档另冻新版本，无阻断后消费真实报告并收尾。本批之后仍需真实 Integration、Mission Acceptance 与平等 Agent 自主交付。
