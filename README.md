# RU routing

Роутинг для Xray: российские сервисы идут напрямую, всё остальное — через туннель.

Собственные `geosite.dat` и `geoip.dat`, готовые профили для Happ и Incy,
конфиги для панели Remnawave и обновление списков раз в 2 дня через GitHub Actions.

## Что внутри

**1026 доменов** в 30 категориях: Яндекс (Браузер, Карты, Музыка), VK (соцсеть,
Видео, Музыка), МТС, Сбербанк, Т-Банк, ВТБ, Альфа-Банк и ещё десяток банков из
`category-bank-ru`, Wildberries, Ozon, MegaMarket, Самокат, Кинопоиск, RuStore,
Avito, 2ГИС, Одноклассники, MAX, Rutube, Mail.ru, ФНС и Госуслуги, платёжный
контур НСПК и Mir Pay, плюс системный слой iOS и Android.

**10 844 диапазона** в `geoip`: все российские сети (IPv4 и IPv6), сеть Apple
`17.0.0.0/8` и приватные адреса.

## Быстрый старт

### Happ

Профиль забирает списки из наших `.dat` по ссылке, поэтому сам он занимает
меньше килобайта. Готовая ссылка — в [`dist/links.md`](dist/links.md), открыть
её нужно на устройстве с установленным Happ.

    happ://routing/add/{base64}     — добавить
    happ://routing/onadd/{base64}   — добавить и сразу включить

Гео-файлы приложение обновляет само, но не чаще раза в неделю.

### Incy

Incy — клиент на Xray-core, гео-файлы ему не подсунуть, поэтому он получает
полный список доменов по ссылке. Схема `autorouting` включает автообновление:

    incy://autorouting/add/https://raw.githubusercontent.com/USER/REPO/main/dist/incy-routing.json

Разовый импорт без автообновления — `incy://routing/add/{base64}`, тоже в
[`dist/links.md`](dist/links.md).

### Панель Remnawave

`xray-config-remnawave.json` — полный конфиг ноды. Замените `privateKey` в
`realitySettings` на свой. Если мержите роутинг в существующий конфиг, возьмите
секцию из [`dist/routing-ru-apps.json`](dist/routing-ru-apps.json).

В inbound обязателен `sniffing` с `destOverride: ["http", "tls", "quic"]` —
без него доменные правила не работают, роутер видит только IP.

### Xray на десктопе

`xray-client-config.json` — готовый конфиг с socks 10808 и http 10809.
Либо положите `.dat` рядом с бинарником и ссылайтесь на категории:

```json
{ "type": "field", "domain": ["ext:ru-routing-geosite.dat:ru-apps"], "outboundTag": "direct" }
{ "type": "field", "ip": ["ext:ru-routing-geoip.dat:ru"], "outboundTag": "direct" }
```

Файлы работают и как замена штатных: переименуйте в `geosite.dat` / `geoip.dat`
и обращайтесь как `geosite:ru-apps`, `geoip:ru`.

## Категории geosite

Кроме сводной `ru-apps` есть категория на каждую группу — можно включать
выборочно: `yandex`, `yandex-maps`, `yandex-music`, `vk`, `vk-video`, `vk-music`,
`mts`, `sber`, `tbank`, `vtb`, `alfabank`, `banks-ru`, `gov-ru`, `wildberries`,
`ozon`, `megamarket`, `samokat`, `kinopoisk`, `rustore`, `avito`, `2gis`, `ok`,
`max`, `rutube`, `mailru`, `apple`, `android`, `huawei`, `payments`.

В geoip: `ru`, `apple`, `private`.

## Как это обновляется

Раз в 2 дня GitHub Actions подтягивает домены из
[v2fly/domain-list-community](https://github.com/v2fly/domain-list-community),
пересобирает `.dat`, проверяет их настоящим Xray и публикует в релиз `latest`.

Домены из апстрима только **добавляются** к ручному списку в
`ru-domains-seed.json` — ничего не удаляется. Если апстрим выкинет домен, у вас
он останется: иначе чужая правка могла бы молча сломать вам роутинг банка.

Локально то же самое:

```bash
python update_ru_domains.py
python build_dat.py --verify
python make_profiles.py --repo username/ru-routing
```

Нужен только Python 3.8+, внешних зависимостей нет.

## Добавить свой сервис

В `ru-domains-seed.json` дописать группу:

```json
"мой-сервис": {
  "title": "Название",
  "upstream": [],
  "domains": ["domain:example.ru"]
}
```

`upstream` — имена файлов из v2fly, откуда подмешивать домены автоматически;
пустой список означает «только ручные». Дальше `python update_ru_domains.py`.

Префикс `domain:` совпадает со всеми поддоменами: `domain:nalog.ru` покрывает и
`lknpd.nalog.ru`. Есть ещё `full:` для точного совпадения.

## Что стоит знать

**Серверный DIRECT — это выход с IP ноды, а не с домашнего IP.** Если нода за
границей, российские банки увидят иностранный адрес и заблокируют сессию.
Реальный обход даёт только клиентский роутинг — Happ, Incy или конфиг Xray на
устройстве.

**FCM намеренно идёт в туннель.** Google push в РФ режется, напрямую уведомления
приходят с большими задержками. Домены `fcm.googleapis.com`, `mtalk.google.com`
и `alt1-8-mtalk.google.com` не входят ни в одну direct-категорию.

**Apple `17.0.0.0/8` идёт напрямую целиком**, включая App Store. Если Apple ID не
российский и магазин нужен через туннель — уберите `geoip:apple` из `DirectIp`.

**Плашку «Лучше без VPN» роутингом не убрать.** iOS сообщает приложениям о самом
факте активного VPN-интерфейса, независимо от того, куда идёт их трафик.

## Проверка

`.dat` собираются вручную закодированным protobuf без внешних библиотек, поэтому
каждая сборка проверяется трижды: обратным разбором в `build_dat.py --verify`,
загрузкой в настоящий Xray (`xray run -test`) и негативным контролем на
несуществующую категорию. Сквозной тест показал, что `lknpd.nalog.ru` уходит
в `direct`, а `example.com` — в `block`.

## Источники

- [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) — домены
- [ipverse/rir-ip](https://github.com/ipverse/rir-ip) — российские IP-диапазоны
