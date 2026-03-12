# Work Log

## 2026-03-12

### 基线搭建

- 新建 `gr2_sim` 目录，作为正式贡献边界。
- 抽出 `skill.py / gr2_controller.py / sim_app.py / config.py`，形成 RoboOS 到 Isaac Sim 的最小桥接版。
- 暴露 `connect_robot / disconnect_robot / get_joint_state / list_named_poses / move_named_pose / move_joints`。

### 配置整理

- 默认从 `config.yaml` 读取运行配置。
- 保留环境变量作为覆盖层，不再要求团队成员改源码路径。
- 项目名从 `gr2_isaaclab` 收敛为 `gr2_sim`。

### RoboOS 联通

- 已完成本地 smoke test，证明 MCP tool 调用链路可用。
- 记录过一次真实阻塞：`Redis 127.0.0.1:6379` 未启动会导致 `RoboOS slaver` 无法注册监听。

### 场景稳定性修复

- 对比 `scene_bottle/load_gr2.py` 的稳定落地逻辑，确认 fixed USD 直接打开后机器人初始会与 ground plane 重合。
- 新增按包围盒自动贴地逻辑，避免继续硬编码 `z=1.0`。
- fixed USD 为 stage 型资产时，跳过无意义的 reference 加载尝试，直接走 open-stage fallback。

### 启动流程修复

- 发现有头模式下一次“GUI 闪退”并非物理再次崩溃，而是 `0.0.0.0:8000` 已被旧的 `python skill.py` 占用。
- 在 `skill.py` 中新增服务端口预检查。
- 后续若端口冲突，会在 Isaac runtime 预加载前直接报错，避免窗口先打开再退出。
- 将端口冲突输出改为单行 `startup_error=...`，避免团队成员被 traceback 干扰判断。

### 当前已知现象

- `omni.fabric.plugin getAttributeCount/getTypes called on non-existent path ...` 目前仍会出现。
- 这些 warning 当前更像资产/渲染层噪声，已知不会阻止机器人贴地站稳。
- 如果后续影响控制稳定性，再单独清理 fixed USD 的 mesh/collision 引用。

### RoboOS 任务链路补充

- `deploy` 只是部署与网页入口，不负责直接把自然语言变成机器人动作。
- 真正的自然语言执行链路是：
  `release 页面 / HTTP 请求 -> master:5000 -> Redis -> slaver -> MCP skill -> Isaac Sim`
- 按当前 `master/config.yaml` 和 `slaver/config.yaml`，`master` 与 `slaver` 都默认依赖 `http://127.0.0.1:4567/v1/` 的模型服务。
- 这意味着如果想输入“动一下右胳膊”并自动触发 `move_joints`，至少需要同时具备：
  - `gr2_sim` skill 服务
  - Redis
  - RoboOS master
  - RoboOS slaver
  - 模型服务（本地 RoboBrain/vLLM，或改成别的可兼容 OpenAI API 的服务）

### 2026-03-12 联调结论

- 已使用 `/home/fmc3/hf_models/RoboBrain2.0-3B` 跑通当前本机的最小自然语言链路。
- 已验证请求：
  - `请让 gr2_sim 动一下右胳膊。`
- 当前实际生效链路：
  - `master` 将任务压缩为单个子任务 `Raise the right arm of gr2_sim a little.`
  - `slaver` 选择 `move_named_pose`
  - skill 实际执行 `move_named_pose(name=\"right_arm_up\")`
- skill 侧返回了有效执行结果，包含：
  - `message: Completed named pose right_arm_up.`
  - `commanded_joints.right_shoulder_pitch_joint`
  - `commanded_joints.right_shoulder_roll_joint`
  - `commanded_joints.right_elbow_pitch_joint`

### 为联调加入的兼容改动

- `RoboBrain2.0/inference.py`
  - 增加 master 侧简单任务分解 heuristic
  - 增加 slaver 侧中文/英文动作意图到 tool/args 的映射
- `gr2_sim/gr2_controller.py`
  - 增加 `right_arm_up` 和 `left_arm_up` named pose
  - motion/state 调用支持按需自动连接，不再强制用户先显式 `connect_robot`

### 当前残留问题

- `slaver` 的历史 `Completed Actions` 会带上之前失败的旧记录，日志显得偏脏，但不影响当前成功执行。
- `master` 侧目前看到同一条 `gr2_sim_to_RoboOS` 结果消息重复打印，后续需要单独确认是否为 Redis 订阅或结果处理重复。
- `omni.fabric.plugin` 相关 warning 仍然存在，但已知不阻止当前动作基线。

### 交付文档整理

- `README.md` 已吸收原 `RUNBOOK.md` 的启动与联调内容，作为单一入口文档。
- `RUNBOOK.md` 现保留为轻量跳转页，避免旧链接失效。
- `CLAUDE.md` 已更新为当前真实交付边界和联调状态，而不是早期规划态描述。
- 新增 `gr2_sim/.gitignore`，避免将 `__pycache__` 和本地 `results/` 误提交到仓库。

### 仓库交付

- 已按当前基线整理提交边界，仅纳入：
  - `projects/RoboSkill/fmc3-robotics/gr2_sim`
  - `projects/RoboBrain2.0/inference.py`
  - `projects/RoboOS/master/config.yaml`
  - `projects/RoboOS/slaver/config.yaml`
- 明确不将 `scene_bottle` 一并提交，保持 playground 与正式贡献边界分离。
