# 架构

标准包包含 models/specs.py、models/registry.py、workers/、client/provider.py，以及 capabilities.py、contracts.py、deployment.py、artifacts.py。runtime/、operations/、pipelines/ 按需创建，不创建空抽象层。

依赖方向：specs → 标准库；registry → specs；contracts/artifacts → 标准库及纯数据契约；capabilities/deployment → registry；workers → registry/contracts/artifacts/runtime；client → 公共能力、契约、部署描述及传输适配器。箭头表示左侧可导入右侧。元数据层不得导入 workers、client、Modal、GPU 库或网络客户端。Worker 不得依赖 Hub 会话、用户状态、全局任务数据库或 client。pipeline 可组合 Worker，但元数据不可反向依赖 pipeline。

模型声明、注册、执行、部署是不同职责。纯元数据导入及清单验证 MUST 不需要 Modal 凭证、不请求网络、不加载权重、不初始化 GPU。部署模块可以读取本地代码计算 revision。

未来包路径变更 MUST 提供兼容导出、插件入口兼容和逐步弃用计划。先验证旧调用仍可工作，再改变内部目录。标准模板只是默认布局，已有布局不是本轮失败条件。
