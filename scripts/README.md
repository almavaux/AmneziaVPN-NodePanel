# Internal Scripts

Эта папка внутренняя, не для ручного деплоя.

Публичный путь деплоя панели:

```bash
curl -fsSL https://raw.githubusercontent.com/almavaux/AmneziaVPN-NodePanel/main/deploy.sh | bash -s -- install
```

После установки:

```bash
vvh menu
```

Правила:
- Панель ставится/обновляется только через `deploy.sh`/`vvh`.
- Node ставится и обновляется только из панели.
