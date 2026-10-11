# 产物

内部 ArtifactSpec MUST 描述 role、media_type、sha256、size_bytes；使用 frozen dataclass。sha256 为内容的 64 位小写十六进制 SHA-256，size_bytes 为非负整数（拒绝 bool）。读取后必须核对内容长度及哈希，role/MIME 必须与 Capability 声明匹配。

primary-image/image/png、primary-glb/model/gltf-binary 等已有角色保持稳定；World 可以产生多种角色。新角色必须在该 Provider 能力及产物允许表登记，不应把模板角色作为所有 Provider 的全局白名单。

远程 Volume 和路径是 Provider 私有定位信息，不是公共 Artifact 身份；外部身份由现有 Job/Artifact 协议提供。对外 camelCase 字段通过兼容映射处理，不强制修改现有契约。模板的 primary-text/text/plain 是独立 CPU 示例。
