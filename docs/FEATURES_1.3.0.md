# 1.3.0 功能规划 · 完善 1.2 遗留

> 1.2 系列做完后，按「用户能感知」排出的优先级：
> P1 多屏每屏独立数量/缩放 · P2 跨屏移动策略 · P3 里程碑/养成持久化 ·
> P4 表达式运行时校验。
>
> 全部完成于 2026-11-06。

## P1 · 每屏独立数量与缩放 ✅

F5 最小切片只做了「允许/禁止去某块屏」。1.3 补齐：

- **每屏数量上限**：`monitor_settings[设备名].max_count`，`0`=继承全局。
  `summon_many` 现在按屏分配：先挑一个「还没满」的允许屏，落点夹到那屏
  work 区；**所有允许屏都满了就停止召唤**（每屏上限是真的上限，不兜底超上限）。
- **每屏缩放**：`monitor_settings[设备名].scale`，`0`=继承全局。
- 设置 → 显示器标签页：每屏一行「数量 / 缩放」spinbox，显示「继承」占位。
- 数据层：`Environment.monitor_max_count() / monitor_scale() /
  apply_monitor_settings()`；空/None 配置全部回退继承全局。

## P2 · 跨屏移动策略 ✅

- **允许屏之间自由跨**；宠物进入禁屏，下一帧 `_clamp_to_allowed` 拉回最近
  允许屏，不切动作、不改行为。
- **跨到新屏自动切换该屏 scale**：`_apply_scale_for_monitor` 记录上一次应用
  缩放的设备名，**只在设备变化时设 scale**。
  - ⭐ 踩坑：第一版每帧无条件 set 该屏 scale，结果 timer 在跑时
    `verify_mascot` 的「set_scale(2.0) 生效」立刻被下一帧重置回 1.0。
    修复后同一屏上重复检查不覆盖手动 scale。
- ⭐ 修了 F5 的一个**潜伏真 bug**：旧 `_clamp_to_allowed` 用
  `move_window_at(m._win, ...)`，但 `m._win` 不存在（Mascot 是 QWidget），
  且返回 tuple 被当 Pt 访问 `.x/.y`。异常被 `Manager.tick` 的 except 吞掉，
  单屏测试走不到、真实多屏上宠物根本拉不回来。改成设置锚点 +
  `m.reposition()`（锚点→窗口左上角的换算在 Mascot 里）。

测试：`verify_monitor_per_screen.py`（21 项），用临时两屏 monitor_info 模拟。

## P3 · 养成数值与里程碑持久化 ✅

⭐ **发现比里程碑更根本的洞**：`save_session` 原本只存位置/朝向/行为，
**四个养成数值根本没持久化** —— 用户重启后好感归零，单独做里程碑持久化没有
意义。

- `PetStatus.to_snapshot() / from_snapshot()`：四值（feeling/energy/health/
  likability）+ 已报过的里程碑（50/80/100）随会话存盘。
- 旧快照缺 `status` 字段时安全回退默认值。
- 恢复时**不触发** `on_state_changed/on_milestone`（恢复不是「刚养成」，不能
  开机刷台词）：`_state = state()` 直接对齐，不走 `cached_state()` 的通知。
- 50 里程碑说过后重启不再说；继续涨到 80 正常触发。

测试：`verify_status_persist.py`（12 项）。

## P4 · 表达式运行时试算 ✅

F6 只做编译期。1.3 加 `check_expression(raw, runtime=True)`：

- 对**纯常量/纯内置函数**表达式实际 eval 一次，能抓编译通过但运行时必炸的：
  `#{1/0}`、`#{Math.floor()}`（缺参）。
- **含环境变量的不试算**（workArea / mouseX / mascot…）：编辑器没有真实
  宠物/环境命名空间，硬试必然误报。用 AST 扫描 Name，不在安全集合就跳过。
- 设置页 custom.xml 校验改走 `runtime=True`。

测试：`verify_expr_validate.py` 扩到 32 项。

---

## 贯穿纪律

- 新断言都做了变异测试确认鉴别力（屏幕上限恒用全局、跨屏不切 scale 等）。
- 写死的「设置窗口 8 页」断言改成「页数不减少 / 切语言页数不变」——新增
  显示器页后不再误报，也符合「条目数不写死」的项目纪律。
- 全量回归 27 项全绿。
