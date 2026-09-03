"""本地控制台：FastAPI 后端 + 无构建静态前端。`guji console` 启动。

- jobs.py   任务队列：子进程跑 `python -m open_guji_cv pipeline …`，日志与记录落 runs/
- app.py    路由：注册表 / 状态 / 运行 / 产物 / 叠图 / 缓存图
- static/   index.html（总览 · 运行 · 产物 三个视图）
"""
