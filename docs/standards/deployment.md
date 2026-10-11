# DeploymentManifest v1

稳定入口 deployment_manifest() -> dict[str, object]，内容必须可 JSON 序列化。v1 新清单包含 schema_version=1、provider（非空稳定 ID）、targets（目标对象数组），可选 utilities（辅助部署目标）。未知扩展字段允许，但不可改变标准字段语义。

每个 target：app（唯一非空应用名）、module（可解析的 Python 模块）、kind（worker/pipeline/compiler/prefetch）、revision（非空代码版本）、models（模型 ID 数组）、weights（权重组数组）、secrets（Secret 名数组，绝不包含值）。工具目标可 models=[]。不同目标允许共享 models；代码 revision 使用提交号或源码摘要，权重 revision 放在 ModelSpec。

weight 对象：volume 为非空私有 Volume 名；requiredPaths 为相对 POSIX 路径数组，不接受绝对路径或 ..；prepare 为命令描述数组，每项有 module、function 和 arguments（字符串数组）。既有 requiredPaths 拼写保持兼容。显式 weightless=true 的目标必须 weights=[]。

每个目标 MUST 能单独部署。清单描述部署，不执行部署或下载；权重准备先于部署并可独立执行。前置条件只读检查，缺失即明确失败。prerequisites 可作为领域扩展保存 World 的 bundle 验证；不得默默替换成普通权重路径。

旧清单无 schema_version、省略 models/weights/secrets 或 prepare 依赖目标 module 时属于迁移状态，保留原消费方式；新增 v1 目标使用完整格式。清单校验及模块存在性检查不导入 Worker，不需要真实 Modal 凭证。旧入口重命名保留转发兼容。
