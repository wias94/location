# 持久化历史

历史库 `history.sqlite` 与 STATE_PATH 同目录；当前 Docker 设置为 `/data/history.sqlite`，使用现有 `/data` 持久卷。

`records` 表保存 gzip 压缩的 UTF-8 JSON：

- `locations`：每个实际时间 5 分钟区间首次成功检查时，全员位置及状态；包含实际记录时间和模拟时间。不是逐秒轨迹，期间发生的短暂移动可能不在采样中。
- `daily`：America/Toronto 每日首次成功检查时的全员人物资料、持久状态、模拟状态。
- `state`：每次保存时保留有变化的状态版本，包含配置、互动、人物覆盖等；A→B→A 会保留三次状态，相同状态不重复写入。

后台每 30 秒检查一次，失败会记日志并重试。首次运行即开始采样；重启后相同区间/日期不会重复。模拟暂停或回拨不影响实际时间去重。

旧轨迹无法恢复，停机期间不补造轨迹。无自动清理，磁盘占用会持续增长。持久卷不等于异机备份。

只读导出一日位置记录（日期过滤按 UTC recorded_at；每日快照键按 Toronto 日期）：

```python
import gzip, json, sqlite3
with sqlite3.connect('file:/data/history.sqlite?mode=ro', uri=True) as db:
    for timestamp, payload in db.execute(
        "SELECT recorded_at,payload FROM records WHERE kind='locations' AND recorded_at>=? AND recorded_at<? ORDER BY id",
        ('2026-09-05T00:00:00', '2026-09-06T00:00:00')):
        record = json.loads(gzip.decompress(payload))
        # 按人物 ID 筛选 record['people']，或导出到管理员本地文件。
```

没有公开历史查询接口；通过管理员本地访问历史库。
