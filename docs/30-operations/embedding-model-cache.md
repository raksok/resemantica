# Embedding Model Cache

The canonical glossary embedding model is `BAAI/bge-m3`.

`embedding/` is local runtime data and is ignored by Git. The first glossary discovery or alias clustering run may download the configured Hugging Face snapshot into `embedding/BAAI/bge-m3`.

To prefetch the model manually:

```powershell
uv run python scripts/download_embedding_model.py
```

Offline glossary runs work after `embedding/BAAI/bge-m3` exists locally. The legacy config value `bge-M3` is normalized to `BAAI/bge-m3` for compatibility.
