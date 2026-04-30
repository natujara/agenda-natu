"""
La agenda de natu (extendida) — Scraper v2
============================================
Fuentes:
  · Ticketek
  · All Access
  · Passline
  · TicketPass
  · LivePass
  · TuEntrada
  · Alpogo
  · MiAnticipada
  · RgEntradas
  · Plateanet
  · CatPass
  · Teatro Argentino (calendario oficial)

Genera shows.json consumido por la página web.
Corre automáticamente cada 6hs via GitHub Actions.

Instalación: pip install requests beautifulsoup4
"""

import json, re, time, logging
from datetime import datetime
from pathlib import Path
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("natu")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "es-AR,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

LP_KW = [
    "la plata","berisso","ensenada","gonnet","tolosa","city bell",
    "villa elisa","ringuelet","teatro argentino","estadio estudiantes",
    "estadio gimnasia","coliseo podestá","pasaje dardo rocha","coliseo podesta",
]

CAT_KW = {
    "recital":  ["recital","concierto","música","rock","jazz","cumbia","tango","folk","metal","pop","indie","show en vivo","show musical","orquesta","sinfónico"],
    "teatro":   ["teatro","obra","dramaturgia","monólogo","dramático","ópera","opera","lírico"],
    "festival": ["festival","feria","encuentro cultural","ciclo"],
    "standup":  ["stand-up","stand up","humor","comedia","comediante"],
    "danza":    ["danza","ballet","tango show","circo","acrobacia"],
    "cine":     ["cine","película","film","proyección","cinemato"],
    "arte":     ["expo","exposición","muestra","arte","galería","fotografía","instalación"],
    "infantil": ["infantil","niños","familiar","kids","bebés","familia"],
}

def detect_cat(title, desc=""):
    text = (title+" "+desc).lower()
    for cat, kws in CAT_KW.items():
        if any(k in text for k in kws):
            return cat
    return "otro"

def is_lp(text):
    t = text.lower()
    return any(k in t for k in LP_KW)

def pause(): time.sleep(2)

# ──────────────────────────────────────────
# TEATRO ARGENTINO — scraping directo HTML
# Es la fuente más confiable porque es HTML estático y local
# ──────────────────────────────────────────
def scrape_teatro_argentino():
    events = []
    log.info("Teatro Argentino → iniciando…")
    url = "https://teatroargentino.gba.gob.ar/meets/no-season"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        # Cada evento está en un bloque con <h5> para el título
        # y párrafos de texto con fecha e ícono de ubicación
        # Estructura real observada:
        # <h5>Nombre del evento</h5>
        # texto: DD/MM/YYYY HH:MM
        # texto: Sala (venue)
        # <a href="/meet/ID">+ INFO</a>
        # <img src="..."> (flyer)

        blocks = soup.find_all("h5")
        for h5 in blocks:
            try:
                title = h5.get_text(strip=True)
                if not title or len(title) < 3:
                    continue

                # El contenido relevante está en el mismo contenedor padre
                parent = h5.parent

                # Fecha: buscamos un patrón DD/MM/YYYY HH:MM en el texto del bloque
                block_text = parent.get_text(" ", strip=True)
                date_str, time_str = "", ""
                m = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})", block_text)
                if m:
                    date_str = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
                    time_str = f"{m.group(4)}:{m.group(5)}"

                # Venue: texto que sigue al ícono de ubicación (segundo párrafo de info)
                # En el HTML real aparece como texto plano después de la imagen del ícono
                venue = "Teatro Argentino"
                # Intentamos extraer la sala específica (Ginastera, Piazzolla, etc.)
                sala_m = re.search(r"(Alberto Ginastera|Astor Piazzolla|Sala [A-Z][a-záéíóú]+)", block_text)
                if sala_m:
                    venue = f"Teatro Argentino — Sala {sala_m.group(1).replace('Alberto Ginastera','Ginastera').replace('Astor Piazzolla','Piazzolla')}"

                # Link: /meet/ID → URL completa
                link_el = parent.find("a", href=re.compile(r"/meet/\d+"))
                link = f"https://teatroargentino.gba.gob.ar{link_el['href']}" if link_el else url

                # Flyer
                img_el = parent.find("img", src=re.compile(r"/uploads/"))
                flyer = f"https://teatroargentino.gba.gob.ar{img_el['src']}" if img_el else ""

                events.append({
                    "title":     title[:120],
                    "cat":       detect_cat(title),
                    "date":      date_str,
                    "time":      time_str,
                    "venue":     venue,
                    "city":      "La Plata",
                    "source":    "Teatro Argentino",
                    "sourceKey": "teatroargentino",
                    "url":       link,
                    "flyer":     flyer,
                })
            except Exception as e:
                log.debug(f"Teatro Argentino bloque error: {e}")

    except Exception as e:
        log.error(f"Teatro Argentino: {e}")

    log.info(f"Teatro Argentino → {len(events)} eventos")
    return events


# ──────────────────────────────────────────
# HELPER genérico para ticketeras HTML
# ──────────────────────────────────────────
def scrape_generic_html(name, urls, source_key, base_url,
                        title_sel, date_sel, venue_sel, link_sel, img_sel,
                        title_prefix="", filter_lp=True):
    events = []
    log.info(f"{name} → iniciando…")
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(r.text, "html.parser")

            # Detectar cards con varios selectores posibles
            cards = []
            for sel in [".event-card",".evento",".evento-item","article","[class*='event']",".card",".show-item","li"]:
                cards = soup.select(sel)
                if len(cards) > 2:
                    log.info(f"{name}: {len(cards)} cards con '{sel}'")
                    break

            for card in cards:
                try:
                    t_el = card.select_one(title_sel) if title_sel else card.select_one("h1,h2,h3,h4,.title,.name,[class*='title'],[class*='name']")
                    title = (title_prefix + t_el.get_text(strip=True)) if t_el else ""
                    if not title or len(title) < 3:
                        continue

                    d_el = card.select_one(date_sel) if date_sel else card.select_one("[class*='date'],[class*='fecha'],time")
                    v_el = card.select_one(venue_sel) if venue_sel else card.select_one("[class*='venue'],[class*='lugar'],[class*='location']")
                    l_el = card.select_one(link_sel) if link_sel else card.select_one("a[href]")
                    i_el = card.select_one(img_sel) if img_sel else card.select_one("img[src]")

                    venue_txt = v_el.get_text(strip=True) if v_el else ""
                    date_txt  = d_el.get_text(strip=True) if d_el else ""

                    if filter_lp:
                        full = title + " " + venue_txt + " " + card.get_text()
                        if not is_lp(full):
                            continue

                    href = ""
                    if l_el:
                        href = l_el.get("href","")
                        if href.startswith("/"):
                            href = base_url + href

                    img_src = ""
                    if i_el:
                        img_src = i_el.get("src", i_el.get("data-src",""))
                        if img_src.startswith("/"):
                            img_src = base_url + img_src

                    events.append({
                        "title":     title[:120],
                        "cat":       detect_cat(title),
                        "date":      parse_date(date_txt),
                        "time":      parse_time(date_txt),
                        "venue":     venue_txt[:100],
                        "city":      "La Plata",
                        "source":    name,
                        "sourceKey": source_key,
                        "url":       href or base_url,
                        "flyer":     img_src if img_src.startswith("http") else "",
                    })
                except Exception as e:
                    log.debug(f"{name} card error: {e}")

            pause()
        except Exception as e:
            log.error(f"{name} URL {url}: {e}")

    log.info(f"{name} → {len(events)} eventos de La Plata")
    return events


# ──────────────────────────────────────────
# TICKETERAS INDIVIDUALES
# ──────────────────────────────────────────

def scrape_ticketek():
    return scrape_generic_html("Ticketek",
        ["https://www.ticketek.com.ar/shows/shows.aspx","https://www.ticketek.com.ar/shows/shows.aspx?prov=BUE"],
        "ticketek","https://www.ticketek.com.ar",
        "h2,h3,h4,.show-name,.title",None,None,None,None)

def scrape_allaccess():
    return scrape_generic_html("All Access",
        ["https://www.allaccess.com.ar/eventos","https://www.allaccess.com.ar/eventos?ciudad=la-plata"],
        "allaccess","https://www.allaccess.com.ar",
        None,None,None,None,None)

def scrape_ticketpass():
    return scrape_generic_html("TicketPass",
        ["https://ticketpass.com.ar/eventos","https://ticketpass.com.ar/eventos?ciudad=la-plata"],
        "ticketpass","https://ticketpass.com.ar",
        None,None,None,None,None)

def scrape_livepass():
    return scrape_generic_html("LivePass",
        ["https://www.livepass.com.ar/eventos","https://www.livepass.com.ar/eventos?ciudad=la-plata"],
        "livepass","https://www.livepass.com.ar",
        None,None,None,None,None)

def scrape_tuentrada():
    return scrape_generic_html("TuEntrada",
        ["https://tuentrada.com/eventos","https://tuentrada.com/eventos?ciudad=la-plata"],
        "tuentrada","https://tuentrada.com",
        None,None,None,None,None)

def scrape_alpogo():
    return scrape_generic_html("Alpogo",
        ["https://alpogo.com/eventos","https://alpogo.com/search?q=la+plata"],
        "alpogo","https://alpogo.com",
        None,None,None,None,None)

def scrape_mianticipada():
    return scrape_generic_html("MiAnticipada",
        ["https://mianticipada.com/eventos","https://mianticipada.com/eventos?ciudad=la-plata"],
        "mianticipada","https://mianticipada.com",
        None,None,None,None,None)

def scrape_rgentradas():
    return scrape_generic_html("RgEntradas",
        ["https://rgentradas.com/eventos","https://rgentradas.com/eventos?ciudad=la-plata"],
        "rgentradas","https://rgentradas.com",
        None,None,None,None,None)

def scrape_plateanet():
    return scrape_generic_html("Plateanet",
        ["https://www.plateanet.com/eventos","https://www.plateanet.com/eventos?ciudad=la-plata"],
        "plateanet","https://www.plateanet.com",
        None,None,None,None,None)

def scrape_catpass():
    return scrape_generic_html("CatPass",
        ["https://catpass.com.ar/eventos","https://catpass.com.ar/eventos?ciudad=la-plata"],
        "catpass","https://catpass.com.ar",
        None,None,None,None,None)


# Passline tiene API — scraping especial
def scrape_passline():
    events = []
    log.info("Passline → iniciando…")
    for api_url in ["https://www.passline.com/api/events?country=AR&city=la-plata&limit=200",
                    "https://www.passline.com/api/events?country=AR&limit=500"]:
        try:
            r = requests.get(api_url, headers=HEADERS, timeout=20)
            if r.status_code != 200: continue
            data = r.json()
            raw = data if isinstance(data, list) else data.get("events", data.get("data", data.get("items",[])))
            log.info(f"Passline API: {len(raw)} raw")
            for ev in raw:
                try:
                    title = str(ev.get("name", ev.get("title",""))).strip()
                    if not title or len(title)<3: continue
                    vraw = ev.get("venue", ev.get("lugar", ev.get("location","")))
                    venue = vraw.get("name","") if isinstance(vraw,dict) else str(vraw)
                    date_raw = str(ev.get("date", ev.get("start_date", ev.get("starts_at",""))))
                    slug = ev.get("slug", ev.get("id",""))
                    img = str(ev.get("image", ev.get("cover", ev.get("flyer",""))))
                    desc = str(ev.get("description",""))
                    if not is_lp(title+" "+venue+" "+desc): continue
                    events.append({
                        "title":title[:120],"cat":detect_cat(title,desc),
                        "date":parse_date(date_raw),"time":parse_time(date_raw),
                        "venue":venue[:100],"city":"La Plata",
                        "source":"Passline","sourceKey":"passline",
                        "url":f"https://www.passline.com/eventos/{slug}" if slug else "https://www.passline.com",
                        "flyer":img if img.startswith("http") else "",
                    })
                except: pass
            if events: break
        except Exception as e:
            log.warning(f"Passline API {api_url}: {e}")

    if not events:
        events += scrape_generic_html("Passline",
            ["https://www.passline.com/eventos?pais=AR"],
            "passline","https://www.passline.com",None,None,None,None,None)

    log.info(f"Passline → {len(events)} eventos")
    return events


# ──────────────────────────────────────────
# PARSEO DE FECHAS / HORA
# ──────────────────────────────────────────
MESES = {"enero":"01","febrero":"02","marzo":"03","abril":"04","mayo":"05","junio":"06",
          "julio":"07","agosto":"08","septiembre":"09","setiembre":"09","octubre":"10","noviembre":"11","diciembre":"12",
          "jan":"01","feb":"02","mar":"03","apr":"04","may":"05","jun":"06",
          "jul":"07","aug":"08","sep":"09","oct":"10","nov":"11","dec":"12"}

def parse_date(raw):
    if not raw: return ""
    raw = raw.strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m: return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", raw)
    if m: return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    m = re.search(r"(\d{1,2})\s+(?:de\s+)?([a-zA-ZáéíóúÁÉÍÓÚ]+)\s+(?:de\s+)?(\d{4})", raw)
    if m:
        mes = MESES.get(m.group(2).lower()[:3], MESES.get(m.group(2).lower(),""))
        if mes: return f"{m.group(3)}-{mes}-{m.group(1).zfill(2)}"
    return ""

def parse_time(raw):
    if not raw: return ""
    m = re.search(r"(\d{1,2}):(\d{2})(?:\s*hs?)?", raw)
    return f"{m.group(1).zfill(2)}:{m.group(2)}" if m else ""

def deduplicate(events):
    seen, out = set(), []
    for e in events:
        key = (e["title"].lower()[:40], e["date"], e["sourceKey"])
        if key not in seen: seen.add(key); out.append(e)
    return out

def filter_future(events):
    today = datetime.now().strftime("%Y-%m-%d")
    return [e for e in events if e.get("date","9999") >= today or not e.get("date")]

def sort_events(events):
    return sorted(events, key=lambda e: (e.get("date") or "9999-12-31", e.get("title","").lower()))


# ──────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────
def main():
    log.info("════════════════════════════════════════")
    log.info("  La agenda de natu (extendida) — v2")
    log.info("════════════════════════════════════════")
    t0 = time.time()

    all_events = []

    # Teatro Argentino primero — fuente más confiable
    all_events += scrape_teatro_argentino(); pause()
    all_events += scrape_ticketek();         pause()
    all_events += scrape_allaccess();        pause()
    all_events += scrape_passline();         pause()
    all_events += scrape_ticketpass();       pause()
    all_events += scrape_livepass();         pause()
    all_events += scrape_tuentrada();        pause()
    all_events += scrape_alpogo();           pause()
    all_events += scrape_mianticipada();     pause()
    all_events += scrape_rgentradas();       pause()
    all_events += scrape_plateanet();        pause()
    all_events += scrape_catpass();

    log.info(f"Total crudo: {len(all_events)}")
    all_events = deduplicate(all_events)
    all_events = filter_future(all_events)
    all_events = sort_events(all_events)

    for i, e in enumerate(all_events):
        e["id"] = i + 1

    output = {
        "updated_at": datetime.now().isoformat(),
        "source":     "scraper-natu-v2",
        "city":       "La Plata",
        "total":      len(all_events),
        "events":     all_events,
    }

    out = Path(__file__).parent / "shows.json"
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"✓ {len(all_events)} eventos → shows.json ({time.time()-t0:.1f}s)")

if __name__ == "__main__":
    main()
