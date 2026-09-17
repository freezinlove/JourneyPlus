# 表格权威与费用状态修复

## 实施规则

- 程序已解析的映射行、地区、等级、价格、币种、可用性和原文证据保持不变。旧模型输出中的覆盖/清空指令仍可反序列化，但合并时不会执行。
- 模型可添加缺失行；已有路线仅允许填充空缺的资格说明/入口及新增目标等级价格。映射额外说明放在 caveats。已有表格与正文冲突时以表格为准。
- 新增行按地区别名和等级名称进行重复检查，部分重叠的地区仅补充未覆盖部分。无表格时仍允许模型从正文创建数据，确实无依据时可以为空。
- 程序未解析的正文继续提供给模型。检测到映射表但输出为空会进入原有重试流程，仍为空则阻止发布。
- 菲律宾表头支持 Airlines，以及 Matching Allowed & Selected 辅助列；不再把辅助列当等级。明确 No 的行不建立关系。
- 费用状态为 FREE / PAID / UNKNOWN；paid 对应 false / true / null。只有明确免费可通过 free_only。页面的 UNKNOWN 文案为“费用待核实”。
- 路径规则升级为 simple-matching-v2-fee-state，旧路径不能再次作为新展示引用；历史图显示旧版费用提示，原对话保留。

## 正式数据修复

脚本：scripts/repair_authoritative_tables.py。默认事务回滚预览，--apply 发布新版本。不调用模型、不重写历史事实、原始网页或旧分析记录。

- Flying Blue：当前 FactSet 3d8d694f-9e71-40c9-8295-08b4b9838dc0，版本 9，恢复 10 项明确金额。原始页面为数据库保存的 FAQ/条款快照，并非本次重新采集。
- 菲律宾 Mabuhay Miles：当前 FactSet 1d10d044-c9b4-46dc-bc1d-7c1f74f0c36f，版本 2，164 条映射、4 项地区价格。
- 重新执行脚本预览时两者 current ID 保持不变，未产生新的事实版本。
- 正式知识读取接口的数据结构中 Flying Blue fee.status=PAID，希腊 Gold=199 EUR、Platinum=349 EUR；菲律宾可见 Senator → Premier Elite。
- 直接执行正式库路径查询：Senator → Flying Blue Gold 为 PAID；Senator → Mabuhay Miles PREMIER ELITE 为 PAID；free_only 仅返回 Club Avolta Gold。

## 验证

相关后端回归共 170 项通过（核心 144 项、候选/知识路径 25 项、可选费用未知状态新增 1 项）；浏览器 8 项通过（包括免费、付费、未知标签和图文阅读顺序）；TypeScript/Vite 生产构建通过。

额外检查 test_agent_route_recall.py 发现 4 项已有失败：3 项依赖旧 sections 输出结构，1 项使用缺少 paid/节点身份的旧路线夹具。将本次修改的相关模块在独立 Python 进程内替换成 HEAD 版本后仍复现这 4 项失败。没有为本次修复改写这些旧测试或归档逻辑。

改动保留在工作区，未创建 Git 提交。
