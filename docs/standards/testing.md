# 验证与渐进采用

本地执行：

```powershell
uv run --python 3.12 --no-project python scripts/check-provider-architecture.py
uv run --python 3.12 --no-project python -m unittest discover -s templates/provider/tests -v
uv build templates/provider --out-dir templates/provider/dist
```

CI 执行相同的架构检查、CPU/Fake Modal 测试、wheel/sdist 构建及 wheel 安装后测试。测试覆盖重复模型、未知模型、请求边界、能力/部署对应、入口存在、禁用依赖、哈希/大小/角色、远程入口验证和包导入。Fake Modal 不代替真实部署验收。

架构脚本默认严格检查模板；--provider-dir 与 --package 用于检查新增标准 Provider。基于 AST 检查依赖，之后仅导入公共元数据交叉验证。AST 是回归门禁，不是任意 Python 的隔离沙箱；动态导入与网络副作用仍需审查。

现有 2D、3D、World 暂不声明 v1 合规：2D specs/registry 尚在 models.py；3D 有操作型旧模型标识与根层 Worker；World registry 是 backend factory registry，不能冒充模型注册表。现有 runtime architecture gate 和各包测试继续执行。先新增兼容接口及权威注册表，再逐包启用严格门禁，不大规模挪目录、不自动修改 ID。

迁移验收必须运行原有 CPU/Fake Modal 测试、Hub 插件发现/打包测试以及旧部署入口测试。规范变更需说明兼容影响并升级版本；目录例外要文档化。
