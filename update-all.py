#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Полный цикл: списки -> .dat -> профили и ссылки. Для планировщика."""
import os, subprocess, sys

BASE = os.path.dirname(os.path.abspath(__file__))
STEPS = [
    ["update_ru_domains.py"],
    ["build_dat.py", "--verify"],
    ["make_profiles.py"],
]
for step in STEPS:
    code = subprocess.call([sys.executable, os.path.join(BASE, step[0])] + step[1:], cwd=BASE)
    if code != 0:
        print("шаг %s завершился с кодом %d, дальше не идём" % (step[0], code))
        sys.exit(code)
print("готово")
