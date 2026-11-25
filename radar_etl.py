#!/usr/bin/env python3
"""Radar de convocatorias de bombero: ETL desde el BOE y RSS de boletines provinciales.

Uso:
  python radar_etl.py                      # últimos 7 días
  python radar_etl.py --desde 2026-09-01   # recuperar histórico
Salida: data/docs.json (todo lo encontrado) y data/convocatorias.json (fichas para la web).
Solo librería estándar. Fuente: BOE datos abiertos (reutilización con cita de la fuente).
"""
import argparse, hashlib, html, json, re, sys, time, unicodedata, urllib.error, urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

UA = "radar-bomberos/0.1 (proyecto personal; contacto: https://github.com/adrianfernandez10513-png/radarbombero)"
BOE_SUMARIO = "https://www.boe.es/datosabiertos/api/boe/sumario/{d}"
KEYWORDS = re.compile(r"\bbomberos?\b|extinci[oó]n de incendios|prevenci[oó]n y extinci[oó]n", re.I)
GENERIC = re.compile(r"convocatoria|bases|pruebas selectivas|proveer|plazas?\b", re.I)
SKIP_DEPT = re.compile(r"universidad|ministerio", re.I)
SECCIONES = {"2B"}  # II.B Oposiciones y concursos
DATA = Path("data")

NUM = {"cinco": 5, "diez": 10, "quince": 15, "veinte": 20, "veinticinco": 25, "treinta": 30}
ORDEN = {"convocatoria": 0, "admitidos": 2, "examen": 3, "resultados": 4, "nombramiento": 5}
FASE = {0: "previsto", 2: "admitidos", 3: "examen", 4: "resultados", 5: "curso"}

# provincia (con alias) -> comunidad
_PROV = {
 "Andalucía": ["Almería", "Cádiz", "Córdoba", "Granada", "Huelva", "Jaén", "Málaga", "Sevilla"],
 "Aragón": ["Huesca", "Teruel", "Zaragoza"], "Asturias": ["Asturias"], "Baleares": ["Illes Balears|Baleares|Islas Baleares"],
 "Canarias": ["Las Palmas", "Santa Cruz de Tenerife"], "Cantabria": ["Cantabria"],
 "Castilla y León": ["Ávila", "Burgos", "León", "Palencia", "Salamanca", "Segovia", "Soria", "Valladolid", "Zamora"],
 "Castilla-La Mancha": ["Albacete", "Ciudad Real", "Cuenca", "Guadalajara", "Toledo"],
 "Cataluña": ["Barcelona", "Girona|Gerona", "Lleida|Lérida", "Tarragona"],
 "Comunidad Valenciana": ["Alicante|Alacant", "Castellón|Castelló", "Valencia|València"],
 "Extremadura": ["Badajoz", "Cáceres"], "Galicia": ["A Coruña|La Coruña|Coruña", "Lugo", "Ourense|Orense", "Pontevedra"],
 "Madrid": ["Madrid"], "Murcia": ["Murcia"], "Navarra": ["Navarra"],
 "País Vasco": ["Álava|Araba", "Gipuzkoa|Guipúzcoa", "Bizkaia|Vizcaya"], "La Rioja": ["La Rioja"],
 "Ceuta": ["Ceuta"], "Melilla": ["Melilla"]}


def norm(t):
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


PROV_ALIAS = {}  # alias normalizado -> (nombre canónico, comunidad)
for _cc, _lst in _PROV.items():
    for _p in _lst:
        _names = _p.split("|")
        for _n in _names:
            PROV_ALIAS[norm(_n)] = (_names[0], _cc)
_ALT = "|".join(re.escape(a) for a in sorted(PROV_ALIAS, key=len, reverse=True))
_CTX = re.compile(r"(?:provincia de|\(|diputacion (?:provincial |foral )?de|ayuntamiento de|cabildo (?:insular )?de)\s*(" + _ALT + r")\b")


def provincia(*textos):
    for t in textos:
        m = _CTX.search(norm(t))
        if m: return PROV_ALIAS[m.group(1)]
    return ("", "")


def ref_bop(body):
    """Referencia al BOP donde se publicaron las bases, si el anuncio del BOE la cita."""
    m = re.search(r"Bolet[ií]n Oficial de la Provincia[^.]{0,120}?n\.?\s?[º°o]\s?(\d+)[^.]{0,40}?(\d{1,2} de [a-záéíóú]+ de \d{4})", body, re.I)
    return {"num": m.group(1), "fecha": m.group(2)} if m else None


def http_get(url, accept=None, retries=3):
    for i in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, **({"Accept": accept} if accept else {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None  # no hay BOE ese día (domingos, festivos)
            time.sleep(2 * (i + 1))
        except Exception:
            time.sleep(2 * (i + 1))
    print(f"  ! fallo al descargar {url}", file=sys.stderr)
    return None


def aslist(x):
    return [] if x is None else x if isinstance(x, list) else [x]


def attr(d, k, default=""):
    return d.get(k) or d.get("@" + k) or default


def iter_items(sumario):
    """Recorre diario > seccion > departamento > (epigrafe >) item, tolerando objeto o lista."""
    for diario in aslist(sumario.get("diario")):
        for sec in aslist(diario.get("seccion")):
            cod = attr(sec, "codigo")
            for dep in aslist(sec.get("departamento")):
                dn = attr(dep, "nombre")
                for it in aslist(dep.get("item")):
                    yield cod, dn, "", it
                for ep in aslist(dep.get("epigrafe")):
                    for it in aslist(ep.get("item")):
                        yield cod, dn, attr(ep, "nombre"), it


def url_of(x):
    return x.get("texto", "") if isinstance(x, dict) else (x or "")


def strip_html(t):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


# ---------- extracción de datos de un documento ----------
def entidad(texto):
    m = re.search(r"\bdel? ((?:Ayuntamiento|Diputaci[oó]n|Consorcio|Cabildo|Consell|Comunidad|Gobierno|Generalitat|"
                  r"Mancomunidad|Consejo|Agencia|Principado|Ciudad)[^,.]{3,80}?)(?:,|\s+referente|\s+por la que|\s+por el que)", texto)
    return m.group(1).strip() if m else ""


def tipo_plaza(t):
    return "conductor" if re.search(r"conductor", t, re.I) else "especialista" if re.search(r"especialista", t, re.I) else "bombero"


def tipo_doc(t):
    t = t.lower()
    if "correcci" in t and "errores" in t: return "correccion"
    if re.search(r"lista (provisional|definitiva)? ?(de )?(aspirantes )?admitid", t): return "admitidos"
    if re.search(r"nombramiento|funcionarios? de carrera|toma de posesi", t): return "nombramiento"
    if re.search(r"calificaci|aprobad|resultado", t): return "resultados"
    if re.search(r"tribunal|fecha (de|del) (examen|comienzo)|celebraci", t): return "examen"
    return "convocatoria"


def plazas(t):
    m = re.search(r"(\d{1,3}|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+plazas?", t, re.I)
    if not m: return 0
    w = {"una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}
    v = m.group(1).lower()
    return int(v) if v.isdigit() else w.get(v, 0)


def plazo_estimado(texto, publicado):
    """'veinte días hábiles a partir del siguiente a la publicación' -> fecha estimada (sin festivos)."""
    m = re.search(r"(\d{1,2}|" + "|".join(NUM) + r")\s*(?:\(\d+\)\s*)?d[ií]as\s+(h[aá]biles|naturales)", texto, re.I)
    if not m: return None
    n = int(m.group(1)) if m.group(1).isdigit() else NUM[m.group(1).lower()]
    d = datetime.strptime(publicado, "%Y-%m-%d").date()
    if m.group(2).lower().startswith("n"):
        return (d + timedelta(days=n)).isoformat()
    while n:
        d += timedelta(days=1)
        if d.weekday() < 5:  # sábados y domingos inhábiles (Ley 39/2015); festivos no incluidos
            n -= 1
    return d.isoformat()


def build_doc(id_, fecha, titulo, url, texto, fuente):
    full = f"{titulo} {texto}"
    prov, cc = provincia(titulo, texto[:3000])
    return {"prov": prov, "cc": cc, "bop": ref_bop(texto), "id": id_, "fecha": fecha, "titulo": titulo, "url": url, "fuente": fuente,
            "entidad": entidad(titulo) or entidad(texto[:600]), "tipo": tipo_plaza(titulo + " " + texto[:1500]),
            "doc": tipo_doc(titulo), "plazas": plazas(titulo + " " + texto[:1500]),
            "grupo": (re.search(r"\b(?:grupo|subgrupo)\s*(C1|C2)\b", full, re.I) or [None, ""])[1].upper(),
            "sistema": ("Concurso-oposición" if re.search(r"concurso[- ]oposici", full, re.I) else
                        "Oposición" if re.search(r"oposici", full, re.I) else "Concurso"),
            "bolsa": bool(re.search(r"bolsa de (empleo|trabajo)", full, re.I)),
            "plazo": plazo_estimado(texto[:3000], fecha) if tipo_doc(titulo) == "convocatoria" else None}


# ---------- fuentes ----------
def fetch_boe(dia, seen, pausa):
    raw = http_get(BOE_SUMARIO.format(d=dia.strftime("%Y%m%d")), accept="application/json")
    if not raw: return []
    sumario = json.loads(raw).get("data", {}).get("sumario", {})
    out = []
    for cod, dep, _ep, it in iter_items(sumario):
        if cod not in SECCIONES or SKIP_DEPT.search(dep): continue
        id_, titulo = it.get("identificador", ""), it.get("titulo", "")
        if id_ in seen or not (KEYWORDS.search(titulo) or GENERIC.search(titulo)): continue
        url = url_of(it.get("url_html")) or url_of(it.get("url_pdf"))
        body = strip_html(http_get(url) or "") if it.get("url_html") else ""
        time.sleep(pausa)
        seen.add(id_)
        if KEYWORDS.search(titulo) or KEYWORDS.search(body):
            out.append(build_doc(id_, dia.isoformat(), titulo, url, body, "BOE"))
    return out


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child(it, k):
    return next((c for c in it if _local(c.tag) == k), None)


def _txt(c):
    return (c.text or "").strip() if c is not None else ""


def fetch_rss(src, seen):
    """Boletín provincial con RSS o Atom (ver bop_discover.py para localizar los feeds)."""
    raw = http_get(src["url"])
    if not raw: return []
    out = []
    for it in ET.fromstring(raw).iter():
        if _local(it.tag) not in ("item", "entry"): continue
        lc = _child(it, "link")
        t, l = _txt(_child(it, "title")), (lc.get("href") if lc is not None and lc.get("href") else _txt(lc))
        d = _txt(_child(it, "description")) or _txt(_child(it, "summary")) or _txt(_child(it, "content"))
        id_ = "rss-" + hashlib.md5(l.encode()).hexdigest()[:10]
        if id_ in seen or not KEYWORDS.search(t + " " + d): continue
        seen.add(id_)
        pub = _txt(_child(it, "pubDate")) or _txt(_child(it, "published")) or _txt(_child(it, "updated"))
        try: f = parsedate_to_datetime(pub).date().isoformat()
        except Exception:
            try: f = date.fromisoformat(pub[:10]).isoformat()
            except Exception: f = date.today().isoformat()
        out.append(build_doc(id_, f, t, l, strip_html(d), src["nombre"]))
    return out


# ---------- agrupar en fichas ----------
def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower().replace("ó", "o").replace("á", "a").replace("í", "i").replace("é", "e").replace("ú", "u")).strip("-")


def build(docs, overrides, hoy):
    fichas = {}
    for d in sorted(docs.values(), key=lambda x: x["fecha"]):
        key = overrides.get(d["id"]) or f"{slug(d['entidad'] or 'sin-entidad')}-{d['tipo']}"
        f = fichas.setdefault(key, {"id": key, "n": d["entidad"] or "Entidad sin identificar", "prov": "", "cc": "",
                                    "pl": 0, "tipo": d["tipo"], "g": "", "sis": "", "tasa": None, "bolsa": False,
                                    "plazo": None, "docs": [], "_o": 0})
        f["docs"].append({k: d[k] for k in ("id", "fecha", "doc", "titulo", "url", "fuente")})
        f["prov"] = d["prov"] or f["prov"]; f["cc"] = d["cc"] or f["cc"]; f["bop"] = d["bop"] or f.get("bop")
        f["pl"] = max(f["pl"], d["plazas"]); f["g"] = d["grupo"] or f["g"]
        f["sis"] = d["sistema"] if d["doc"] == "convocatoria" else f["sis"] or d["sistema"]
        f["bolsa"] = f["bolsa"] or d["bolsa"]; f["plazo"] = d["plazo"] or f["plazo"]
        if d["doc"] != "correccion": f["_o"] = max(f["_o"], ORDEN[d["doc"]])
        f["nov"] = {"convocatoria": "Convocatoria", "correccion": "Corrección de errores", "admitidos": "Lista de admitidos",
                    "examen": "Examen / tribunal", "resultados": "Resultados", "nombramiento": "Nombramiento"}[d["doc"]]
        f["nd"] = d["fecha"]
    out = []
    for f in fichas.values():
        o = f.pop("_o")
        if o == 0:
            f["fase"] = "previsto" if not f["plazo"] else "abierto" if hoy.isoformat() <= f["plazo"] else "cerrado"
        else:
            f["fase"] = FASE[o]
        f["plazo_estimado"] = bool(f["plazo"])
        out.append(f)
    return sorted(out, key=lambda x: x["nd"], reverse=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde"); ap.add_argument("--hasta"); ap.add_argument("--pausa", type=float, default=0.5)
    a = ap.parse_args()
    hoy = date.today()
    desde = date.fromisoformat(a.desde) if a.desde else hoy - timedelta(days=7)
    hasta = date.fromisoformat(a.hasta) if a.hasta else hoy
    DATA.mkdir(exist_ok=True)
    load = lambda p, dflt: json.loads(p.read_text()) if p.exists() else dflt
    docs = load(DATA / "docs.json", {}); seen = set(load(DATA / "seen.json", []))
    overrides = load(Path("overrides.json"), {}); sources = load(Path("sources.json"), [])
    dia = desde
    while dia <= hasta:
        for d in fetch_boe(dia, seen, a.pausa): docs[d["id"]] = d; print("BOE", d["fecha"], d["titulo"][:90])
        dia += timedelta(days=1)
    for s in sources:
        for d in fetch_rss(s, seen): docs[d["id"]] = d; print(s["nombre"], d["titulo"][:90])
    (DATA / "docs.json").write_text(json.dumps(docs, ensure_ascii=False, indent=1))
    (DATA / "seen.json").write_text(json.dumps(sorted(seen)))
    fichas = build(docs, overrides, hoy)
    (DATA / "convocatorias.json").write_text(json.dumps({"actualizado": hoy.isoformat(), "fichas": fichas}, ensure_ascii=False, indent=1))
    print(f"{len(docs)} documentos -> {len(fichas)} fichas")


if __name__ == "__main__":
    main()
