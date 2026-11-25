import json, radar_etl as r
from datetime import date
SUM={"data":{"sumario":{"diario":{"seccion":[{"codigo":"2B","departamento":{"nombre":"ADMINISTRACIÓN LOCAL","epigrafe":{"nombre":"x","item":[
 {"identificador":"BOE-A-1","titulo":"Resolución de 3 de noviembre de 2026, del Ayuntamiento de Motril (Granada), referente a la convocatoria para proveer seis plazas de Bombero.","url_html":{"texto":"http://x/1"},"url_pdf":{"texto":"p"}},
 {"identificador":"BOE-A-2","titulo":"Resolución de 3 de noviembre de 2026, del Ayuntamiento de Foo, referente a la convocatoria para proveer una plaza de administrativo.","url_html":"http://x/2"}]}}},
 {"codigo":"2B","departamento":[{"nombre":"UNIVERSIDAD X","item":[{"identificador":"U","titulo":"convocatoria plaza bombero"}]}]}]}}}}
BODIES={"http://x/1":"<p>Seis plazas, Grupo C1, sistema de oposición libre. Bases publicadas en el «Boletín Oficial de la Provincia de Granada» n.º 120, de 20 de octubre de 2026. Plazo: veinte días hábiles a partir del día siguiente a la publicación.</p>","http://x/2":"<p>administrativo</p>"}
def fake(url, accept=None, retries=3):
    return json.dumps(SUM) if "sumario" in url else BODIES.get(url)
r.http_get=fake
seen=set(); docs=r.fetch_boe(date(2026,11,4),seen,0)
assert len(docs)==1, docs
d=docs[0]; print(d)
assert d["entidad"]=="Ayuntamiento de Motril (Granada)" or d["entidad"].startswith("Ayuntamiento de Motril")
assert d["plazas"]==6 and d["grupo"]=="C1" and d["tipo"]=="bombero" and d["sistema"]=="Oposición"
assert d["plazo"]=="2026-12-02", d["plazo"]   # 20 hábiles desde 4-nov (sin festivos)
f=r.build({d["id"]:d},{},date(2026,11,25)); print(f[0]["fase"], f[0]["plazo"])
assert f[0]["fase"]=="abierto"
assert d["prov"]=="Granada" and d["cc"]=="Andalucía", (d["prov"],d["cc"])
assert d["bop"]=={"num":"120","fecha":"20 de octubre de 2026"}, d["bop"]
assert f[0]["prov"]=="Granada" and f[0]["bop"]["num"]=="120"
assert r.provincia("Resolución del Ayuntamiento de La Oliva (Las Palmas)")==("Las Palmas","Canarias")
print("OK")
