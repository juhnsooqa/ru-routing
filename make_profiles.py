#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Профили роутинга и deeplink-ссылки для Happ и Incy.

Happ и Incy устроены по-разному, поэтому и подход разный:

  Happ  — свой формат профиля (DirectSites/DirectIp + Geositeurl/Geoipurl).
          Профиль крошечный, всё содержимое лежит в наших .dat, которые
          приложение скачивает по ссылке само. Отсюда короткий deeplink.

  Incy  — Xray-core, ест обычные правила Xray. Гео-файлы ему не подсунуть,
          поэтому отдаём полный список доменов, но по URL: схема
          incy://autorouting/add/{url} умеет обновлять его сама.

Слаг репозитория берётся из --repo, затем из GITHUB_REPOSITORY (его выставляет
GitHub Actions), затем из файла repo.txt. Если ничего нет — останется заглушка.

Запуск:
    python make_profiles.py --repo username/ru-routing
"""

import argparse
import base64
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(BASE_DIR, "dist")
PLACEHOLDER = "USER/REPO"


def repo_slug(arg):
    if arg:
        return arg
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    path = os.path.join(BASE_DIR, "repo.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            value = fh.read().strip()
            if value:
                return value
    return PLACEHOLDER


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def b64(obj):
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


# --------------------------------------------------------------------------

def happ_profile(slug):
    """Профиль в формате Happ. Списки живут в .dat, здесь только ссылки на них."""
    release = "https://github.com/%s/releases/latest/download" % slug
    return {
        "Name": "RU bypass",
        "GlobalProxy": "true",
        # Внешние домены — через DoH Cloudflare, российские — через Яндекс.
        # Иначе РФ-домены резолвятся зарубежным резолвером и CDN отдаёт чужие узлы.
        "RemoteDNSType": "DoH",
        "RemoteDNSDomain": "https://cloudflare-dns.com/dns-query",
        "RemoteDNSIP": "1.1.1.1",
        "DomesticDNSType": "DoU",
        "DomesticDNSDomain": "",
        "DomesticDNSIP": "77.88.8.8",
        "DnsHosts": {"cloudflare-dns.com": "1.1.1.1"},
        "Geositeurl": "%s/ru-routing-geosite.dat" % release,
        "Geoipurl": "%s/ru-routing-geoip.dat" % release,
        "DirectSites": ["geosite:ru-apps"],
        "DirectIp": [
            "geoip:ru",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "169.254.0.0/16",
            "224.0.0.0/4",
            "255.255.255.255",
        ],
        # FCM намеренно не попадает ни в одну direct-категорию:
        # в РФ google push режется, ему нужен туннель.
        # Реклама и трекеры — в блокировку отдельной категорией.
        "ProxySites": [],
        "ProxyIp": [],
        "BlockSites": ["geosite:ads"],
        "BlockIp": [],
        "DomainStrategy": "IPIfNonMatch",
        "FakeDNS": "false",
    }


def incy_routing():
    """Правила Xray для Incy — берём уже собранный полный список."""
    path = os.path.join(DIST, "happ-routing-ru-apps.json")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    doc["name"] = "RU bypass"
    doc["remarks"] = "Российские сервисы напрямую, остальное через прокси"
    return doc


LIMIT_ONCE = 20000


def incy_once_block(incy_b64):
    """Кнопка разового импорта — только если ссылка вменяемой длины.

    С блокировкой рекламы список раздувается до сотен килобайт, и deeplink
    такой длины ни один клиент не примет. Вариант с автообновлением работает
    всегда, потому что передаёт ссылку, а не сам список."""
    if len(incy_b64) <= LIMIT_ONCE:
        return ('<a class="btn sec" href="incy://routing/add/%s">'
                'Разово, без автообновления</a>' % incy_b64)
    return ('<p class="meta">Разовый импорт ссылкой недоступен: со списком '
            'блокировки профиль весит %d КБ, столько в deeplink не помещается. '
            'Используйте вариант с автообновлением выше.</p>' % (len(incy_b64) // 1024))


def main():
    ap = argparse.ArgumentParser(description="Профили и deeplink-ссылки")
    ap.add_argument("--repo", help="слаг репозитория, например username/ru-routing")
    args = ap.parse_args()

    slug = repo_slug(args.repo)
    raw = "https://raw.githubusercontent.com/%s/main" % slug

    happ = happ_profile(slug)
    incy = incy_routing()

    os.makedirs(DIST, exist_ok=True)
    with open(os.path.join(DIST, "happ-profile.json"), "w", encoding="utf-8") as fh:
        fh.write(dumps(happ))
    with open(os.path.join(DIST, "incy-routing.json"), "w", encoding="utf-8") as fh:
        fh.write(dumps(incy))

    happ_b64 = b64(happ)
    incy_b64 = b64(incy)
    incy_url = "%s/dist/incy-routing.json" % raw

    lines = [
        "# Ссылки для импорта",
        "",
        "Открыть на устройстве, где установлено приложение.",
        "",
        "## Happ",
        "",
        "Профиль тянет домены и адреса из наших .dat по ссылке, поэтому он короткий.",
        "Гео-файлы приложение обновляет само, но не чаще раза в неделю.",
        "",
        "Добавить (%d символов):" % len(happ_b64),
        "",
        "    happ://routing/add/%s" % happ_b64,
        "",
        "Добавить и сразу включить:",
        "",
        "    happ://routing/onadd/%s" % happ_b64,
        "",
        "## Incy",
        "",
        "Рекомендуемый вариант — с автообновлением: приложение само перечитывает",
        "список по ссылке, а его обновляет GitHub Actions раз в 2 дня.",
        "",
        "    incy://autorouting/add/%s" % incy_url,
        "",
    ]
    if len(incy_b64) <= LIMIT_ONCE:
        lines += [
            "Разово, без автообновления (%d символов):" % len(incy_b64),
            "",
            "    incy://routing/add/%s" % incy_b64,
            "",
        ]
    else:
        lines += [
            "Разовый импорт ссылкой недоступен: со списком блокировки профиль",
            "весит %d КБ — столько в deeplink не помещается." % (len(incy_b64) // 1024),
            "",
        ]
    lines += [
        "## Прямые ссылки на файлы",
        "",
        "    geosite: https://github.com/%s/releases/latest/download/ru-routing-geosite.dat" % slug,
        "    geoip:   https://github.com/%s/releases/latest/download/ru-routing-geoip.dat" % slug,
        "    роутинг: %s" % incy_url,
        "",
    ]
    if slug == PLACEHOLDER:
        lines.insert(1, "")
        lines.insert(2, "> Слаг репозитория не задан — в ссылках стоит `USER/REPO`.")
        lines.insert(3, "> Укажите его: `python make_profiles.py --repo username/ru-routing`")

    with open(os.path.join(DIST, "links.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print("репозиторий: %s%s" % (slug, "  (заглушка!)" if slug == PLACEHOLDER else ""))
    print("happ-профиль:  %5d символов в ссылке" % len(happ_b64))
    print("incy-роутинг:  %5d символов в ссылке, %d правил" % (len(incy_b64), len(incy["rules"])))
    print("записано: dist/happ-profile.json, dist/incy-routing.json, dist/links.md")
    # Страница с кнопками: GitHub вырезает ссылки на happ:// и incy:// из markdown,
    # кликабельными они бывают только в настоящем HTML.
    tpl_path = os.path.join(BASE_DIR, "templates", "page.html")
    if os.path.exists(tpl_path):
        with open(tpl_path, encoding="utf-8") as fh:
            page = fh.read()
        with open(os.path.join(DIST, "merged-domains.json"), encoding="utf-8") as fh:
            merged = json.load(fh)
        subs = {
            "__HAPP_ADD__": "happ://routing/add/" + happ_b64,
            "__HAPP_ONADD__": "happ://routing/onadd/" + happ_b64,
            "__INCY_AUTO__": "incy://autorouting/add/" + incy_url,
            "__INCY_ONCE_BLOCK__": incy_once_block(incy_b64),
            "__REL__": "https://github.com/%s/releases/latest/download" % slug,
            "__RAW__": raw,
            "__REPO_URL__": "https://github.com/%s" % slug,
            "__COUNT__": str(len({d for v in merged.values()
                                  if v.get("action", "direct") != "block"
                                  for d in v["domains"]})),
            "__CATS__": str(sum(1 for v in merged.values()
                                if v.get("action", "direct") != "block")),
            "__ADS__": str(sum(len(v["domains"]) for v in merged.values()
                               if v.get("action", "direct") == "block")),
        }
        for key, value in subs.items():
            page = page.replace(key, value)
        docs = os.path.join(BASE_DIR, "docs")
        os.makedirs(docs, exist_ok=True)
        with open(os.path.join(docs, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(page)
        print("страница: docs/index.html")

    return 0


if __name__ == "__main__":
    sys.exit(main())
