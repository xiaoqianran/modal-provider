# Modal Provider Standard v1

状态：新 Provider 的开发基线；现有 Provider 渐进采用。架构和接口 MUST 遵守；目录与私有命名 SHOULD 遵守，例外必须记录原因、兼容出口和验证方式。

目标：公开接口保持稳定，内部实现允许自由演进。第一版重点固定 ModelSpec、Registry、Worker、DeploymentManifest。规范不要求三类推理共享实现，也不要求立即移动生产代码。

- [架构](architecture.md)
- [模型](models.md)
- [Worker](workers.md)
- [能力](capabilities.md)
- [契约](contracts.md)
- [部署](deployment.md)
- [产物](artifacts.md)
- [测试与迁移](testing.md)

可运行参考：[templates/provider](../../templates/provider/README.md)。新增模型必须同步 registry、能力、部署及契约测试。
