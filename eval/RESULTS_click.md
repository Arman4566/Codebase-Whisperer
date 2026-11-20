# Retrieval evaluation

16 answerable + 4 unanswerable questions, k=5

| Retrieval mode | File Hit@k | Line Hit@k | MRR |
|---|---|---|---|
| bm25 | 69% | 56% | 0.349 |
| dense | 56% | 50% | 0.216 |
| hybrid | 94% | 88% | 0.658 |

**Abstain check** - correctly refused unanswerable: 3/4; wrongly refused answerable: 0/16

## Hybrid misses
- `How do I test a command line app with a runner?` expected [{'path': 'src/click/testing.py', 'lines': [341, 341]}] got ['tests/conftest.py:L6-L8', 'tests/test_basic.py:L819-L835', 'tests/test_formatting.py:L127-L147']
- `How are command groups implemented?` expected [{'path': 'src/click/core.py', 'lines': [1694, 1694]}] got ['src/click/core.py:L1836-L1837', 'src/click/core.py:L1839-L1842', 'src/click/core.py:L1844-L1883']
