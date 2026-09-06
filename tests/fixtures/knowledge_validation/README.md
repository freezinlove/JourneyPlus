# 公开事实回归快照

固定于 2026-09-06，SHA-256：`748965526b6e076dca6007dfb052225e9b94a279fbad5dc5931f759f73a8423e`。

来自隔离验证库的公开活动事实，共 9 条路线与 5 个活动卡。查询起点 Air Canada Aeroplan Elite 50K 是合成测试假设，明确关闭 use_saved_holdings；不导出已保存会籍、会话、邮件内容、访问凭证或 StatusMatcher 报告。数据库标识替换为本夹具局部引用，不保存反向映射。资料的原抓取日期随 sources 保留，不能将旧快照当成当前有效报价或正式库种子。

- 同一 Gold Sparrow 的 USD149 不能替换成 Silver USD49。
- 直达与中转 Avolta 路径保持不同步骤；已知收费不变免费。
- Radisson 余下费用未知不能因已知项为零而成为免费。
- Enrich 费用适用性待核实、Flying Blue 区域与币种分开。
- 自由输入／经验许可的复现与重放关联见快照 defects 及工作区开发评测集。

`tests/test_public_validation_snapshot.py` 验证事实范围和局部引用完整性。需要换基线时先审核事实与脱敏，再使用 `scripts/export_validation_snapshot.py`，同步审阅本摘要与哈希。冻结会话保留集独立管理，不因刷新此快照而变化。
