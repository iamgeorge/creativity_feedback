# creativity_feedback

数据存储已经改为本地 CSV，不再依赖 MySQL。

- 提交到 `/store` 的数据会按用户组写入 `data/` 目录。
- 生成的文件名分别是 `control.csv`、`evaluative.csv`、`informative.csv`、`positive.csv`、`negative.csv`。
- 每个 CSV 都使用同一列结构：`user_id,time,question,answer,feedback`。
