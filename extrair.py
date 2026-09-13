#!/usr/bin/env python3
"""
Recolhe horarios do portal Bullet do IPLeiria e gera dados.json.

Corre fora do browser, por isso nao ha CORS. Usa a configuracao publica do
proprio portal para obter as credenciais, de modo a continuar a funcionar se
o fornecedor as mudar.

    python extrair.py                 # usa cursos.txt
    python extrair.py --listar        # mostra todos os cursos disponiveis
    python extrair.py --todos         # inclui todos os cursos
"""
import argparse, collections, json, os, re, sys, urllib.parse, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CFG_URL = "https://ipleiria-publish.bulletscheduling.com/assets/config/app-settings.prod.json"
CURSOS_TXT = os.path.join(BASE, "cursos.txt")
SAIDA = os.path.join(BASE, "dados.json")
UA = {"User-Agent": "horarios-dei/1.0"}


def http(url, data=None, headers=None, metodo=None):
    h = dict(UA)
    h.update(headers or {})
    corpo = data.encode() if isinstance(data, str) else data
    req = urllib.request.Request(url, data=corpo, headers=h, method=metodo)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def sessao():
    """Devolve (api_base, cabecalhos_autenticados)."""
    cfg = http(CFG_URL)
    a = cfg["authConfig"]
    tok = http(a["issuer"] + "/connect/token",
               data=urllib.parse.urlencode({
                   "grant_type": a.get("grantType", "client_credentials"),
                   "client_id": a["clientId"],
                   "client_secret": a["clientSecret"],
                   "scope": a["scope"]}),
               headers={"Content-Type": "application/x-www-form-urlencoded"})
    if "access_token" not in tok:
        sys.exit("Nao foi possivel obter token: " + json.dumps(tok)[:200])
    return cfg["apiBaseUrl"], {
        "Authorization": "Bearer " + tok["access_token"],
        "Content-Type": "application/json",
        "Accept": "application/json"}


def procura(api, cab, rota, filtros=None):
    corpo = {"page": 0, "pageSize": 0, "sorts": [],
             "filters": filtros or [], "groups": [], "aggregates": []}
    r = http(api + rota, data=json.dumps(corpo), headers=cab)
    return r["data"]["data"]


# ---------------------------------------------------------------- cursos.txt
CABECALHO = """# Cursos a incluir no horario.
# Uma linha por curso, com o ID no inicio. Comenta com # para excluir.
# Corre  python extrair.py --listar  para veres todos os disponiveis.
"""


def le_cursos():
    if not os.path.exists(CURSOS_TXT):
        return None
    ids = []
    for linha in open(CURSOS_TXT, encoding="utf-8"):
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        m = re.match(r"(\d+)", linha)
        if m:
            ids.append(int(m.group(1)))
    return ids


def escreve_cursos(cursos, escolhidos):
    with open(CURSOS_TXT, "w", encoding="utf-8") as f:
        f.write(CABECALHO)
        for c in sorted(cursos, key=lambda c: (c["acr"] or "", c["name"])):
            marca = "" if c["id"] in escolhidos else "# "
            f.write(f'{marca}{c["id"]}  {c["acr"]}  {c["name"]}\n')


def seccao(nome):
    n = nome.lower()
    if "tecnico superior" in n or "técnico superior" in n:
        return "Tecnicos Superiores Profissionais"
    if "mestrado" in n or "master" in n:
        return "Mestrados"
    if "pos-grad" in n or "pós-grad" in n:
        return "Pos-graduacoes"
    if "doutoramento" in n or "phd" in n:
        return "Doutoramentos"
    return "Licenciaturas"


ORDEM_SEC = ["Licenciaturas", "Mestrados", "Tecnicos Superiores Profissionais",
             "Pos-graduacoes", "Doutoramentos"]


def regime(nome):
    m = re.search(r"[-\u2013]?\s*\((D|PL|ING)\)", nome)
    if m:
        limpo = (nome[:m.start()] + nome[m.end():]).replace("  ", " ")
        return m.group(1), limpo.strip(" -\u2013")
    m = re.search(r"\|\s*(D|PL)\s*\|", nome)
    return (m.group(1) if m else ""), nome


def mins(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


# ------------------------------------------------------------ transformacao
def constroi(grupos, eventos, semanas, cursos_sel):
    PLANOS = {}
    for g in grupos:
        p = g.get("curricularPlan")
        if p:
            PLANOS[p["id"]] = p
    GRP = {g["id"]: g for g in grupos}
    SEC = {c["id"]: seccao(c["name"]) for c in cursos_sel}
    IDS = set(SEC)

    wids = sorted({w["id"] for w in semanas})
    WBIT = {w: 1 << i for i, w in enumerate(wids)}
    mask = lambda ws: sum(WBIT.get(w, 0) for w in set(ws))

    def ctx(e):
        out = set()
        for gid in e["g"]:
            g = GRP.get(gid)
            if g and g.get("curricularPlan"):
                p = g["curricularPlan"]
                out.add((p["course"]["id"], p["year"], p["id"]))
        return out

    # 1. fundir aulas iguais do mesmo turno (docentes/semanas diferentes)
    fundidas = {}
    for e in eventos:
        k = (e["mod"], e["typ"], e["wls"], e["day"], e["s"], e["e"])
        m = fundidas.get(k)
        if m is None:
            fundidas[k] = m = {"mod": e["mod"], "typ": e["typ"], "wls": e["wls"],
                               "day": e["day"], "s": mins(e["s"]), "e": mins(e["e"]),
                               "rooms": [], "teachers": [], "weeks": set(),
                               "n": e["n"], "ann": [], "ctx": set(), "gids": set()}
        m["rooms"] += [r for r in e["r"] if r not in m["rooms"]]
        m["teachers"] += [t for t in e["t"] if t not in m["teachers"]]
        m["weeks"] |= set(e["w"])
        if e["ann"] and e["ann"] not in m["ann"]:
            m["ann"].append(e["ann"])
        m["ctx"] |= ctx(e)
        m["gids"] |= set(e["g"])

    # 2. agrupar sessoes em turnos (UC, tipologia, wls)
    turnos = collections.defaultdict(list)
    for m in fundidas.values():
        turnos[(m["mod"], m["typ"], m["wls"])].append(m)

    TL = []
    for (mod, typ, wls), sess in sorted(turnos.items()):
        sess.sort(key=lambda x: (x["day"], x["s"]))
        cset, yset, gset, tset = set(), set(), set(), []
        for s in sess:
            for cid, yr, _ in s["ctx"]:
                cset.add(cid)
                yset.add((cid, yr))
            gset |= s["gids"]
            for t in s["teachers"]:
                if t not in tset:
                    tset.append(t)
        if not (cset & IDS):
            continue
        TL.append({
            "mod": mod, "typ": typ, "wls": wls,
            "c": sorted(cset & IDS),
            "y": sorted(f"{c}:{y}" for c, y in yset if c in IDS),
            "g": sorted(gset), "tt": tset,
            "ss": [{"d": s["day"], "a": s["s"], "b": s["e"], "r": s["rooms"],
                    "t": s["teachers"], "w": len(s["weeks"]), "wm": mask(s["weeks"]),
                    "n": s["n"], "an": s["ann"]} for s in sess]})
    for i, t in enumerate(TL):
        t["k"] = i
    return TL, PLANOS, GRP, SEC, len(wids)


# -------------------------------------------------------------------- saida
def escreve(caminho, grupos, brutos, semanas, sel):
    import datetime
    TL, PLANOS, GRP, SEC, nw = constroi(grupos, brutos, semanas, sel)

    cursos = []
    for c in sel:
        planos = sorted([p for p in PLANOS.values()
                         if p.get("course") and p["course"]["id"] == c["id"]],
                        key=lambda p: (p["year"], p["name"]))
        anos = sorted({p["year"] for p in planos})
        if not any(y.startswith(f'{c["id"]}:') for t in TL for y in t["y"]):
            continue
        reg, fam = regime(c["name"])
        cursos.append({
            "id": c["id"], "acr": c["acr"], "name": c["name"],
            "sec": SEC[c["id"]], "reg": reg or "D", "fam": fam,
            "famAcr": re.sub(r"_(PL|D)$", "", c["acr"]),
            "years": anos,
            "plans": [{"id": p["id"], "n": p["name"], "y": p["year"]} for p in planos]})
    cursos.sort(key=lambda c: (ORDEM_SEC.index(c["sec"]) if c["sec"] in ORDEM_SEC else 9,
                               c["famAcr"], c["reg"]))

    por_grupo = collections.defaultdict(list)
    for t in TL:
        for gid in t["g"]:
            por_grupo[gid].append(t["k"])

    validos = {c["id"] for c in cursos}
    presets = []
    for gid, ks in sorted(por_grupo.items()):
        g = GRP.get(gid)
        p = g and g.get("curricularPlan")
        if not p or not p.get("course") or p["course"]["id"] not in validos:
            continue
        presets.append({"g": gid, "n": g["name"], "c": p["course"]["id"],
                        "y": p["year"], "p": p["id"], "k": sorted(ks)})

    app = {"gerado": datetime.datetime.now(datetime.timezone.utc)
                      .strftime("%Y-%m-%d %H:%M UTC"),
           "nw": nw, "courses": cursos, "turnos": TL, "presets": presets}

    # se so o carimbo de data mudou, deixa o ficheiro como esta: assim o git
    # nao regista alteracoes e nao se acumulam commits sem conteudo novo
    if os.path.exists(caminho):
        try:
            antigo = json.load(open(caminho, encoding="utf-8"))
            a, b = dict(antigo), dict(app)
            a.pop("gerado", None)
            b.pop("gerado", None)
            if a == b:
                print(f"sem alteracoes nos horarios (ultima recolha: {antigo.get('gerado','?')})")
                return False
        except Exception:
            pass

    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(app, f, ensure_ascii=False, separators=(",", ":"))
    print(f"cursos:  {len(cursos)}")
    print(f"turnos:  {len(TL)}")
    print(f"turmas:  {len(presets)}")
    print(f"escrito: {caminho} ({os.path.getsize(caminho):,} bytes)")
    return True


# -------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listar", action="store_true", help="mostra os cursos disponiveis e sai")
    ap.add_argument("--todos", action="store_true", help="inclui todos os cursos")
    ap.add_argument("--saida", default=SAIDA)
    args = ap.parse_args()

    api, cab = sessao()
    print("token obtido")

    grupos = procura(api, cab, "/StudentGroups/search")
    print(f"turmas: {len(grupos)}")

    cursos = {}
    for g in grupos:
        p = g.get("curricularPlan")
        if not p or not p.get("course"):
            continue
        c = p["course"]
        cursos.setdefault(c["id"], {
            "id": c["id"],
            "acr": (c.get("acronym") or "").replace("ESTG - ", "").replace("ESTG-", ""),
            "name": c["name"]})
    print(f"cursos no portal: {len(cursos)}")

    if args.listar:
        for c in sorted(cursos.values(), key=lambda c: (c["acr"], c["name"])):
            print(f'  {c["id"]:5d}  {c["acr"]:14s}  {c["name"]}')
        return

    ids = None if args.todos else le_cursos()
    if ids is None and not args.todos:
        escreve_cursos(cursos.values(), set())
        sys.exit(f"Criei {CURSOS_TXT}. Descomenta os cursos que queres e corre outra vez.")
    if args.todos:
        ids = list(cursos)
    sel = [cursos[i] for i in ids if i in cursos]
    if not sel:
        sys.exit("Nenhum curso valido em cursos.txt")
    print(f"cursos escolhidos: {len(sel)}")

    gids = [g["id"] for g in grupos
            if g.get("curricularPlan") and g["curricularPlan"].get("course")
            and g["curricularPlan"]["course"]["id"] in {c["id"] for c in sel}]

    # eventos, em lotes para nao criar pedidos gigantes
    brutos, vistos = [], set()
    for i in range(0, len(gids), 300):
        lote = gids[i:i + 300]
        for x in procura(api, cab, "/EventPublished/search", [
                {"and": True, "type": 10, "path": "EventData.EventType.Id", "value": [2, 9]},
                {"and": True, "type": 10, "path": "EventData.StudentGroups.Id", "value": lote}]):
            e = x["eventData"]
            if e["id"] in vistos:
                continue
            vistos.add(e["id"])
            brutos.append({
                "mod": (e.get("module") or {}).get("name") or "",
                "typ": "/".join((t.get("acronym") or t.get("name") or "")
                                for t in (e.get("typologies") or [])),
                "wls": e.get("wlsSectionName") or e.get("name") or "",
                "day": e["day"], "s": e["startTime"], "e": e["endTime"],
                "r": [c.get("name") or c.get("code") or "" for c in (e.get("classrooms") or [])],
                "t": [t.get("name") or "" for t in (e.get("teachers") or [])],
                "g": [g["id"] for g in (e.get("studentGroups") or [])],
                "w": [w["id"] for w in (e.get("weeks") or [])],
                "n": e.get("numStudents") or 0, "ann": e.get("annotations") or ""})
    print(f"aulas: {len(brutos)}")
    semanas = [{"id": w} for w in sorted({w for e in brutos for w in e["w"]})]
    print(f"semanas: {len(semanas)}")
    escreve(args.saida, grupos, brutos, semanas, sel)


if __name__ == "__main__":
    main()
