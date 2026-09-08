# Ollama Qwen3 Embedding 检索评测

评测时间：2026-08-26

## 环境

- 设备：Apple M4 Mac mini，16GB 内存。
- Ollama：0.33.0，Homebrew 后台服务。
- 模型：`qwen3-embedding:0.6b`，Q8_0，639MB。
- 向量：1024 维，PGVector cosine distance，HNSW 索引。
- 查询格式：`Instruct: ...\nQuery: ...`；文档保持原文。

## 数据集

- 5 份中文旅行测试文档：成都、杭州、北京、西安、重庆。
- 10 个有明确目标文档的旅行检索问题。
- 3 个与旅行知识库无关的域外问题。
- 每次评测临时入库并发布，结束后自动删除全部评测记录。

## 结果

| 指标 | 结果 |
|---|---:|
| 文档入库耗时 | 2.395s |
| Hit@1 | 100.0% |
| Hit@3 | 100.0% |
| 正例相似度范围 | 0.4626–0.6934 |
| 域外问题最高相似度 | 0.1729 |
| 平均查询延迟 | 62.9ms |

模型成功返回 1024 维向量并写入现有 `VECTOR(1024)` 字段，证明 Ollama、Qwen3 Embedding、PostgreSQL 和 PGVector 的真实链路兼容。

## 阈值结论

评测数据给出的正负分数分界中点约为 0.32。项目初始使用 `RAG_SIMILARITY_THRESHOLD=0.35`：高于当前域外问题上限，并保留全部已测正例。

该阈值不是生产环境最终值。上线前应使用至少 50–100 个真实旅行问题，覆盖同城相似景点、跨城市同类问题、时效问题和模糊表达，再按知识缺口率、误召回率和引用准确率校准。

## 复现

```bash
source .venv/bin/activate
python scripts/evaluate_rag.py
```
