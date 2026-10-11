# 可运行 Provider 示例

CPU Echo 模型验证声明、注册、业务执行、远程入口和产物完整性，无权重或凭证要求。它不是 GPU 模型或完整 Hub 插件。

从仓库根目录运行 docs/standards/testing.md 中命令。测试注入 Fake Modal；实际部署需安装本包 modal extra，然后单独执行 `modal deploy -m modal_example.workers.echo`。导入元数据不需要 Modal。示例不定义 submit/poll/cancel 的伪生产语义。

复制后替换包名、provider/model/operation ID，配置 ModelSpec 和权重，实现领域 Worker，再对接现有 Hub 协议。保留 registry 为唯一模型来源。
