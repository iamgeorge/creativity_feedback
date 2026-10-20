# creativity_feedback

运行方式：

- 正式网站是 systemd 服务 `creativity-feedback`（gunicorn，端口 5555），开机自动启动，崩溃后自动重启；另有定时检查，每 2 分钟访问 `/healthz`，没有响应就重启。详见 `deploy/README.md`。
- 改了代码、模板或 `.env` 之后：`sudo systemctl restart creativity-feedback`。看日志：`sudo journalctl -u creativity-feedback -f`。
- 本地调试：`PORT=5556 python app.py`（5555 被服务占用）。测试：`python -m pytest tests -q`。
- 代码在 `creativity/` 包里（`config`、`storage`、`llm`、`scoring`、`auth`、`dashboard`、`routes/`）。

数据存储已经改为本地 CSV，不再依赖 MySQL。

- 提交到 `/store` 的数据会按用户组写入 `data/` 目录。
- 生成的文件名分别是 `control.csv`、`evaluative.csv`、`informative.csv`、`positive.csv`、`negative.csv`。
- 每个 CSV 都使用同一列结构：`user_id,time,type,question,answer,score,feedback,duration_seconds`。
- 每一行是一个事件（一个回答、一次绘图提交或一次心情评分），不是每人一行。
- 每个参与者另有自己的文件夹 `data/participants/<用户ID>/`：
  - `responses.csv`：这个人的所有行（列和分组 CSV 一样）
  - `drawings/`：这个人的绘图 PNG（`<题目>__<时间>.png`）。CSV 里绘图行的 `answer` 列就是图片路径。每次提交都会另存一张；时间到了还没提交的绘图也会保存（`type` 为 `drawing_unsubmitted`）。
- 第一次写入时，会自动把分组 CSV 里已有的旧数据按参与者整理到 `data/participants/`。
- `data/` 目录只在服务器上有一份，请定期备份（可在 dashboard 下载 “Everything (.zip)”）。

查看数据：

- `/dashboard` 可以按参与者查看回答、分数、反馈、绘图和心情评分。`/dashboard?user=C2` 直接打开某个参与者。
- 下载：每个参与者的数据 `/export/participant/<用户ID>.zip`，各组 CSV `/export/<组名>.csv`，全部数据 `/export/all.zip`（dashboard 上都有按钮）。
- 这些页面需要登录：在 `.env` 里设置 `DASHBOARD_USERNAME`（默认 `admin`）和 `DASHBOARD_PASSWORD`，浏览器会弹出登录框。没设置密码时页面会被锁住。

管理页面 `/admin`（和 dashboard 用同样的登录）：

- 创建参与者 ID（如 `C007`）和密码（只在创建时显示一次，可以重置）。也可以在这里添加/删除研究者账号。
- 数据样例和每列说明：`docs/data_collection_sample.xlsx`。
- 原来的说明：创建参与者 ID（如 `C007`）。一旦创建过 ID，只有这里创建的 ID 才能登录和保存数据。ID 列表在 `data/participant_ids.csv`。
- 每周下载并删除：先点 “Download Everything (.zip)”，确认压缩包能打开，再点 “Delete Data From Server”。只有在下载后 30 分钟内、且下载之后没有新数据时才能删除；ID 列表会保留。
- 多个研究者账号：在 `.env` 里设置 `DASHBOARD_USERS=名字:密码,名字:密码`。

密钥不要再写进代码。

- OpenAI 从服务端环境变量读取：`OPENAI_API_KEY`。
- OpenScoring 可选从服务端环境变量读取：`OPENSCORING_API_KEY`。
- 本地可参考 `.env.example`，实际使用的 `.env` 已加入忽略，不会进 git。
