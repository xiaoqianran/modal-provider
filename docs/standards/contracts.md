# 请求与适配协议

公共入口为 validate_request()/normalize_request()，明确输入类型、未知字段策略、默认值、长度/数值范围和错误类型。规范化返回新值，不修改调用者输入。Worker 自行重复验证，不能只依赖客户端。

每个 Capability 声明 contract 版本。不兼容字段或语义变更必须升级契约并保留旧版适配；未知模型 KeyError，可预期输入错误 ValueError 或专用错误，执行失败单独报告。

生产 client/provider.py 遵循现有 Hub 协议：submit、poll、cancel、read_artifact 的签名、异步行为和任务状态以 Hub 实际协议为准，不能凭模板重新定义。模板仅提供 list_capabilities()/normalize_request() 及同步 run_example() 演示，不注册 modal_gen.providers 插件，也不声称实现 Hub 任务协议。接入时必须补齐真实协议的集成测试。
