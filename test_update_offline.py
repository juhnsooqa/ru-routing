# -*- coding: utf-8 -*-
"""Проверка парсера v2fly и сборки правил без обращения к сети."""
import json, io, sys
import update_ru_domains as u

FIXTURES = {
    "ozon": u"""
# комментарий
ozon.ru
full:www.ozon.travel
ozon.com @ads
keyword:ozonstatic
include:ozon-cdn
""",
    "ozon-cdn": u"ozstatic.by\nozonru.net\n",
}
u.fetch = lambda name: FIXTURES.get(name)

parsed = u.parse_list(FIXTURES["ozon"], "ozon")
assert parsed == ["domain:ozon.ru", "full:www.ozon.travel",
                  "domain:ozstatic.by", "domain:ozonru.net"], parsed
print("parse_list OK:", parsed)

seed = {"groups": {"ozon": {"title": "Ozon", "upstream": ["ozon"],
                            "domains": ["domain:ozon.ru", "domain:o3.ru"]}}}
groups, stats = u.collect(seed)
assert groups["ozon"] == ["domain:ozon.ru", "domain:o3.ru", "full:www.ozon.travel",
                          "domain:ozstatic.by", "domain:ozonru.net"], groups["ozon"]
assert stats["added"] == 3, stats
print("merge OK: seed сохранён, добавлено", stats["added"])

u.fetch = lambda name: None
groups2, stats2 = u.collect(seed)
assert groups2["ozon"] == seed["groups"]["ozon"]["domains"]
assert stats2["missing"] == ["ozon"]
print("404 upstream OK: seed не пострадал")

def boom(name):
    raise RuntimeError("сеть недоступна")
u.fetch = boom
try:
    u.collect(seed)
    sys.exit("ОШИБКА: исключение должно было пробросить наверх")
except RuntimeError:
    print("сетевой сбой OK: пробрасывается, файлы не переписываются")

srv = u.build_rules({"ozon": ["domain:ozon.ru"]}, "server")
cli = u.build_rules({"ozon": ["domain:ozon.ru"]}, "happ")
assert srv[0]["outboundTag"] == "BLOCK" and srv[-1]["outboundTag"] == "DIRECT"
assert cli[0]["outboundTag"] == "direct" and cli[1]["outboundTag"] == "proxy"
assert cli[-1]["protocol"] == ["bittorrent"] and cli[-1]["outboundTag"] == "direct"
print("правила OK: server=%d, happ=%d" % (len(srv), len(cli)))
print("\nвсе проверки пройдены")
