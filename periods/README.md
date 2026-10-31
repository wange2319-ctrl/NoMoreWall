# 两期订阅保留规则

- `current/`：最新一期。
- `previous/`：上一期，作为回退。
- 每次抓取前，`current/` 自动轮换为 `previous/`。
- 新一期生成后，旧 `previous/` 自动删除。
- GitHub Actions 会把仓库压缩为单次快照，不在版本历史中保留旧订阅。

固定使用仓库根目录的 `list.best.meta.yml`、`list.best.yml` 或 `list.best.txt` 即可。
