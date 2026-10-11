# 模型

ModelSpec MUST 是不可变元数据，默认 frozen dataclass + slots。最小语义包含 id、name、runtime、worker_app、operations 和明确的执行入口（worker_module、worker_class、业务方法、远程方法）。gpu 是字符串或纯数据资源描述，不包含 Modal SDK 对象。

新模型 ID 使用稳定 kebab-case（数字版本允许点，如 sana-sprint-1.6b）。现有 ID 不自动改名。权重仓库 hf_id、权重 revision、steps、guidance、batch、尺寸及领域参数按需保留；六字段示例不限制真实模型规格。代码 revision 与权重 revision 是不同概念。

Registry MUST 检查 ID 唯一并立即拒绝重复项，提供 get_model(model_id) 和 list_models()；未知 ID 抛 KeyError。返回不可变序列及只读映射。支持按模型族分文件，但公共查询入口保持唯一。ModelSpec 不下载、初始化或推理。

同一 Worker 可服务多个模型；同一模型可由多个部署阶段处理。新增模型应使能力和部署可从同一权威注册信息发现。
