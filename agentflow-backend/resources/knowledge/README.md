# Knowledge resources

运行时的知识库源文件不在仓库里，写入：

`agentflow-backend/data/resources/users/<owner>/knowledge/<kb_id>/`

目录结构：

```text
<kb_id>/
  manifest.json
  documents/<doc_id>.md
```

SQLite 仍然保存 chunk 索引，用于检索；这里的文件是可读、可备份、可迁移的源数据。仓库里的 `resources/` 只放内置工具和 MCP 代码包，不放用户上传的知识库内容。
