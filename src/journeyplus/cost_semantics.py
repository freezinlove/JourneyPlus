"""Shared fee wording for producers and brief generation; no schema constraints."""

COST_EXTRACTION_RULES = """费用字段分工：application_routes.prices 保存明确的金额、币种、适用等级和
可用性，无论价格来自正文还是程序解析的表格。cost 和每条 route.cost 是可选费用说明：
已有结构化价格时，只补充 prices 未表达的退款规则、额外收费条件等信息，不再抄写价格清单、
生成价格区间或“费用因地区和等级而异”一类重复摘要；没有额外信息就保持 null。
某项费用尚不能结构化时，仍在对应范围的 cost 中保留材料明确说明的文字，不得因为其他路线
已有 prices 而丢弃它。未说明的金额或币种不得猜测。不同币种分别表达，不得合成一个价格区间。
旧事实中的 cost 仅供对照，不是本次费用摘要的模板；重新按当前材料及上述字段分工提取。
"""

COST_BRIEF_RULES = """费用文案直接读取各申请路径 prices 的金额、币种、适用等级和可用性；
cost/route.cost 是补充说明，或尚未结构化的费用文字。cost 为空不表示 prices 中的费用未知，
引用结构化价格使用 application_routes 这个 fact_key。已有 prices 与旧 cost 的价格摘要不一致时，
以对应路径 prices 为准，同时保留 cost 中未被 prices 表达的退款和额外收费条件。
不同币种分别表述，不得写成“从 EUR 89 到 USD 399”这样的跨币种区间；不同地区和等级不能混用。
CONDITIONAL 价格只适用于其条件，不能推广到全部申请人，也不能在没有明确总价时与基础费用相加；
UNAVAILABLE 不能描述成可付费申请。没有金额的路线仍按其自身信息表达，不从其他路线补猜。
"""
