# Worker

Worker MUST 负责加载模型、校验和规范化请求、执行领域操作、处理输出。不得管理 Hub 用户会话和全局任务数据库。GPU 加载只能发生在显式生命周期入口，不能发生在公共规格导入期间。

业务方法按领域命名：generate、reconstruct、segment、generate_mesh、compile_semantics。Modal 远程入口如 generate_job/run_job 保留已有命名；Registry 记录两者映射，不强制所有业务变成 generate。

远程入口 MUST 调用同样的请求校验与业务执行逻辑，并产生可验证产物。Worker 不能相信绕过 client 的直接调用。失败不能伪装成功；无效请求与运行失败应可区分。重命名模块、类、方法时保留旧部署入口兼容转发并测试。

模板的 EchoWorker 是 CPU 文本执行示例。Fake Modal 仅验证装饰入口和直接调用，不模拟云端调度、GPU、取消或 Volume 一致性。
