# LruCache em Python

Cache LRU (least recently used) em Python puro, com `get` e `put` em O(1), TTL opcional por entrada e segurança para uso com várias threads. A estrutura é a combinação clássica de um dicionário com uma lista duplamente encadeada, implementada à mão em vez de usar `OrderedDict`, justamente para expor o mecanismo.

## Por que este projeto

"Implemente um cache LRU" (LeetCode 146) é uma das perguntas mais repetidas em entrevistas de big techs, e a variação com TTL e concorrência é o que separa a resposta decorada da de quem já operou um cache de verdade. Caches desse tipo estão na frente de bancos de dados, resolvedores de DNS, serviços de autenticação e CDNs; entender a política de despejo, o custo de cada operação e o que acontece sob contenção é conhecimento diário de quem trabalha com sistemas de backend.

## Recursos

- `get`, `put`, `delete`, `peek` (leitura sem alterar a recência), `get_or_set`, `clear`, `items`, `len` e `in`.
- Despejo do item menos recentemente usado quando a capacidade é atingida.
- TTL padrão do cache e TTL por chave, com expiração preguiçosa (verificada no acesso).
- `purge_expired()` para limpeza explícita.
- Estatísticas: acertos, erros, despejos e taxa de acerto.
- Segurança entre threads por meio de um `RLock`.
- Relógio injetável (padrão `time.monotonic`), o que permite testar o TTL sem `sleep`.

## Como executar

Requer Python 3.8 ou superior.

```python
from lru_cache import LRUCache

cache = LRUCache(capacity=2, default_ttl=60)
cache.put("a", 1)
cache.put("b", 2, ttl=5)     # TTL próprio
cache.get("a")               # 1; "a" passa a ser o mais recente
cache.put("c", 3)            # despeja "b", o menos recente
print(cache.stats())
```

Para ver o resultado rapidamente a partir da pasta do projeto:

```bash
python3 -c "from lru_cache import LRUCache; c=LRUCache(2); c.put('a',1); c.put('b',2); c.get('a'); c.put('c',3); print(list(c.items()), c.stats())"
```

## Como testar

```bash
python3 -m unittest -v
```

Os testes verificam a ordem de despejo, atualização de chaves existentes, capacidade 1, valores `None` e falsy, integridade da lista após centenas de operações, expiração com relógio falso, e um teste com cinco threads que checa os invariantes (tamanho, chaves únicas, valores corretos) ao final.

## Decisões de projeto

- **Dicionário + lista duplamente encadeada.** O dicionário localiza o nó em O(1); a lista mantém a ordem de uso e permite remover e mover um nó em O(1) porque cada nó conhece seus vizinhos. Uma lista simples ou um `list.remove` custaria O(n).
- **Nó sentinela circular.** Elimina os casos especiais de lista vazia e de um elemento; `head.next` é o mais recente e `head.prev` o menos recente.
- **TTL preguiçoso.** Não há thread de limpeza: entradas expiradas são descartadas quando lidas ou quando chegam ao fim da lista. Isso mantém `put` em O(1) e evita uma thread de fundo; o custo é que entradas mortas podem ocupar espaço até serem tocadas (use `purge_expired()` se isso importar). Uma entrada expirada removida do fim da lista não conta como despejo.
- **Um único `RLock` grosso.** É simples e correto; a contenção cresce com o número de threads. A reentrância permite que `get_or_set` chame `get` e `put`. Alternativas seriam particionar o cache em shards, cada um com seu lock.
- **`get_or_set` executa a fábrica sob o lock.** Garante uma única computação por chave ausente, ao custo de bloquear as outras threads durante o cálculo.
- **Relógio monotônico.** O TTL não deve ser afetado por ajustes do relógio do sistema.
- **Complexidade:** `get`, `put`, `delete` e `peek` são O(1) (amortizado, por causa do dicionário); `purge_expired` e `items` são O(n); memória O(capacidade).

## Estrutura de pastas

```
LruCache/
├── lru_cache/
│   ├── __init__.py
│   └── cache.py        # LRUCache e o nó da lista
├── tests/
│   └── test_cache.py
├── LICENSE
└── README.md
```

## Limitações conhecidas

- O lock global serializa todas as operações; não há sharding nem leitura sem lock.
- Não há limite por tamanho em bytes, apenas por número de entradas.
- Entradas expiradas só liberam espaço quando acessadas, despejadas ou purgadas.
- Sem callbacks de despejo nem persistência.
- A contagem de estatísticas é local ao processo.

## Licença

MIT. Veja o arquivo [LICENSE](LICENSE).
