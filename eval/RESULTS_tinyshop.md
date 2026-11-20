# Retrieval evaluation

16 answerable + 4 unanswerable questions, k=5

| Retrieval mode | File Hit@k | Line Hit@k | MRR |
|---|---|---|---|
| bm25 | 94% | 94% | 0.708 |
| dense | 100% | 100% | 0.547 |
| hybrid | 94% | 94% | 0.812 |

**Abstain check** - correctly refused unanswerable: 4/4; wrongly refused answerable: 0/16

## Hybrid misses
- `What configuration options are there for payments retries?` expected [{'path': 'config.yaml'}] got ['docs/architecture.md:L14-L17', 'app/payments.py:L1-L3', 'app/payments.py:L17-L27']
