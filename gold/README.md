# 人工金标

第一版金标使用 `GoldDataset` JSON Schema，覆盖文章相关性、事件关系或分组、关键事实和证据定位。具体文章由用户后续提供并共同标注；本目录不预置虚构案例，也不设上线阈值。

对比已经导出的当前与候选结果：

```bash
uv run journeyplus-eval gold.json \
  --prediction current=current-output.json \
  --prediction candidate=candidate-output.json
```

每次修订案例时递增案例 `version`，整套集合发布时递增 `dataset_version`。
