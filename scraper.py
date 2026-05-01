"""
La agenda de natu (extendida) — Scraper v3
============================================
Estrategia por fuente:

  HTML ESTÁTICO (requests + BeautifulSoup):
    · Casa Metro         — WordPress, HTML limpio
    · Teatro Argentino   — HTML estático con <h5>
    · Teatro Metro LP    — HTML estático
    · Plateanet          — HTML estático
    · PlateaUno          — HTML estático (nodo1.plateaunotickets.com)

  API JSON (requests):
    · Passline           — API pública /api/events
    · Alpogo             — API pública
    · TuEntrada          — API pública

  JAVASCRIPT PESADO (Playwright headless):
    · Ticketek           — React, requiere JS
    · All Access         — React, requiere JS
    · TicketPass         — React, requiere JS
    · LivePass           — React, requiere JS
    · MiAnticipada       — React, requiere JS
    · RgEntradas         — React, requiere JS
    · CatPass            — React, requiere JS
    · UniversoTickets    — React, requiere JS

Instalación:
    pip install requests beautifulsoup4 playwright
    playwright install chromium
"""

import json, re, time, logging
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("natu-scraper")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

# Palabras que indican que el evento es en La Plata / zona
LP_KW = [
    "la plata", "berisso", "ensenada", "gonnet", "tolosa", "city bell",
    "villa elisa", "ringuelet", "teatro argentino", "estadio estudiantes",
    "estadio uno", "estadio único", "estadio unico", "estadio gimnasia",
    "coliseo podestá", "coliseo podesta", "pasaje dardo rocha",
    "casa metro", "teatro metro", "anfiteatro martin fierro",
    "anfiteatro martín fierro", "hipódromo de la plata", "hipodromo de la plata",
]

CAT_KW = {
    "recital":  ["recital","concierto","música","rock","jazz","cumbia","tango","folk",
                 "metal","pop","indie","show en vivo","show musical","orquesta","sinfónico",
                 "blues","reggae","electrónica","electro","hip hop","trap","rap","cuarteto"],
    "teatro":   ["teatro","obra","dramaturgia","monólogo","ópera","opera","lírico","comedia musical"],
    "festival": ["festival","feria","encuentro cultural","ciclo"],
    "standup":  ["stand-up","stand up","humor","comedia","comediante"],
    "danza":    ["danza","ballet","tango show","circo","acrobacia"],
    "cine":     ["cine","película","film","proyección","cinemato"],
    "arte":     ["expo","exposición","muestra","arte","galería","fotografía","instalación"],
    "infantil": ["infantil","niños","familiar","kids","bebés","familia"],
}

def detect_cat(title, desc=""):
    text = (title + " " + desc).lower()
    for cat, kws in CAT_KW.items():
        if any(k in text for k in kws):
            return cat
    return "otro"

def is_lp(text):
    return any(k in text.lower() for k in LP_KW)

def pause(secs=2):
    time.sleep(secs)


# ═══════════════════════════════════════════════════════════
#  FUENTES HTML ESTÁTICO
# ═══════════════════════════════════════════════════════════

def scrape_casa_metro():
    """
    Casa Metro — WordPress con estructura clara.
    URL: https://casametro.com.ar/
    Cada evento: <article> o bloque con fecha, título, imagen y link.
    """
    events = []
    log.info("Casa Metro → scrapeando…")
    try:
        r = requests.get("https://casametro.com.ar/", headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        # Buscar todos los bloques con "Comprar tickets"
        for link in soup.find_all("a", string=re.compile("Comprar tickets", re.I)):
            try:
                block = link.find_parent(["article", "div", "section", "li"])
                if not block:
                    continue

                # Título: el <h2>, <h3>, <h4> o <h5> más cercano
                title_el = block.find(["h2","h3","h4","h5"])
                title = title_el.get_text(strip=True) if title_el else ""
                if not title or len(title) < 3:
                    continue

                # Fecha: texto que contenga patrón de día/mes/año
                block_text = block.get_text(" ")
                date_str = parse_date(block_text)
                time_str = parse_time(block_text)

                # Imagen / flyer
                img_el = block.find("img")
                flyer = ""
                if img_el:
                    flyer = img_el.get("src", img_el.get("data-src", ""))

                href = link.get("href", "https://casametro.com.ar")

                events.append({
                    "title":     title[:120],
                    "cat":       detect_cat(title),
                    "date":      date_str,
                    "time":      time_str,
                    "venue":     "Casa Metro La Plata",
                    "city":      "La Plata",
                    "source":    "Casa Metro",
                    "sourceKey": "casametro",
                    "url":       href,
                    "flyer":     flyer if flyer.startswith("http") else "",
                })
            except Exception as e:
                log.debug(f"Casa Metro bloque error: {e}")

    except Exception as e:
        log.error(f"Casa Metro: {e}")

    log.info(f"Casa Metro → {len(events)} eventos")
    return events


def scrape_teatro_argentino():
    """
    Teatro Argentino — HTML estático con <h5> por evento.
    URL: https://teatroargentino.gba.gob.ar/meets/no-season
    """
    events = []
    log.info("Teatro Argentino → scrapeando…")
    url = "https://teatroargentino.gba.gob.ar/meets/no-season"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        for h5 in soup.find_all("h5"):
            try:
                title = h5.get_text(strip=True)
                if not title or len(title) < 3:
                    continue

                parent = h5.parent
                block_text = parent.get_text(" ", strip=True)

                # Fecha formato DD/MM/YYYY HH:MM
                date_str, time_str = "", ""
                m = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})", block_text)
                if m:
                    date_str = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
                    time_str = f"{m.group(4)}:{m.group(5)}"

                # Sala
                venue = "Teatro Argentino"
                sala_m = re.search(r"(Alberto Ginastera|Astor Piazzolla|Sala \w+)", block_text)
                if sala_m:
                    venue = f"Teatro Argentino — {sala_m.group(1)}"

                # Link directo al evento
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


def scrape_teatro_metro():
    """
    Teatro Metro LP — HTML estático.
    URL: https://www.teatrometrolp.com.ar/entradas/cartelera/
    """
    events = []
    log.info("Teatro Metro LP → scrapeando…")
    base = "https://www.teatrometrolp.com.ar"
    try:
        r = requests.get(f"{base}/entradas/cartelera/", headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        # Cada espectáculo está en un bloque contenedor
        for card in soup.select("[class*='show'], [class*='event'], [class*='espectaculo'], article, .item"):
            try:
                title_el = card.find(["h1","h2","h3","h4","h5",".title",".nombre"])
                title = title_el.get_text(strip=True) if title_el else ""
                if not title or len(title) < 3:
                    continue

                block_text = card.get_text(" ")
                date_str = parse_date(block_text)
                time_str = parse_time(block_text)

                link_el = card.find("a", href=True)
                href = link_el["href"] if link_el else ""
                if href and not href.startswith("http"):
                    href = base + href

                img_el = card.find("img")
                flyer = ""
                if img_el:
                    flyer = img_el.get("src", img_el.get("data-src",""))
                    if flyer and not flyer.startswith("http"):
                        flyer = base + flyer

                events.append({
                    "title":     title[:120],
                    "cat":       detect_cat(title),
                    "date":      date_str,
                    "time":      time_str,
                    "venue":     "Teatro Metro LP",
                    "city":      "La Plata",
                    "source":    "Teatro Metro LP",
                    "sourceKey": "teatrometrolp",
                    "url":       href or f"{base}/entradas/cartelera/",
                    "flyer":     flyer if flyer.startswith("http") else "",
                })
            except Exception as e:
                log.debug(f"Teatro Metro LP bloque error: {e}")

    except Exception as e:
        log.error(f"Teatro Metro LP: {e}")

    log.info(f"Teatro Metro LP → {len(events)} eventos")
    return events


def scrape_plateanet():
    """
    Plateanet — buscar eventos filtrando por La Plata.
    """
    events = []
    log.info("Plateanet → scrapeando…")
    urls = [
        "https://www.plateanet.com/eventos?ciudad=la-plata",
        "https://www.plateanet.com/cartelera?ciudad=la-plata",
        "https://www.plateanet.com/eventos",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select("article, .event-card, .evento, [class*='event'], [class*='show']")
            if not cards:
                continue
            log.info(f"Plateanet: {len(cards)} cards en {url}")
            for card in cards:
                try:
                    title_el = card.find(["h1","h2","h3","h4","h5"])
                    title = title_el.get_text(strip=True) if title_el else ""
                    if not title or len(title) < 3:
                        continue
                    block_text = card.get_text(" ")
                    if not is_lp(title + " " + block_text):
                        continue
                    link_el = card.find("a", href=True)
                    href = link_el["href"] if link_el else ""
                    if href and not href.startswith("http"):
                        href = "https://www.plateanet.com" + href
                    img_el = card.find("img")
                    flyer = img_el.get("src","") if img_el else ""
                    events.append({
                        "title":     title[:120],
                        "cat":       detect_cat(title),
                        "date":      parse_date(block_text),
                        "time":      parse_time(block_text),
                        "venue":     "",
                        "city":      "La Plata",
                        "source":    "Plateanet",
                        "sourceKey": "plateanet",
                        "url":       href or "https://www.plateanet.com",
                        "flyer":     flyer if flyer.startswith("http") else "",
                    })
                except Exception as e:
                    log.debug(f"Plateanet card: {e}")
            if events:
                break
            pause(1)
        except Exception as e:
            log.error(f"Plateanet {url}: {e}")
    log.info(f"Plateanet → {len(events)} eventos")
    return events


def scrape_plateauno():
    """
    PlateaUno — HTML estático, filtrar por LaPlata Metro.
    URL: https://nodo1.plateaunotickets.com/cartelera
    """
    events = []
    log.info("PlateaUno → scrapeando…")
    try:
        r = requests.get("https://nodo1.plateaunotickets.com/cartelera", headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        # La cartelera tiene ítems con nombre de sala — filtramos "LaPlata"
        for item in soup.select("li, .item, tr, [class*='event'], article"):
            try:
                text = item.get_text(" ", strip=True)
                if "laplata" not in text.lower().replace(" ","") and "la plata" not in text.lower():
                    continue
                # Extraer título (primer texto largo)
                title = ""
                for el in item.find_all(["h1","h2","h3","h4","h5","strong","b","span"]):
                    t = el.get_text(strip=True)
                    if len(t) > 4:
                        title = t
                        break
                if not title:
                    title = text[:80]
                link_el = item.find("a", href=True)
                href = link_el["href"] if link_el else ""
                if href and not href.startswith("http"):
                    href = "https://nodo1.plateaunotickets.com" + href
                events.append({
                    "title":     title[:120],
                    "cat":       detect_cat(title),
                    "date":      parse_date(text),
                    "time":      parse_time(text),
                    "venue":     "Teatro Metro LP",
                    "city":      "La Plata",
                    "source":    "PlateaUno",
                    "sourceKey": "plateauno",
                    "url":       href or "https://nodo1.plateaunotickets.com/cartelera",
                    "flyer":     "",
                })
            except Exception as e:
                log.debug(f"PlateaUno item: {e}")
    except Exception as e:
        log.error(f"PlateaUno: {e}")
    log.info(f"PlateaUno → {len(events)} eventos")
    return events


# ═══════════════════════════════════════════════════════════
#  FUENTES CON API JSON
# ═══════════════════════════════════════════════════════════

def scrape_passline():
    """Passline — API pública."""
    events = []
    log.info("Passline → scrapeando API…")
    for api_url in [
        "https://www.passline.com/api/events?country=AR&city=la-plata&limit=200",
        "https://www.passline.com/api/events?country=AR&limit=500",
    ]:
        try:
            r = requests.get(api_url, headers=HEADERS, timeout=20)
            if r.status_code != 200:
                continue
            data = r.json()
            raw = data if isinstance(data, list) else data.get("events", data.get("data", data.get("items",[])))
            log.info(f"Passline: {len(raw)} items raw")
            for ev in raw:
                try:
                    title = str(ev.get("name", ev.get("title",""))).strip()
                    if not title or len(title) < 3:
                        continue
                    vraw = ev.get("venue", ev.get("lugar", ev.get("location","")))
                    venue = vraw.get("name","") if isinstance(vraw,dict) else str(vraw)
                    date_raw = str(ev.get("date", ev.get("start_date", ev.get("starts_at",""))))
                    desc = str(ev.get("description",""))
                    if not is_lp(title+" "+venue+" "+desc):
                        continue
                    slug = ev.get("slug", ev.get("id",""))
                    img = str(ev.get("image", ev.get("cover", ev.get("flyer",""))))
                    events.append({
                        "title":     title[:120],
                        "cat":       detect_cat(title, desc),
                        "date":      parse_date(date_raw),
                        "time":      parse_time(date_raw),
                        "venue":     venue[:100],
                        "city":      "La Plata",
                        "source":    "Passline",
                        "sourceKey": "passline",
                        "url":       f"https://www.passline.com/eventos/{slug}" if slug else "https://www.passline.com",
                        "flyer":     img if img.startswith("http") else "",
                    })
                except Exception as e:
                    log.debug(f"Passline item: {e}")
            if events:
                break
        except Exception as e:
            log.warning(f"Passline API {api_url}: {e}")

    log.info(f"Passline → {len(events)} eventos")
    return events


def scrape_alpogo():
    """Alpogo — intentar API, fallback HTML."""
    events = []
    log.info("Alpogo → scrapeando…")
    for url in [
        "https://alpogo.com/api/events?city=la-plata",
        "https://alpogo.com/api/events?location=la+plata",
        "https://alpogo.com/eventos?ciudad=la-plata",
        "https://alpogo.com/eventos",
    ]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            # Intentar JSON
            try:
                data = r.json()
                raw = data if isinstance(data,list) else data.get("events", data.get("data",[]))
                for ev in raw:
                    title = str(ev.get("name", ev.get("title",""))).strip()
                    if not title or len(title) < 3: continue
                    vraw = ev.get("venue",""); venue = vraw.get("name","") if isinstance(vraw,dict) else str(vraw)
                    date_raw = str(ev.get("date", ev.get("start_date","")))
                    if not is_lp(title+" "+venue): continue
                    slug = ev.get("slug", ev.get("id",""))
                    img = str(ev.get("image", ev.get("cover","")))
                    events.append({"title":title[:120],"cat":detect_cat(title),"date":parse_date(date_raw),"time":parse_time(date_raw),
                        "venue":venue[:100],"city":"La Plata","source":"Alpogo","sourceKey":"alpogo",
                        "url":f"https://alpogo.com/eventos/{slug}" if slug else "https://alpogo.com","flyer":img if img.startswith("http") else ""})
                if events: break
            except Exception:
                # Fallback HTML
                soup = BeautifulSoup(r.text, "html.parser")
                for card in soup.select("article,[class*='event'],[class*='card']"):
                    title_el = card.find(["h1","h2","h3","h4","h5"])
                    title = title_el.get_text(strip=True) if title_el else ""
                    if not title or len(title)<3: continue
                    bt = card.get_text(" ")
                    if not is_lp(title+" "+bt): continue
                    link_el = card.find("a",href=True)
                    href = link_el["href"] if link_el else ""
                    if href and not href.startswith("http"): href="https://alpogo.com"+href
                    events.append({"title":title[:120],"cat":detect_cat(title),"date":parse_date(bt),"time":parse_time(bt),
                        "venue":"","city":"La Plata","source":"Alpogo","sourceKey":"alpogo","url":href or "https://alpogo.com","flyer":""})
                if events: break
            pause(1)
        except Exception as e:
            log.warning(f"Alpogo {url}: {e}")

    log.info(f"Alpogo → {len(events)} eventos")
    return events


def scrape_tuentrada():
    """TuEntrada — intentar API o HTML."""
    events = []
    log.info("TuEntrada → scrapeando…")
    for url in [
        "https://tuentrada.com/api/events?city=la-plata",
        "https://tuentrada.com/eventos?ciudad=la-plata",
        "https://tuentrada.com/eventos",
    ]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            try:
                data = r.json()
                raw = data if isinstance(data,list) else data.get("events", data.get("data",[]))
                for ev in raw:
                    title = str(ev.get("name",ev.get("title",""))).strip()
                    if not title or len(title)<3: continue
                    vraw=ev.get("venue",""); venue=vraw.get("name","") if isinstance(vraw,dict) else str(vraw)
                    date_raw=str(ev.get("date",ev.get("start_date","")))
                    if not is_lp(title+" "+venue): continue
                    slug=ev.get("slug",ev.get("id",""))
                    img=str(ev.get("image",ev.get("cover","")))
                    events.append({"title":title[:120],"cat":detect_cat(title),"date":parse_date(date_raw),"time":parse_time(date_raw),
                        "venue":venue[:100],"city":"La Plata","source":"TuEntrada","sourceKey":"tuentrada",
                        "url":f"https://tuentrada.com/eventos/{slug}" if slug else "https://tuentrada.com","flyer":img if img.startswith("http") else ""})
                if events: break
            except Exception:
                soup = BeautifulSoup(r.text,"html.parser")
                for card in soup.select("article,[class*='event'],[class*='card']"):
                    title_el=card.find(["h1","h2","h3","h4","h5"])
                    title=title_el.get_text(strip=True) if title_el else ""
                    if not title or len(title)<3: continue
                    bt=card.get_text(" ")
                    if not is_lp(title+" "+bt): continue
                    link_el=card.find("a",href=True)
                    href=link_el["href"] if link_el else ""
                    if href and not href.startswith("http"): href="https://tuentrada.com"+href
                    events.append({"title":title[:120],"cat":detect_cat(title),"date":parse_date(bt),"time":parse_time(bt),
                        "venue":"","city":"La Plata","source":"TuEntrada","sourceKey":"tuentrada","url":href or "https://tuentrada.com","flyer":""})
                if events: break
            pause(1)
        except Exception as e:
            log.warning(f"TuEntrada {url}: {e}")
    log.info(f"TuEntrada → {len(events)} eventos")
    return events


# ═══════════════════════════════════════════════════════════
#  FUENTES JAVASCRIPT — Playwright headless
# ═══════════════════════════════════════════════════════════

def scrape_with_playwright(name, source_key, urls, filter_lp=True):
    """
    Scraper genérico con Playwright para sitios que renderizan con JS.
    Espera a que aparezcan cards de eventos, luego extrae título, fecha,
    venue, link e imagen.
    """
    events = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning(f"{name}: Playwright no instalado, saltando.")
        return events

    log.info(f"{name} (Playwright) → scrapeando…")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-setuid-sandbox"])
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="es-AR",
        )
        page = context.new_page()

        for url in urls:
            try:
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
                # Esperar hasta 10s a que aparezca algún selector de evento
                for sel in ["article", "[class*='event']", "[class*='card']", "[class*='show']", "h2", "h3"]:
                    try:
                        page.wait_for_selector(sel, timeout=8000)
                        break
                    except Exception:
                        continue

                # Scroll para cargar lazy content
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2)

                html = page.content()
                soup = BeautifulSoup(html, "html.parser")

                selectors = [
                    "article", "[class*='event-card']", "[class*='EventCard']",
                    "[class*='event-item']", "[class*='show-card']", "[class*='card']",
                    "[class*='evento']",
                ]
                cards = []
                for sel in selectors:
                    cards = soup.select(sel)
                    if len(cards) > 2:
                        log.info(f"{name}: {len(cards)} cards con '{sel}'")
                        break

                for card in cards:
                    try:
                        title_el = card.find(["h1","h2","h3","h4","h5",
                                              "[class*='title']","[class*='name']"])
                        if title_el is None:
                            title_el = card.select_one("[class*='title'],[class*='name']")
                        title = title_el.get_text(strip=True) if title_el else ""
                        if not title or len(title) < 3:
                            continue

                        block_text = card.get_text(" ")
                        if filter_lp and not is_lp(title + " " + block_text):
                            continue

                        date_el  = card.select_one("[class*='date'],[class*='fecha'],time")
                        venue_el = card.select_one("[class*='venue'],[class*='lugar'],[class*='location']")
                        link_el  = card.find("a", href=True)
                        img_el   = card.find("img")

                        date_txt  = (date_el.get_text(strip=True) if date_el else "") or block_text
                        venue_txt = venue_el.get_text(strip=True) if venue_el else ""

                        href = link_el["href"] if link_el else ""
                        base_url = "/".join(url.split("/")[:3])
                        if href and not href.startswith("http"):
                            href = base_url + href

                        flyer = ""
                        if img_el:
                            flyer = img_el.get("src", img_el.get("data-src",""))
                            if flyer and not flyer.startswith("http"):
                                flyer = base_url + flyer

                        events.append({
                            "title":     title[:120],
                            "cat":       detect_cat(title),
                            "date":      parse_date(date_txt),
                            "time":      parse_time(date_txt),
                            "venue":     venue_txt[:100],
                            "city":      "La Plata",
                            "source":    name,
                            "sourceKey": source_key,
                            "url":       href or url,
                            "flyer":     flyer if flyer.startswith("http") else "",
                        })
                    except Exception as e:
                        log.debug(f"{name} card: {e}")

                if events:
                    break

            except Exception as e:
                log.error(f"{name} URL {url}: {e}")

        browser.close()

    log.info(f"{name} (Playwright) → {len(events)} eventos")
    return events


# Ticketeras JS — cada una con sus URLs específicas

def scrape_ticketek():
    return scrape_with_playwright("Ticketek","ticketek",[
        "https://www.ticketek.com.ar/shows/shows.aspx?prov=BUE",
        "https://www.ticketek.com.ar/shows/shows.aspx",
    ])

def scrape_allaccess():
    return scrape_with_playwright("All Access","allaccess",[
        "https://www.allaccess.com.ar/eventos?ciudad=la-plata",
        "https://www.allaccess.com.ar/eventos",
    ])

def scrape_ticketpass():
    return scrape_with_playwright("TicketPass","ticketpass",[
        "https://ticketpass.com.ar/eventos?ciudad=la-plata",
        "https://ticketpass.com.ar/eventos",
    ])

def scrape_livepass():
    return scrape_with_playwright("LivePass","livepass",[
        "https://www.livepass.com.ar/eventos?ciudad=la-plata",
        "https://www.livepass.com.ar/eventos",
    ])

def scrape_mianticipada():
    return scrape_with_playwright("MiAnticipada","mianticipada",[
        "https://mianticipada.com/eventos?ciudad=la-plata",
        "https://mianticipada.com/eventos",
    ])

def scrape_rgentradas():
    return scrape_with_playwright("RgEntradas","rgentradas",[
        "https://rgentradas.com/eventos?ciudad=la-plata",
        "https://rgentradas.com/eventos",
    ])

def scrape_catpass():
    return scrape_with_playwright("CatPass","catpass",[
        "https://catpass.com.ar/eventos?ciudad=la-plata",
        "https://catpass.com.ar/eventos",
    ])

def scrape_universotickets():
    return scrape_with_playwright("UniversoTickets","universotickets",[
        "https://universotickets.com/buscar?q=la+plata",
        "https://universotickets.com/",
    ])


# ═══════════════════════════════════════════════════════════
#  PARSEO DE FECHAS Y HORA
# ═══════════════════════════════════════════════════════════

MESES = {
    "enero":"01","febrero":"02","marzo":"03","abril":"04","mayo":"05","junio":"06",
    "julio":"07","agosto":"08","septiembre":"09","setiembre":"09","octubre":"10",
    "noviembre":"11","diciembre":"12",
    "jan":"01","feb":"02","mar":"03","apr":"04","may":"05","jun":"06",
    "jul":"07","aug":"08","sep":"09","oct":"10","nov":"11","dec":"12",
}

def parse_date(raw):
    if not raw: return ""
    raw = str(raw).strip()
    # ISO 2025-06-14 o 2025-06-14T21:00:00
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m: return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # DD/MM/YYYY o DD-MM-YYYY
    m = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", raw)
    if m: return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    # "14 de junio de 2025" / "14 Jun 2025" / "Sábado 14 junio 2025"
    m = re.search(r"(\d{1,2})\s+(?:de\s+)?([a-zA-ZáéíóúÁÉÍÓÚ]+)\s+(?:de\s+)?(\d{4})", raw)
    if m:
        mes = MESES.get(m.group(2).lower()[:3], MESES.get(m.group(2).lower(),""))
        if mes: return f"{m.group(3)}-{mes}-{m.group(1).zfill(2)}"
    return ""

def parse_time(raw):
    if not raw: return ""
    m = re.search(r"(\d{1,2}):(\d{2})(?:\s*hs?)?", str(raw))
    return f"{m.group(1).zfill(2)}:{m.group(2)}" if m else ""

def deduplicate(events):
    seen, out = set(), []
    for e in events:
        key = (e["title"].lower()[:40], e["date"], e["sourceKey"])
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out

def filter_future(events):
    today = datetime.now().strftime("%Y-%m-%d")
    return [e for e in events if e.get("date","9999") >= today or not e.get("date")]

def sort_events(events):
    return sorted(events, key=lambda e: (e.get("date") or "9999-12-31", e.get("title","").lower()))


# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════

def main():
    log.info("══════════════════════════════════════════")
    log.info("  La agenda de natu (extendida) — v3")
    log.info("══════════════════════════════════════════")
    t0 = time.time()

    all_events = []

    # ── HTML estático (rápido, sin JS) ──
    all_events += scrape_casa_metro();       pause()
    all_events += scrape_teatro_argentino(); pause()
    all_events += scrape_teatro_metro();     pause()
    all_events += scrape_plateanet();        pause()
    all_events += scrape_plateauno();        pause()

    # ── APIs JSON ──
    all_events += scrape_passline();         pause()
    all_events += scrape_alpogo();           pause()
    all_events += scrape_tuentrada();        pause()

    # ── JS con Playwright ──
    all_events += scrape_ticketek();         pause()
    all_events += scrape_allaccess();        pause()
    all_events += scrape_ticketpass();       pause()
    all_events += scrape_livepass();         pause()
    all_events += scrape_mianticipada();     pause()
    all_events += scrape_rgentradas();       pause()
    all_events += scrape_catpass();          pause()
    all_events += scrape_universotickets()

    log.info(f"Total crudo: {len(all_events)}")
    all_events = deduplicate(all_events)
    all_events = filter_future(all_events)
    all_events = sort_events(all_events)

    for i, e in enumerate(all_events):
        e["id"] = i + 1

    output = {
        "updated_at": datetime.now().isoformat(),
        "source":     "scraper-natu-v3",
        "city":       "La Plata",
        "total":      len(all_events),
        "events":     all_events,
    }

    out = Path(__file__).parent / "shows.json"
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"✓ {len(all_events)} eventos → shows.json ({time.time()-t0:.1f}s)")
    log.info(f"  Fuentes con datos: {len(set(e['sourceKey'] for e in all_events))}")


if __name__ == "__main__":
    main()
