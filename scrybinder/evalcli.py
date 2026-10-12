"""`scrybinder-eval`: measures accuracy (printing and illustration level) and tunes weights. Sets:
dev   captures from scan_log (truth = the user's choice)
tune  synthetic photos (seed 1) to tune weights · synth synthetic photos (seed 2) to measure
final HTML sheet with the photos in data/test-photos-final and the prediction; the user marks the wrong ones (no answer key)
"""
import argparse
import base64
import itertools
import json
import random
import sys
from pathlib import Path

import cv2

from . import db as dbmod, scryfall
from .scan import visual
from .scan.identify import Identifier
from .scan.session import decode, identify_image
from .scan.synth import photo

ROOT = Path(__file__).resolve().parent.parent
ERAS = ("1993", "1997", "2003", "2015", "future", "borderless")


def _synth_samples(db, ids, n, seed):
    """n cards from the index, stratified by era (from the `large` image, different from the one used in the index)."""
    rng = random.Random(seed)
    by_era: dict[str, list[str]] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for r in db.execute(f"SELECT id, frame, border_color FROM cards WHERE id IN ({','.join('?' * len(chunk))})", chunk):
            by_era.setdefault("borderless" if r["border_color"] == "borderless" else r["frame"], []).append(r["id"])
    eras = [e for e in ERAS if by_era.get(e)]
    return [(eras[i % len(eras)], None, rng.randrange(10**6)) for i in range(n)], by_era, rng


def _synth_photo(db, cid, seed):
    p = scryfall.image_path(db, cid, "large")
    return None if p is None else photo(p, seed=seed, size=(3000, 2000), noise=6, blur=1.6)  # ≈ resolution of real photos (24 MP camera, downscaled to 3000)


def _rank(cands, w):
    return sorted(cands, key=lambda c: w["art"] * c.get("art", 0) + w["card"] * c.get("card", 0)
                  + w["name"] * c.get("name_score", 0) / 100 + w["pts"] * c.get("score", 0) + c.get("prior", 0), reverse=True)  # (no 'rescue': grid search only)


def _ill(db, cid):
    r = db.execute("SELECT illustration_id FROM cards WHERE id=?", (cid,)).fetchone()
    return r[0] if r else None


def _report(db, samples):
    groups: dict[str, list] = {}
    for g, truth, res in samples:
        groups.setdefault(g, []).append((truth, res))
        groups.setdefault("TOTAL", []).append((truth, res))
    for g, items in groups.items():
        n = len(items)
        top1 = sum(1 for t, r in items if r["candidates"] and r["candidates"][0]["id"] == t)
        top5 = sum(1 for t, r in items if t in [c["id"] for c in r["candidates"][:5]])
        ill1 = sum(1 for t, r in items if r["candidates"] and _ill(db, r["candidates"][0]["id"]) == _ill(db, t))
        print(f"{g:>10}: n={n:3d}  top1(printing)={top1 / n:6.1%}  top1(illustration)={ill1 / n:6.1%}  top5={top5 / n:6.1%}")
    by_conf: dict[str, list[bool]] = {}
    for _, truth, res in samples:
        by_conf.setdefault(res["confidence"], []).append(bool(res["candidates"]) and res["candidates"][0]["id"] == truth)
    print("  by confidence:", ", ".join(f"{k}: {sum(v)}/{len(v)}" for k, v in sorted(by_conf.items())))
    for g, truth, res in samples:
        if not res["candidates"] or res["candidates"][0]["id"] != truth:
            c = db.execute("SELECT name, set_code, collector_number FROM cards WHERE id=?", (truth,)).fetchone()
            got = res["candidates"][0] if res["candidates"] else None
            print(f"  x [{g}] esperado {c['name']} {c['set_code']} #{c['collector_number']} | obtido "
                  + (f"{got.get('name', got['id'])} {got.get('set_code', '')} #{got.get('collector_number', '')} ({res['confidence']})" if got else "nada"))


def _grid(samples):
    base = visual.weights()
    out = []
    for wc, wn, wp in itertools.product((0.0, 0.25, 0.5, 1.0), (0.0, 0.15, 0.3, 0.6), (0.0, 0.025, 0.05, 0.1)):
        w = {**base, "card": wc, "name": wn, "pts": wp}
        out.append((sum(1 for _, t, r in samples if (rk := _rank(r["candidates"], w)) and rk[0]["id"] == t), w))
    out.sort(key=lambda x: -x[0])
    for ok, w in out[:6]:
        print(f"  {ok}/{len(samples)}  card={w['card']} name={w['name']} pts={w['pts']}")


def _visual_only(ident, img):
    """Visual branch only (detection + art/card), ordered by the weights; no OCR. For fast iteration on the index."""
    from .scan.vision import card_from_photo
    w = visual.weights()
    scores, top_art, _ = ident.vis().best_orientation(card_from_photo(img)[0], w, try_rotated=True)
    cands = [{"id": k, "art": a, "card": c} for k, (a, c) in scores.items()]
    return {"candidates": _rank(cands, w)[:40], "confidence": "-", "top_art": top_art}


def _final_sheet(db, ident):
    thumb_h = 360

    def b64(m):
        return base64.b64encode(cv2.imencode(".jpg", m, [cv2.IMWRITE_JPEG_QUALITY, 80])[1]).decode()

    items, results = [], {}
    for p in sorted((ROOT / "data" / "test-photos-final").glob("*")):
        if p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        img = decode(p.read_bytes())
        res = identify_image(ident, img)[2]
        top = res["candidates"][0] if res["candidates"] else None
        pred = None
        if top and (ip := scryfall.image_path(db, top["id"], "normal")):
            pred = cv2.imread(str(ip))
        sc = lambda m: cv2.resize(m, None, fx=thumb_h / m.shape[0], fy=thumb_h / m.shape[0], interpolation=cv2.INTER_AREA)  # noqa: E731
        items.append({"f": p.name, "photo": b64(sc(img)), "pred": b64(sc(pred)) if pred is not None else "",
                      "name": top["name"] if top else "-", "set": f"{top['set_code']} #{top['collector_number']}" if top else "",
                      "conf": res["confidence"],
                      "pid": top["id"] if top else None,
                      "cands": [{"id": c["id"], "t": f"{c['name']} {c['set_code']} #{c['collector_number']}"} for c in res["candidates"][:12]]})
        results[p.name] = (top["id"] if top else None, [c["id"] for c in res["candidates"][:5]])
        print(p.name, items[-1]["name"], items[-1]["set"], items[-1]["conf"], flush=True)
    out = ROOT / "data" / "eval" / "final.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(_HTML.replace("__DATA__", json.dumps(items)), encoding="utf-8")
    (out.parent / "final.json").write_text(json.dumps([{k: v for k, v in i.items() if k not in ("photo", "pred")} for i in items]),
                                           encoding="utf-8")
    print("folha:", out)
    _truth_report(db, results)


TRUTH = ROOT / "data" / "eval" / "truth-final.json"


def import_corrections(db, path):
    """Corrections pasted from the sheet → data/eval/truth-final.json {photo: scryfall_id}. Uncorrected photos keep the
    reviewed prediction. Free text 'name set number [lang]' is resolved against the database; what cannot be is listed."""
    truth = {}
    for c in json.loads(Path(path).read_text(encoding="utf-8-sig")):
        if c.get("bad") is False:  # new format: the prediction the user saw and accepted (independent of final.json)
            if c.get("pred"):
                truth[c["f"]] = c["pred"]
            continue
        tid = c.get("truth_id")
        if not tid and c.get("text", "").strip():
            tid = _resolve(db, c["text"])
        if tid:
            truth[c["f"]] = tid
        else:
            print("unresolved:", c["f"], repr(c.get("text")))  # wrong without the right one: counts neither way
    TRUTH.write_text(json.dumps(truth), encoding="utf-8")
    print(len(truth), "photos with ground truth in", TRUTH)


def _resolve(db, text):
    toks = text.replace("#", " ").split()
    for n in range(len(toks) - 1, 0, -1):  # 'name ... set number [lang]': try prefixes from the end to the start
        name, rest = " ".join(toks[:n]), toks[n:]
        rows = db.execute("SELECT id, set_code, collector_number, lang FROM cards WHERE UPPER(name)=UPPER(?) AND digital=0", (name,)).fetchall()
        if rows:
            low = [t.lower() for t in rest]
            hit = [r for r in rows if r["set_code"] in low and r["collector_number"].lower() in low]
            hit.sort(key=lambda r: r["lang"] not in low and r["lang"] != "en")  # honour the language if given in the text, otherwise en first
            return hit[0]["id"] if hit else None
    return None


def _truth_report(db, results):
    if not TRUTH.exists():
        return
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    ok = [f for f, (pid, top5) in results.items() if f in truth and pid == truth[f]]
    n = sum(1 for f in results if f in truth)
    t5 = sum(1 for f, (_, top5) in results.items() if f in truth and truth[f] in top5)
    print(f"ground truth of the final photos: top1 {len(ok)}/{n} ({len(ok) / max(n, 1):.1%}) top5 {t5}/{n}")
    for f, (pid, _) in sorted(results.items()):
        if f in truth and pid != truth[f]:
            e = db.execute("SELECT name, set_code, collector_number FROM cards WHERE id=?", (truth[f],)).fetchone()
            g = db.execute("SELECT name, set_code, collector_number FROM cards WHERE id=?", (pid,)).fetchone()
            print(f"  x {f}: esperado {e['name']} {e['set_code']} #{e['collector_number']} | obtido " + (f"{g['name']} {g['set_code']} #{g['collector_number']}" if g else "-"))


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # names with ★ or accents in the Windows terminal
    ap = argparse.ArgumentParser(prog="scrybinder-eval")
    ap.add_argument("--set", choices=["dev", "tune", "synth", "final"])
    ap.add_argument("-n", type=int, default=120)
    ap.add_argument("--grid", action="store_true", help="grelha de pesos sobre as amostras recolhidas (use em dev/tune)")
    ap.add_argument("--no-visual", action="store_true", help="OCR-only mode (baseline for comparison)")
    ap.add_argument("--visual-only", action="store_true", help="art+card only (no OCR): fast iteration on the index")
    ap.add_argument("--import-corrections", metavar="JSON", help="import the corrections pasted from the final sheet")
    ap.add_argument("--seed", type=int, default=0, help="seed for the synthetic photos (0 = the set default)")
    a = ap.parse_args(argv)
    db = dbmod.connect()
    if a.import_corrections:
        return import_corrections(db, a.import_corrections)
    if not a.set:
        ap.error("--set ou --import-corrections")
    ident = Identifier(db, use_visual=not a.no_visual)
    vis = ident.vis()
    print("visual:", f"{len(vis.ix)} linhas" if vis else "desligado (fase 2)")
    samples = []  # (grupo, id verdadeiro, resultado)
    if a.set == "dev":
        for r in db.execute("SELECT capture_path, final_id FROM scan_log WHERE final_id IS NOT NULL"):
            img = cv2.imread(r["capture_path"])
            if img is not None:
                samples.append(("capturas", r["final_id"], ident.identify(img)))
        for p in sorted((ROOT / "data" / "test-photos").glob("*.JPG")):  # full real photos (detection + OCR + visual)
            res = identify_image(ident, decode(p.read_bytes()))[2]
            print(p.name, "->", res["candidates"][0]["name"] if res["candidates"] else "-", res["confidence"])
    elif a.set in ("tune", "synth"):
        if not vis:
            sys.exit("the visual index is required")
        picks, by_era, rng = _synth_samples(db, list({r["card_id"] for r in vis.ix.rows}), a.n, a.seed or (1 if a.set == "tune" else 2))
        for era, _, seed in picks:
            cid = rng.choice(by_era[era])
            img = _synth_photo(db, cid, seed)
            if img is not None:
                samples.append((era, cid, _visual_only(ident, img) if a.visual_only else identify_image(ident, img)[2]))
    else:
        return _final_sheet(db, ident)
    _report(db, samples)
    if a.grid:
        _grid(samples)


_HTML = """<!doctype html><meta charset=utf-8><title>Scrybinder - final review</title>
<style>body{font:14px system-ui;background:#111;color:#eee;margin:16px}.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(560px,1fr));gap:12px}
.c{background:#1c1c1c;border:2px solid #333;border-radius:8px;padding:8px}.c.bad{border-color:#e55}.c img{height:260px;margin-right:6px;border-radius:6px}
small{color:#999}button{font-size:15px;padding:6px 12px;cursor:pointer}select,input{width:100%;margin-top:4px;padding:4px;background:#222;color:#eee;border:1px solid #444}
.fix{display:none;margin-top:6px}.bad .fix{display:block}</style>
<h2>Wrong? Click "Wrong" and pick the right printing (or type it). <span id=n></span></h2>
<button onclick="out()">Copy corrections (JSON)</button> <small>paste the result back</small><div class=g id=g></div>
<script>const D=__DATA__;const S=JSON.parse(localStorage.getItem('scrybinder-final')||'{}');
const save=()=>localStorage.setItem('scrybinder-final',JSON.stringify(S));
function r(){const bad=D.filter(x=>S[x.f]&&S[x.f].bad).length;document.getElementById('n').textContent=(D.length-bad)+'/'+D.length+' correct'}
function out(){const o=D.map(x=>({f:x.f,pred:x.pid,bad:!!(S[x.f]&&S[x.f].bad),truth_id:(S[x.f]&&S[x.f].id)||null,text:(S[x.f]&&S[x.f].text)||''}));
 navigator.clipboard.writeText(JSON.stringify(o));alert(o.filter(x=>x.bad).length+' corrections copied (of '+o.length+')')}
D.forEach(x=>{const st=S[x.f]=S[x.f]||{};const d=document.createElement('div');d.className='c'+(st.bad?' bad':'');
 d.innerHTML='<img src="data:image/jpeg;base64,'+x.photo+'"><img src="data:image/jpeg;base64,'+x.pred+'"><div><b>'+x.name+'</b> '+x.set+' <small>('+x.conf+') '+x.f+'</small></div>'+
 '<div><button class=b>'+(st.bad?'Wrong (click to undo)':'Wrong')+'</button></div><div class=fix><select><option value="">- the right one is... -</option>'+
 x.cands.map(c=>'<option value="'+c.id+'">'+c.t+'</option>').join('')+'</select><input placeholder="or type: name  set  number (e.g. Reprieve soa 74 ja)"></div>';
 const sel=d.querySelector('select'),inp=d.querySelector('input'),btn=d.querySelector('.b');sel.value=st.id||'';inp.value=st.text||'';
 btn.onclick=()=>{st.bad=!st.bad;d.classList.toggle('bad',st.bad);btn.textContent=st.bad?'Wrong (click to undo)':'Wrong';save();r()};
 sel.onchange=()=>{st.id=sel.value;save()};inp.oninput=()=>{st.text=inp.value;save()};
 document.getElementById('g').appendChild(d)});r()</script>"""


if __name__ == "__main__":
    main()
