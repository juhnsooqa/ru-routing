#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сборка собственных geosite.dat и geoip.dat для Xray.

Формат — protobuf из v2ray-core. Схема:

    message Domain    { Type type = 1; string value = 2; }   Type: 0 Plain, 1 Regex, 2 Domain, 3 Full
    message GeoSite   { string country_code = 1; repeated Domain domain = 2; }
    message GeoSiteList { repeated GeoSite entry = 1; }

    message CIDR      { bytes ip = 1; uint32 prefix = 2; }
    message GeoIP     { string country_code = 1; repeated CIDR cidr = 2; }
    message GeoIPList { repeated GeoIP entry = 1; }

Кодировщик написан вручную — protobuf-библиотека не нужна, схема тривиальная.

Вход:  dist/merged-domains.json (его пишет update_ru_domains.py)
Выход: dist/ru-routing-geosite.dat, dist/ru-routing-geoip.dat

Запуск:
    python build_dat.py            # собрать
    python build_dat.py --verify   # + проверить обратным разбором
"""

import argparse
import collections
import ipaddress
import json
import os
import struct
import sys
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(BASE_DIR, "dist")
MERGED = os.path.join(BASE_DIR, "dist", "merged-domains.json")

IPV4_URL = "https://raw.githubusercontent.com/ipverse/rir-ip/master/country/ru/ipv4-aggregated.txt"
IPV6_URL = "https://raw.githubusercontent.com/ipverse/rir-ip/master/country/ru/ipv6-aggregated.txt"

# Диапазоны, которые всегда должны идти напрямую.
PRIVATE = [
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16",
    "172.16.0.0/12", "192.0.0.0/24", "192.168.0.0/16", "198.18.0.0/15",
    "224.0.0.0/4", "240.0.0.0/4", "255.255.255.255/32", "::1/128", "fc00::/7", "fe80::/10",
]
PLAIN, REGEX, DOMAIN, FULL = 0, 1, 2, 3


# --------------------------------------------------------------------------
# Минимальный кодировщик protobuf
# --------------------------------------------------------------------------

def varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def tag(field, wire):
    return varint((field << 3) | wire)


def field_varint(field, value):
    return tag(field, 0) + varint(value)


def field_bytes(field, payload):
    return tag(field, 2) + varint(len(payload)) + payload


def field_string(field, text):
    return field_bytes(field, text.encode("utf-8"))


# --------------------------------------------------------------------------
# geosite
# --------------------------------------------------------------------------

def encode_domain(entry):
    """'domain:vk.com' / 'full:www.ozon.ru' / 'regexp:...' -> сообщение Domain."""
    if ":" in entry:
        kind, value = entry.split(":", 1)
    else:
        kind, value = "domain", entry
    dtype = {"domain": DOMAIN, "full": FULL, "regexp": REGEX,
             "keyword": PLAIN, "plain": PLAIN}.get(kind, DOMAIN)
    return field_varint(1, dtype) + field_string(2, value)


def encode_geosite(categories):
    """{'ru-apps': ['domain:vk.com', ...]} -> содержимое geosite.dat."""
    out = bytearray()
    for name, entries in categories.items():
        body = field_string(1, name.upper())          # Xray приводит код к верхнему регистру
        for entry in entries:
            body += field_bytes(2, encode_domain(entry))
        out += field_bytes(1, bytes(body))
    return bytes(out)


# --------------------------------------------------------------------------
# geoip
# --------------------------------------------------------------------------

def encode_cidr(network):
    net = ipaddress.ip_network(network.strip(), strict=False)
    return field_bytes(1, net.network_address.packed) + field_varint(2, net.prefixlen)


def encode_geoip(groups):
    out = bytearray()
    for name, nets in groups.items():
        body = field_string(1, name.upper())
        for net in nets:
            body += field_bytes(2, encode_cidr(net))
        out += field_bytes(1, bytes(body))
    return bytes(out)


# --------------------------------------------------------------------------
# Обратный разбор — чтобы не выкладывать в сеть битый файл
# --------------------------------------------------------------------------

def read_varint(buf, pos):
    result = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def parse_messages(buf):
    """Разбирает поток из повторяющегося поля 1 (length-delimited)."""
    pos, items = 0, []
    while pos < len(buf):
        key, pos = read_varint(buf, pos)
        if key >> 3 != 1 or key & 7 != 2:
            raise ValueError("неожиданный тег %d на позиции %d" % (key, pos))
        size, pos = read_varint(buf, pos)
        items.append(buf[pos:pos + size])
        pos += size
    return items


def verify_geosite(path, expected):
    entries = parse_messages(open(path, "rb").read())
    names = []
    total = 0
    for entry in entries:
        pos = 0
        key, pos = read_varint(entry, pos)
        size, pos = read_varint(entry, pos)
        names.append(entry[pos:pos + size].decode("utf-8"))
        pos += size
        count = 0
        while pos < len(entry):
            key, pos = read_varint(entry, pos)
            size, pos = read_varint(entry, pos)
            pos += size
            count += 1
        total += count
    assert len(names) == len(expected), "категорий %d, ожидалось %d" % (len(names), len(expected))
    assert set(names) == {n.upper() for n in expected}, "имена категорий разошлись"
    return names, total


def verify_geoip(path, expected):
    entries = parse_messages(open(path, "rb").read())
    names, total = [], 0
    for entry in entries:
        pos = 0
        key, pos = read_varint(entry, pos)
        size, pos = read_varint(entry, pos)
        names.append(entry[pos:pos + size].decode("utf-8"))
        pos += size
        while pos < len(entry):
            key, pos = read_varint(entry, pos)
            size, pos = read_varint(entry, pos)
            cidr = entry[pos:pos + size]
            pos += size
            # внутри CIDR: поле 1 — ip (4 или 16 байт), поле 2 — префикс
            cpos = 0
            k, cpos = read_varint(cidr, cpos)
            ln, cpos = read_varint(cidr, cpos)
            assert ln in (4, 16), "длина адреса %d" % ln
            cpos += ln
            k, cpos = read_varint(cidr, cpos)
            prefix, cpos = read_varint(cidr, cpos)
            assert 0 <= prefix <= 128, "префикс %d" % prefix
            total += 1
    assert set(names) == {n.upper() for n in expected}, "имена категорий разошлись"
    return names, total


# --------------------------------------------------------------------------

def fetch_lines(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ru-routing-builder/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = resp.read().decode("utf-8")
    return [l.strip() for l in text.splitlines()
            if l.strip() and not l.startswith("#")]


def main():
    ap = argparse.ArgumentParser(description="Сборка geosite.dat и geoip.dat")
    ap.add_argument("--verify", action="store_true", help="проверить файлы обратным разбором")
    args = ap.parse_args()

    if not os.path.exists(MERGED):
        print("ОШИБКА: нет %s — сначала запустите update_ru_domains.py" % MERGED)
        return 1
    groups = json.load(open(MERGED, encoding="utf-8"))

    # Категории: по одной на группу + сводная ru-apps.
    # В ru-apps попадают только direct-группы: реклама живёт отдельной
    # категорией ads, иначе сводная категория пускала бы её напрямую.
    categories = collections.OrderedDict(
        (name, grp["domains"]) for name, grp in groups.items())
    everything = []
    seen = set()
    for name, grp in groups.items():
        if grp.get("action", "direct") == "block":
            continue
        for e in grp["domains"]:
            if e not in seen:
                seen.add(e)
                everything.append(e)
    categories["ru-apps"] = everything

    os.makedirs(DIST, exist_ok=True)
    site_path = os.path.join(DIST, "ru-routing-geosite.dat")
    with open(site_path, "wb") as fh:
        fh.write(encode_geosite(categories))

    blocked = sum(len(g["domains"]) for g in groups.values()
                  if g.get("action", "direct") == "block")
    print("geosite: %d категорий, %d доменов напрямую, %d в блокировку -> %s" % (
        len(categories), len(everything), blocked, os.path.basename(site_path)))

    print("качаю российские диапазоны...")
    ru = fetch_lines(IPV4_URL) + fetch_lines(IPV6_URL)
    ip_groups = {"ru": ru, "private": PRIVATE}

    ip_path = os.path.join(DIST, "ru-routing-geoip.dat")
    with open(ip_path, "wb") as fh:
        fh.write(encode_geoip(ip_groups))
    print("geoip: %d категорий, %d диапазонов -> %s" % (
        len(ip_groups), sum(len(v) for v in ip_groups.values()), os.path.basename(ip_path)))

    if args.verify:
        names, total = verify_geosite(site_path, categories)
        print("проверка geosite: %d категорий, %d доменов — ok" % (len(names), total))
        names, total = verify_geoip(ip_path, ip_groups)
        print("проверка geoip: %d категорий, %d диапазонов — ok" % (len(names), total))

    for path in (site_path, ip_path):
        print("  %s — %.1f КБ" % (os.path.basename(path), os.path.getsize(path) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
