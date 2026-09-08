# -*- coding: utf-8 -*-
"""Проверка парсера v2fly и сборки правил без обращения к сети."""
import sys
import update_ru_domains as u


def lines(items):
    """Собрать содержимое списка v2fly без возни с экранированием."""
    return chr(10).join(items) + chr(10)


FIXTURES = {
    "ozon": lines(["# комментарий", "ozon.ru", "full:www.ozon.travel",
                   "ozon.com @ads", "keyword:ozonstatic", "include:ozon-cdn"]),
    "ozon-cdn": lines(["ozstatic.by", "ozonru.net"]),
    "category-ads-all": lines(["doubleclick.net", "adservice.google.com @ads",
                               "include:ads-extra"]),
    "ads-extra": lines(["adriver.ru"]),
}
u.fetch = lambda name: FIXTURES.get(name)

# --- парсер ---------------------------------------------------------------

parsed = u.parse_list(FIXTURES["ozon"], "ozon")
assert parsed == ["domain:ozon.ru", "full:www.ozon.travel",
                  "domain:ozstatic.by", "domain:ozonru.net"], parsed
print("parse_list OK: @ads отброшен в белом списке, include развёрнут")

blocked = u.parse_list(FIXTURES["category-ads-all"], "category-ads-all",
                       None, u.BLOCK_SKIP_ATTRS)
assert blocked == ["domain:doubleclick.net", "domain:adservice.google.com",
                   "domain:adriver.ru"], blocked
print("parse_list OK: в блок-списке @ads сохранён")


# include с атрибутом должен брать из файла только помеченные записи,
# иначе блок-список рекламы утащит в блокировку весь сервис
FIXTURES["svc-full"] = lines(["service.ru", "cdn.service.ru", "ads.service.ru @ads"])
FIXTURES["ads-scoped"] = lines(["include:svc-full @ads", "doubleclick.net"])
scoped = u.parse_list(FIXTURES["ads-scoped"], "ads-scoped", None, u.BLOCK_SKIP_ATTRS)
assert scoped == ["domain:ads.service.ru", "domain:doubleclick.net"], scoped
print("include с атрибутом OK: взята только помеченная запись")

# --- слияние с seed -------------------------------------------------------

seed = {"groups": {
    "ozon": {"title": "Ozon", "upstream": ["ozon"],
             "domains": ["domain:ozon.ru", "domain:o3.ru"]},
    "ads": {"title": "Реклама", "action": "block",
            "upstream": ["category-ads-all"], "domains": []},
}}
groups, actions, stats = u.collect(seed)
assert groups["ozon"] == ["domain:ozon.ru", "domain:o3.ru", "full:www.ozon.travel",
                          "domain:ozstatic.by", "domain:ozonru.net"], groups["ozon"]
assert groups["ads"] == ["domain:doubleclick.net", "domain:adservice.google.com",
                         "domain:adriver.ru"], groups["ads"]
assert actions == {"ozon": "direct", "ads": "block"}, actions
print("merge OK: seed сохранён, добавлено", stats["added"])

# Рекламный домен, попавший в апстрим обычного сервиса, должен уйти в блок,
# а не быть занятым direct-группой: блок-группы обрабатываются первыми.
FIXTURES["ru-service"] = lines(["service.ru", "adriver.ru"])
FIXTURES["ads-only"] = lines(["doubleclick.net", "adriver.ru"])
seed_conflict = {"groups": {
    "svc": {"title": "Сервис", "upstream": ["ru-service"], "domains": []},
    "ads": {"title": "Реклама", "action": "block",
            "upstream": ["ads-only"], "domains": []},
}}
gc, ac, _ = u.collect(seed_conflict)
assert "domain:adriver.ru" in gc["ads"], gc["ads"]
assert "domain:adriver.ru" not in gc["svc"], gc["svc"]
assert list(gc) == ["svc", "ads"], "порядок групп должен остаться как в seed"
print("приоритет OK: спорный домен ушёл в блок, порядок групп сохранён")

# --- поведение при сбоях --------------------------------------------------

u.fetch = lambda name: None
groups2, actions2, stats2 = u.collect(seed)
assert groups2["ozon"] == seed["groups"]["ozon"]["domains"]
assert sorted(set(stats2["missing"])) == ["category-ads-all", "ozon"]
print("404 upstream OK: seed не пострадал")


def boom(name):
    raise RuntimeError("сеть недоступна")


u.fetch = boom
try:
    u.collect(seed)
    sys.exit("ОШИБКА: исключение должно было пробросить наверх")
except RuntimeError:
    print("сетевой сбой OK: пробрасывается, файлы не переписываются")

# --- правила --------------------------------------------------------------

g = {"ozon": ["domain:ozon.ru"], "ads": ["domain:doubleclick.net"]}
a = {"ozon": "direct", "ads": "block"}
srv = u.build_rules(g, "server", a)
cli = u.build_rules(g, "client", a)
assert srv[0]["outboundTag"] == "BLOCK" and srv[-1]["outboundTag"] == "DIRECT"
assert cli[0]["outboundTag"] == "direct" and cli[1]["outboundTag"] == "proxy"
assert cli[-1]["network"] == "tcp,udp" and cli[-1]["outboundTag"] == "proxy"


def idx(rules, tag, domain):
    return next(i for i, r in enumerate(rules)
                if r.get("domain") and domain in r["domain"] and r["outboundTag"] == tag)


# реклама должна стоять выше direct-групп, иначе трекер внутри российского
# сервиса проехал бы по правилу этого сервиса
assert idx(cli, "block", "domain:doubleclick.net") < idx(cli, "direct", "domain:ozon.ru")
assert idx(srv, "BLOCK", "domain:doubleclick.net") < idx(srv, "DIRECT", "domain:ozon.ru")
print("порядок OK: блок-правила выше direct")

assert not any("17.0.0.0/8" in str(r) for r in cli + srv), "сеть Apple должна быть убрана"
print("правила OK: server=%d, client=%d" % (len(srv), len(cli)))
print()
print("все проверки пройдены")
