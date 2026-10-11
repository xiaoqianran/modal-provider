# 能力

list_capabilities() 是新 Provider 的公共入口，返回可序列化的能力序列。既有 capabilities_document() 等接口继续保留，迁移可以增加适配导出。

Capability MUST 有稳定 ID、契约版本、模型范围及输出角色/MIME。模型范围由 registry 构建；不可维护另一份模型清单。操作与能力的映射必须明确，多阶段模型不要求一对一 Worker。

已发布 Capability ID MUST 保持原值。例如 2D operation 是 modal-2d.image.text_to_image.v1，image.generate 是 kind；不得把 kind 当成迁移后的 operation ID。模板使用独立的 modal-example.text.echo.v1，无意替换生产接口。
