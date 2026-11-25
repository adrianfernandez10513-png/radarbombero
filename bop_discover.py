#!/usr/bin/env python3
"""Busca qué boletines provinciales (BOP) ofrecen RSS o Atom.

Uso: python bop_discover.py            -> escribe data/bop_discovery.json y muestra un resumen
Después copia los feeds válidos a sources.json: [{"nombre": "BOP Granada", "url": "..."}]
Las URL de bop_urls.json salen del listado oficial del Punto de Acceso General (administracion.gob.es).
"""
import json, re, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

UA = "radar-bomberos/0.1 (proyecto personal; contacto: https://github.com/adrianfernandez10513/radarbombero)"
LINK = re.compile(r"<link\b[^>]*type=[\"']application/(?:rss|atom)\+xml[\"'][^>]*>", re.I)
HREF = re.compile(r"href=[\"']([^\"']+)", re.I)
COMUNES = ["/rss", "/feed", "/rss.xml", "/feed.xml", "/atom.xml", "/rss/bop", "/bop/rss"]


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=25) as r:
            return r.geturl(), r.read(2_000_000).decode("utf-8", "replace")
    except Exception:
        return None, None


def n_items(texto):
    """Número de entradas si el texto es un feed RSS/Atom válido; 0 si no."""
    try:
        root = ET.fromstring(texto.lstrip())
    except Exception:
        return 0
    return sum(1 for e in root.iter() if e.tag.rsplit("}", 1)[-1] in ("item", "entry"))


def candidatos(home, html):
    out = [urllib.parse.urljoin(home, m) for tag in LINK.findall(html or "") for m in HREF.findall(tag)]
    p = urllib.parse.urlparse(home)
    base = f"{p.scheme}://{p.netloc}"
    out += [base + c for c in COMUNES]
    return list(dict.fromkeys(out))


def main():
    urls = json.loads(Path("bop_urls.json").read_text())
    res = {}
    for prov, home in urls.items():
        final, html = get(home)
        if final is None:
            res[prov] = {"home": home, "estado": "no_responde", "feeds": []}
            print(f"{prov:24} no responde"); continue
        feeds = []
        for c in candidatos(final, html):
            _, txt = get(c)
            n = n_items(txt) if txt else 0
            if n: feeds.append({"url": c, "items": n})
            time.sleep(0.3)
        res[prov] = {"home": home, "estado": "rss" if feeds else "sin_rss", "feeds": feeds}
        print(f"{prov:24} {'RSS: ' + feeds[0]['url'] if feeds else 'sin RSS'}")
    Path("data").mkdir(exist_ok=True)
    Path("data/bop_discovery.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    ok = sum(1 for v in res.values() if v["feeds"])
    print(f"\n{ok} de {len(res)} boletines con feed. Detalle en data/bop_discovery.json")


if __name__ == "__main__":
    main()
