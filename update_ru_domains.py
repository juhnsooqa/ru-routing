#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Обновление доменных списков для роутинга Xray / Happ.

Что делает:
  1. Читает ru-domains-seed.json — ручной список групп (правится вручную, никогда не затирается).
  2. Тянет соответствующие файлы из v2fly/domain-list-community (источник geosite.dat).
  3. Домены из upstream ДОБАВЛЯЮТСЯ к seed-группам. Ничего не удаляется —
     upstream может внезапно выкинуть домен, и молча потерять его нельзя.
  4. Пересобирает routing-ru-apps.json, happ-routing-ru-apps.json,
     секцию routing в xray-config-remnawave.json и happ-routing-links.txt.
  5. Если ничего не изменилось — файлы не трогает и выходит с кодом 0.

Зависимости: только стандартная библиотека Python 3.8+.

Запуск:
    python update_ru_domains.py                 # обновить
    python update_ru_domains.py --dry-run       # показать диф, ничего не писать
    python update_ru_domains.py --push          # + отправить конфиг в панель Remnawave
"""

import argparse
import base64
import collections
import datetime
import json
import os
import shutil
import sys
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE_DIR, "ru-domains-seed.json")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
LOG = os.path.join(BASE_DIR, "update.log")

UPSTREAM = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/"
TIMEOUT = 30
RETRIES = 3

# Атрибуты v2fly, которые нам не нужны в белом списке.
SKIP_ATTRS = ("@ads", "@cn", "@!cn")


# --------------------------------------------------------------------------
# Статические правила. Отличаются для сервера и клиента, поэтому заданы отдельно.
# --------------------------------------------------------------------------

def static_rules(profile):
    if profile == "server":
        # На ноде: private блокируем (защита от доступа к локалке),
        # торренты режем, чтобы не ловить абузы на IP сервера.
        return {
            "head": [
                {"type": "field", "ip": ["geoip:private"], "outboundTag": "BLOCK"},
                {"type": "field", "protocol": ["bittorrent"], "outboundTag": "BLOCK"},
            ],
            "tail": [],
            "direct": "DIRECT",
        }
    if profile == "client":
        # Готовый конфиг Xray для клиента. Отличие от happ-шаблона — явное
        # правило-заглушка в конце: в таком конфиге outbound "proxy"
        # подставляет панель, и полагаться на порядок outbounds нельзя.
        return {
            "head": [
                {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
                {"type": "field", "domain": GOOGLE_PUSH, "outboundTag": "proxy"},
            ],
            "tail": [
                {"type": "field", "ip": ["17.0.0.0/8"], "outboundTag": "direct"},
                {"type": "field", "protocol": ["bittorrent"], "outboundTag": "direct"},
                {"type": "field", "network": "tcp,udp", "outboundTag": "proxy"},
            ],
            "direct": "direct",
        }
    # На клиенте: локалка нужна (роутер, принтер, NAS), торренты мимо туннеля,
    # FCM наоборот В туннель — в РФ google push режется.
    return {
        "head": [
            {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
            {"type": "field", "domain": GOOGLE_PUSH, "outboundTag": "proxy"},
        ],
        "tail": [
            {"type": "field", "ip": ["17.0.0.0/8"], "outboundTag": "direct"},
            {"type": "field", "protocol": ["bittorrent"], "outboundTag": "direct"},
        ],
        "direct": "direct",
    }


GOOGLE_PUSH = [
    "domain:fcm.googleapis.com",
    "domain:firebaseinstallations.googleapis.com",
    "domain:android.googleapis.com",
    "domain:mtalk.google.com",
] + ["domain:alt%d-mtalk.google.com" % i for i in range(1, 9)]


# --------------------------------------------------------------------------
# Загрузка и разбор upstream
# --------------------------------------------------------------------------

# В консоли Windows по умолчанию cp866 — кириллица в выводе превращается в мусор.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


def log(msg):
    line = "%s  %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def fetch(name):
    """Скачать один файл списка. None — если его нет в upstream (это не ошибка)."""
    url = UPSTREAM + name
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ru-routing-updater/1.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            last = exc
        except Exception as exc:
            last = exc
        if attempt < RETRIES:
            log("  retry %d/%d для %s: %s" % (attempt, RETRIES, name, last))
    raise RuntimeError("не удалось скачать %s: %s" % (url, last))


def parse_list(text, name, seen=None):
    """Разобрать формат v2fly. include: разворачивается рекурсивно."""
    seen = seen if seen is not None else set()
    if name in seen:
        return []
    seen.add(name)

    out = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        entry, attrs = parts[0], parts[1:]
        if any(a in SKIP_ATTRS for a in attrs):
            continue

        if entry.startswith("include:"):
            child = entry.split(":", 1)[1]
            body = fetch(child)
            if body is None:
                log("  include:%s отсутствует в upstream — пропущен" % child)
                continue
            out.extend(parse_list(body, child, seen))
        elif entry.startswith("full:"):
            out.append("full:" + entry.split(":", 1)[1])
        elif entry.startswith("keyword:") or entry.startswith("regexp:"):
            continue  # слишком широко для белого списка, пропускаем осознанно
        else:
            out.append("domain:" + entry.split(":", 1)[-1])
    return out


def collect(seed, offline=False):
    """seed-группы + upstream. Возвращает (группы, статистика)."""
    groups = collections.OrderedDict()
    stats = {"added": 0, "missing": [], "sources": 0}
    cache = {}

    # Дедупликация сквозная, а не по группам: несколько групп могут тянуть один
    # и тот же список апстрима (yandex у Браузера, Карт и Музыки), и без этого
    # одни и те же домены размножились бы по всем правилам.
    known = set()
    for grp in seed["groups"].values():
        known.update(grp["domains"])

    for key, grp in seed["groups"].items():
        domains = list(grp["domains"])

        if not offline:
            for src in grp.get("upstream", []):
                if src not in cache:
                    body = fetch(src)
                    cache[src] = parse_list(body, src) if body is not None else None
                    if cache[src] is None:
                        stats["missing"].append(src)
                        log("  список '%s' отсутствует в upstream" % src)
                    else:
                        stats["sources"] += 1
                if not cache[src]:
                    continue
                for dom in cache[src]:
                    if dom not in known:
                        known.add(dom)
                        domains.append(dom)
                        stats["added"] += 1
                        log("  + %-14s %s" % (key, dom))

        groups[key] = domains
    return groups, stats


# --------------------------------------------------------------------------
# Сборка конфигов
# --------------------------------------------------------------------------

def build_rules(groups, profile):
    st = static_rules(profile)
    rules = list(st["head"])
    for domains in groups.values():
        if domains:
            rules.append({"type": "field", "domain": domains, "outboundTag": st["direct"]})
    rules.extend(st["tail"])
    return rules


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def happ_link(doc):
    minified = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    return "happ://routing/add/" + base64.b64encode(minified.encode("utf-8")).decode("ascii")


def build_outputs(groups):
    """Готовит {путь: содержимое} для всех генерируемых файлов."""
    out = {}

    server_routing = {"domainStrategy": "IPIfNonMatch", "rules": build_rules(groups, "server")}
    out["dist/routing-ru-apps.json"] = dumps({"routing": server_routing})

    block = json.loads(dumps({"routing": server_routing}).replace('"DIRECT"', '"BLOCK"'))
    out["dist/routing-ru-apps-block.json"] = dumps(block)

    # В полном конфиге меняем только routing, остальное (dns, inbounds, outbounds) не трогаем.
    full = read_json(os.path.join(BASE_DIR, "xray-config-remnawave.json"))
    if full is not None:
        full["routing"] = server_routing
        out["xray-config-remnawave.json"] = dumps(full)

    # Клиентские конфиги: меняем только routing, dns/inbounds/outbounds не трогаем.
    for fname in ("xray-client-config.json", "incy-xray-config.json"):
        client = read_json(os.path.join(BASE_DIR, fname))
        if client is None:
            continue
        client.setdefault("routing", {})
        client["routing"]["domainMatcher"] = client["routing"].get("domainMatcher", "hybrid")
        client["routing"]["domainStrategy"] = "IPIfNonMatch"
        client["routing"]["rules"] = build_rules(groups, "client")
        out[fname] = dumps(client)

    happ = read_json(os.path.join(BASE_DIR, "dist", "happ-routing-ru-apps.json")) or {}
    happ_doc = collections.OrderedDict([
        ("name", happ.get("name", "RU apps bypass")),
        ("remarks", happ.get("remarks", "Российские приложения напрямую, остальное через прокси")),
        ("domainStrategy", "IPIfNonMatch"),
        ("rules", build_rules(groups, "happ")),
    ])
    out["dist/happ-routing-ru-apps.json"] = dumps(happ_doc)

    # Машинно-читаемый срез для build_dat.py — чтобы не тянуть апстрим дважды.
    out["dist/merged-domains.json"] = dumps(collections.OrderedDict(groups))

    seed_only = collections.OrderedDict(
        (k, list(v["domains"])) for k, v in read_json(SEED)["groups"].items())
    apps_doc = collections.OrderedDict([
        ("name", "RU apps bypass (только приложения)"),
        ("remarks", "Ручной список без доменов из апстрима"),
        ("domainStrategy", "IPIfNonMatch"),
        ("rules", build_rules(seed_only, "happ")),
    ])
    out["dist/happ-routing-apps-only.json"] = dumps(apps_doc)

    compact = read_json(os.path.join(BASE_DIR, "dist", "happ-routing-ru-compact.json"))
    links = ["### Полный список — happ-routing-ru-apps.json",
             "правил: %d" % len(happ_doc["rules"]), "", happ_link(happ_doc), "",
             "### Только приложения — happ-routing-apps-only.json",
             "правил: %d" % len(apps_doc["rules"]), "", happ_link(apps_doc), ""]
    if compact is not None:
        links += ["### Компактный — happ-routing-ru-compact.json",
                  "правил: %d" % len(compact["rules"]), "", happ_link(compact), ""]
    out["dist/happ-routing-links.txt"] = "\n".join(links)

    return out


def write_outputs(outputs, dry_run):
    """Пишет только реально изменившиеся файлы. Возвращает список имён."""
    changed = []
    for name, content in outputs.items():
        path = os.path.join(BASE_DIR, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        old = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                old = fh.read()
        if old == content:
            continue
        changed.append(name)
        if dry_run:
            continue
        if old is not None:
            os.makedirs(BACKUP_DIR, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(path, os.path.join(BACKUP_DIR, "%s.%s" % (name.replace("/", "_"), stamp)))
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)   # атомарная замена
    return changed


def prune_backups(keep=20):
    if not os.path.isdir(BACKUP_DIR):
        return
    files = sorted(
        (os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR)),
        key=os.path.getmtime, reverse=True)
    for old in files[keep:]:
        os.remove(old)


# --------------------------------------------------------------------------
# Отправка в панель (опционально)
# --------------------------------------------------------------------------

def push_to_panel():
    """
    ВНИМАНИЕ: путь эндпоинта отличается между версиями Remnawave.
    Проверьте его в /api/docs своей панели перед первым запуском с --push.
    """
    url = os.environ.get("REMNAWAVE_API_URL")
    token = os.environ.get("REMNAWAVE_TOKEN")
    uuid = os.environ.get("REMNAWAVE_PROFILE_UUID")
    if not (url and token and uuid):
        log("--push пропущен: не заданы REMNAWAVE_API_URL / REMNAWAVE_TOKEN / REMNAWAVE_PROFILE_UUID")
        return False

    config = read_json(os.path.join(BASE_DIR, "xray-config-remnawave.json"))
    endpoint = "%s/api/config-profiles" % url.rstrip("/")
    body = json.dumps({"uuid": uuid, "config": config}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, method="PATCH", headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            log("панель ответила %s" % resp.status)
            return True
    except urllib.error.HTTPError as exc:
        log("панель отклонила запрос: %s %s" % (exc.code, exc.read().decode("utf-8", "replace")[:300]))
    except Exception as exc:
        log("не удалось достучаться до панели: %s" % exc)
    return False


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Обновление доменных списков роутинга")
    ap.add_argument("--dry-run", action="store_true", help="показать, что изменится, ничего не записывая")
    ap.add_argument("--offline", action="store_true", help="пересобрать из seed без обращения к сети")
    ap.add_argument("--push", action="store_true", help="отправить конфиг в панель Remnawave")
    args = ap.parse_args()

    log("=== запуск%s ===" % (" (dry-run)" if args.dry_run else ""))
    seed = read_json(SEED)
    if seed is None:
        log("ОШИБКА: не найден %s" % SEED)
        return 1

    try:
        groups, stats = collect(seed, offline=args.offline)
    except RuntimeError as exc:
        # Сеть отвалилась — оставляем текущие файлы как есть, они рабочие.
        log("ОШИБКА: %s" % exc)
        log("файлы не тронуты, предыдущая версия остаётся в силе")
        return 2

    total = sum(len(v) for v in groups.values())
    outputs = build_outputs(groups)
    changed = write_outputs(outputs, args.dry_run)

    log("источников: %d, доменов: %d, новых: %d" % (stats["sources"], total, stats["added"]))
    if stats["missing"]:
        log("нет в upstream: %s" % ", ".join(sorted(set(stats["missing"]))))

    if not changed:
        log("изменений нет")
        return 0

    log("%s: %s" % ("изменилось бы" if args.dry_run else "обновлено", ", ".join(changed)))
    if args.dry_run:
        return 0

    prune_backups()
    if args.push:
        push_to_panel()
    return 0


if __name__ == "__main__":
    sys.exit(main())
