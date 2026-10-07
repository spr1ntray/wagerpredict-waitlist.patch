# Wager

Soft Hub patch for [wagerpredict.com](https://wagerpredict.com) mainnet waitlist.

## Install

```text
dist/wagerpredict-testnet-1.24.0.softhub.zip
```

Soft Hub → Патчи → перетащить zip → Подготовить, если попросит.

## Actions

| Действие | Что делает |
|---|---|
| Заявка | Кошелёк и почта в очередь mainnet через прокси аккаунта |
| Парсинг | Статус очереди. Ничего не меняет |

На аккаунте нужны ключ, прокси и почта. Повторно уже поданные адреса софт не трогает.

## Build

```bash
python3 scripts/build_plugin.py \
  wagerpredict-testnet \
  dist/wagerpredict-testnet-1.24.0.softhub.zip
```
