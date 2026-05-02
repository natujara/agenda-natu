"""
La agenda de natu (extendida) — Scraper v7
============================================
Novedades:
  · Bandsintown: scraping de /c/la-plata-argentina (todos los géneros)
    Bandsintown tiene la página pública más completa de eventos en La Plata.
    Usamos Playwright porque la página carga con JS.
    URL patrón: https://www.bandsintown.com/c/la-plata-argentina/all-dates
  · CatPass: URL corregida a catpass.net/eventos
  · Playwright mejorado: selectores estructurales para sitios con clases dinámicas

Fuentes activas:
  HTML / API   : Casa Metro, Teatro Argentino, Passline
  Playwright   : Bandsintown, Teatro Metro LP, MiAnticipada,
                 UniversoTickets, CatPass, LivePass, Ticketek,
                 TicketPass, TuEntrada, Alpogo, RgEntradas

Instalación:
    pip install requests beautifulsoup4 playwright
    playwright install chromium
"""

import json, re, time, logging
from datetime import datetime
from pathlib import Path
from collections import Counter

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("natu")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "es-AR,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Referer": "https://www.google.com.ar/",
}

LP_KW = [
    "la plata", "berisso", "ensenada", "gonnet", "tolosa", "city bell",
    "villa elisa", "ringuelet",
    "teatro argentino", "estadio estudiantes", "estadio uno", "estadio único",
    "estadio unico", "estadio gimnasia", "coliseo podestá", "coliseo podesta",
    "pasaje dardo rocha", "casa metro", "teatro metro",
    "anfiteatro martin fierro", "anfiteatro martín fierro",
    "hipódromo de la plata", "hipodromo de la plata",
    "quality espacio", "el galpón", "el galpon", "club atenas",
    "cine select", "centro cultural islas malvinas", "casa curutchet",
    "movistar arena la plata", "estadio unico la plata",
]

CAT_KW = {
    "recital":  ["recital","concierto","música","rock","jazz","cumbia","tango","folk",
                 "metal","pop","indie","show en vivo","show musical","orquesta",
                 "sinfónico","blues","reggae","electrónica","hip hop","trap","rap",
                 "cuarteto","peña","folklore","murga","punk","hardcore","ska"],
    "teatro":   ["teatro","obra","dramaturgia","monólogo","ópera","opera",
                 "lírico","comedia musical","unipersonal"],
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
    return "recital"  # en Bandsintown casi todo es música

def is_lp(text):
    return any(k in text.lower() for k in LP_KW)

def pause(s=2): time.sleep(s)

def make_event(title, cat, date, time_, venue, city, source, source_key, url, flyer):
    return {
        "title": title[:120], "cat": cat,
        "date": date, "time": time_,
        "venue": (venue[:100] if venue else ""), "city": city,
        "source": source, "sourceKey": source_key,
        "url": url,
        "flyer": flyer if (flyer and flyer.startswith("http")) else "",
    }


# ══════════════════════════════════════════════════════════
#  BANDSINTOWN — página pública de ciudad
#
#  URL: https://www.bandsintown.com/c/la-plata-argentina/all-dates
#  Estructura de cada evento:
#    <div data-event-id="...">
#      <p>ARTISTA</p>          ← nombre
#      <p>Evento / descripción</p>
#      <p>VENUE, La Plata</p>
#      <time datetime="2025-06-14T21:00:00">Sab 14 Jun • 21:00</time>
#      <a href="/e/...">Get Tickets</a> o <a href="URL externa">Get Tickets</a>
#    </div>
#
#  También scrapeamos por género para no perdernos nada:
#    rock, metal, punk, pop, indie, folk, electronic, jazz, latin, comedy
# ══════════════════════════════════════════════════════════
def scrape_bandsintown():
    events = []
    log.info("Bandsintown → scrapeando…")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("Bandsintown: Playwright no instalado.")
        return events

    # Géneros a scrapear — cubrimos el espectro completo
    genre_urls = [
        "https://www.bandsintown.com/c/la-plata-argentina/all-dates",
        "https://www.bandsintown.com/c/la-plata-argentina/all-dates/genre/rock",
        "https://www.bandsintown.com/c/la-plata-argentina/all-dates/genre/metal",
        "https://www.bandsintown.com/c/la-plata-argentina/all-dates/genre/punk",
        "https://www.bandsintown.com/c/la-plata-argentina/all-dates/genre/pop",
        "https://www.bandsintown.com/c/la-plata-argentina/all-dates/genre/electronic",
        "https://www.bandsintown.com/c/la-plata-argentina/all-dates/genre/latin",
        "https://www.bandsintown.com/c/la-plata-argentina/all-dates/genre/folk",
        "https://www.bandsintown.com/c/la-plata-argentina/all-dates/genre/comedy",
    ]

    seen_titles = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox","--disable-setuid-sandbox",
                  "--disable-dev-shm-usage","--disable-gpu","--lang=es-AR"]
        )
        ctx = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="es-AR",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()

        for url in genre_urls:
            try:
                page.goto(url, timeout=40000, wait_until="domcontentloaded")

                # Esperar a que cargue el listado de eventos
                try:
                    page.wait_for_selector(
                        "[data-event-id], article, [class*='event'], time",
                        timeout=12000
                    )
                except Exception:
                    log.debug(f"Bandsintown: timeout esperando eventos en {url}")

                time.sleep(3)

                # Scroll para cargar todos los eventos (Bandsintown hace lazy load)
                prev_height = 0
                for _ in range(8):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(1.5)
                    new_height = page.evaluate("document.body.scrollHeight")
                    if new_height == prev_height:
                        break
                    prev_height = new_height

                html = page.content()
                soup = BeautifulSoup(html, "html.parser")

                # Bandsintown: cada evento está en un contenedor con data-event-id
                # o en un <article> o en un li con clase que incluye "event"
                event_blocks = (
                    soup.select("[data-event-id]")
                    or soup.select("article")
                    or soup.select("[class*='event-item'],[class*='EventItem']")
                    or soup.select("li:has(time)")
                )

                log.info(f"Bandsintown: {len(event_blocks)} bloques en {url.split('/')[-1]}")

                for block in event_blocks:
                    try:
                        block_text = block.get_text(" ", strip=True)

                        # Artista / título: primer <p> o <h2>/<h3>/<h4>
                        # En Bandsintown el primer texto prominente es el nombre del artista
                        title_el = (
                            block.find(["h2","h3","h4"])
                            or block.find("p")
                        )
                        title = title_el.get_text(strip=True) if title_el else ""

                        # Si hay un nombre de evento separado (ej: "Festival Synth")
                        # tomar el más descriptivo
                        all_ps = block.find_all("p")
                        if len(all_ps) >= 2:
                            # Segundo <p> puede ser nombre del evento
                            event_name = all_ps[1].get_text(strip=True)
                            if event_name and len(event_name) > len(title):
                                title = f"{title} — {event_name}"

                        if not title or len(title) < 3:
                            continue

                        # Deduplicar por título normalizado
                        title_key = title.lower()[:50]
                        if title_key in seen_titles:
                            continue
                        seen_titles.add(title_key)

                        # Fecha y hora — Bandsintown usa <time datetime="ISO">
                        time_el = block.find("time")
                        date_str, time_str = "", ""
                        if time_el:
                            dt_attr = time_el.get("datetime","")
                            if dt_attr:
                                date_str = parse_date(dt_attr)
                                time_str = parse_time(dt_attr)
                            else:
                                # Texto del <time>: "Sab 14 Jun • 21:00"
                                t_text = time_el.get_text(strip=True)
                                date_str = parse_date(t_text)
                                time_str = parse_time(t_text)

                        if not date_str:
                            date_str = parse_date(block_text)
                        if not time_str:
                            time_str = parse_time(block_text)

                        # Venue — último <p> suele ser "Venue, Ciudad"
                        venue = ""
                        if all_ps:
                            last_p = all_ps[-1].get_text(strip=True)
                            # Formato: "Nombre Venue, La Plata"
                            if "," in last_p:
                                venue = last_p.split(",")[0].strip()
                            else:
                                venue = last_p

                        # Link de entradas — buscar "Get Tickets" o cualquier link externo
                        ticket_url = ""
                        for a in block.find_all("a", href=True):
                            href = a.get("href","")
                            text = a.get_text(strip=True).lower()
                            if "ticket" in text or "entrada" in text or "comprar" in text:
                                ticket_url = href
                                break
                        if not ticket_url:
                            link_el = block.find("a", href=True)
                            ticket_url = link_el["href"] if link_el else ""

                        # Links internos de Bandsintown → convertir a URL completa
                        if ticket_url and ticket_url.startswith("/"):
                            ticket_url = "https://www.bandsintown.com" + ticket_url

                        # Imagen del artista
                        img_el = block.find("img")
                        flyer = ""
                        if img_el:
                            flyer = img_el.get("src", img_el.get("data-src",""))

                        events.append(make_event(
                            title, detect_cat(title),
                            date_str, time_str,
                            venue, "La Plata",
                            "Bandsintown", "bandsintown",
                            ticket_url or url, flyer
                        ))

                    except Exception as e:
                        log.debug(f"Bandsintown bloque: {e}")

                pause(2)

            except Exception as e:
                log.error(f"Bandsintown {url}: {e}")

        browser.close()

    log.info(f"Bandsintown → {len(events)} eventos")
    return events


# ══════════════════════════════════════════════════════════
#  CASA METRO — WordPress /cartelera/
# ══════════════════════════════════════════════════════════
def scrape_casa_metro():
    events = []
    log.info("Casa Metro → scrapeando…")
    try:
        r = requests.get("https://casametro.com.ar/cartelera/",
                         headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        cards = soup.select("li.product, article.product, .product-inner")
        if not cards:
            cards = soup.select(".entry, .post, section article")
        if not cards:
            links = soup.find_all("a", href=re.compile(r"/evento/|/product/"))
            cards = [a.find_parent(["li","article","div"]) for a in links]
            cards = [c for c in cards if c]

        log.info(f"Casa Metro: {len(cards)} cards")
        for card in cards:
            try:
                title_el = (card.select_one(".woocommerce-loop-product__title")
                            or card.find(["h2","h3","h4","h5"]))
                title = title_el.get_text(strip=True) if title_el else ""
                if not title or len(title) < 3: continue
                block_text = card.get_text(" ", strip=True)
                link_el = (card.select_one("a[href*='/evento/'], a[href*='/product/']")
                           or card.find("a", href=True))
                href = link_el["href"] if link_el else "https://casametro.com.ar/cartelera/"
                img_el = card.find("img")
                flyer = ""
                if img_el:
                    flyer = img_el.get("data-src") or img_el.get("src") or ""
                    flyer = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", flyer)
                events.append(make_event(
                    title, detect_cat(title),
                    parse_date(block_text), parse_time(block_text),
                    "Casa Metro La Plata", "La Plata",
                    "Casa Metro", "casametro", href, flyer
                ))
            except Exception as e:
                log.debug(f"Casa Metro card: {e}")
    except Exception as e:
        log.error(f"Casa Metro: {e}")
    log.info(f"Casa Metro → {len(events)} eventos")
    return events


# ══════════════════════════════════════════════════════════
#  TEATRO ARGENTINO — HTML estático
# ══════════════════════════════════════════════════════════
def scrape_teatro_argentino():
    events = []
    log.info("Teatro Argentino → scrapeando…")
    url = "https://teatroargentino.gba.gob.ar/meets/no-season"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        for h5 in soup.find_all("h5"):
            try:
                title = h5.get_text(strip=True)
                if not title or len(title) < 3: continue
                parent = h5.parent
                block_text = parent.get_text(" ", strip=True)
                date_str, time_str = "", ""
                m = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})", block_text)
                if m:
                    date_str = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
                    time_str = f"{m.group(4)}:{m.group(5)}"
                venue = "Teatro Argentino"
                sala_m = re.search(r"(Alberto Ginastera|Astor Piazzolla|Sala \w+)", block_text)
                if sala_m:
                    venue = f"Teatro Argentino — {sala_m.group(1)}"
                link_el = parent.find("a", href=re.compile(r"/meet/\d+"))
                link = (f"https://teatroargentino.gba.gob.ar{link_el['href']}"
                        if link_el else url)
                img_el = parent.find("img", src=re.compile(r"/uploads/"))
                flyer = (f"https://teatroargentino.gba.gob.ar{img_el['src']}"
                         if img_el else "")
                events.append(make_event(
                    title, detect_cat(title), date_str, time_str,
                    venue, "La Plata", "Teatro Argentino", "teatroargentino", link, flyer
                ))
            except Exception as e:
                log.debug(f"Teatro Argentino: {e}")
    except Exception as e:
        log.error(f"Teatro Argentino: {e}")
    log.info(f"Teatro Argentino → {len(events)} eventos")
    return events


# ══════════════════════════════════════════════════════════
#  PASSLINE — API JSON
# ══════════════════════════════════════════════════════════
def scrape_passline():
    events = []
    log.info("Passline → API…")
    for api_url in [
        "https://www.passline.com/api/events?country=AR&city=la-plata&limit=200",
        "https://www.passline.com/api/events?country=AR&province=buenos-aires&limit=500",
        "https://www.passline.com/api/events?country=AR&limit=500",
    ]:
        try:
            r = requests.get(api_url, headers=HEADERS, timeout=20)
            if r.status_code != 200: continue
            data = r.json()
            raw = (data if isinstance(data, list)
                   else data.get("events", data.get("data", data.get("items",[]))))
            log.info(f"Passline: {len(raw)} items")
            for ev in raw:
                try:
                    title = str(ev.get("name", ev.get("title",""))).strip()
                    if not title or len(title) < 3: continue
                    vraw = ev.get("venue", ev.get("lugar",""))
                    venue = vraw.get("name","") if isinstance(vraw,dict) else str(vraw)
                    desc = str(ev.get("description",""))
                    if not is_lp(title + " " + venue + " " + desc): continue
                    date_raw = str(ev.get("date", ev.get("start_date", ev.get("starts_at",""))))
                    slug = ev.get("slug", ev.get("id",""))
                    img = str(ev.get("image", ev.get("cover", ev.get("flyer",""))))
                    events.append(make_event(
                        title, detect_cat(title, desc),
                        parse_date(date_raw), parse_time(date_raw),
                        venue, "La Plata", "Passline", "passline",
                        f"https://www.passline.com/eventos/{slug}" if slug else "https://www.passline.com",
                        img
                    ))
                except Exception as e:
                    log.debug(f"Passline item: {e}")
            if events: break
            pause(1)
        except Exception as e:
            log.warning(f"Passline {api_url}: {e}")
    log.info(f"Passline → {len(events)} eventos")
    return events


# ══════════════════════════════════════════════════════════
#  PLAYWRIGHT BASE — selectores estructurales
#  Para sitios con clases CSS dinámicas (hashes)
# ══════════════════════════════════════════════════════════
def playwright_scrape(name, source_key, urls,
                      filter_lp=True, extra_wait=0, venue_default=""):
    events = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning(f"{name}: Playwright no instalado.")
        return events

    log.info(f"{name} (Playwright) → scrapeando…")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox","--disable-setuid-sandbox",
                  "--disable-dev-shm-usage","--disable-gpu","--lang=es-AR"]
        )
        ctx = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="es-AR",
            viewport={"width": 1280, "height": 900},
            extra_http_headers={"Accept-Language": "es-AR,es;q=0.9"},
        )
        page = ctx.new_page()

        for url in urls:
            try:
                page.goto(url, timeout=45000, wait_until="domcontentloaded")

                # Esperar contenido
                for sel in ["article","h2","h3","[class*='card']",
                             "[class*='event']","[class*='show']","main img"]:
                    try:
                        page.wait_for_selector(sel, timeout=12000)
                        break
                    except Exception:
                        continue

                time.sleep(2 + extra_wait)

                # Scroll progresivo
                total = page.evaluate("document.body.scrollHeight")
                for pos in range(0, total, 400):
                    page.evaluate(f"window.scrollTo(0, {pos})")
                    time.sleep(0.15)
                page.evaluate("window.scrollTo(0, 0)")
                time.sleep(1)

                html = page.content()
                soup = BeautifulSoup(html, "html.parser")

                # Selectores ordenados de más a menos específico
                cards = []
                for sel in [
                    "article",
                    "[class*='EventCard']","[class*='event-card']",
                    "[class*='EventItem']","[class*='event-item']",
                    "[class*='ShowCard']","[class*='show-card']",
                    "[class*='evento']","[class*='Evento']",
                    "[class*='events-list'] li","[class*='shows-list'] li",
                    "[class*='grid'] > div:has(a):has(img)",
                    "ul > li:has(a):has(h2)","ul > li:has(a):has(h3)",
                    "main > div > div:has(a):has(img):has(h2)",
                    "main > div > div:has(a):has(img):has(h3)",
                ]:
                    try:
                        found = soup.select(sel)
                        if 2 < len(found) < 200:
                            log.info(f"{name}: {len(found)} cards con '{sel}'")
                            cards = found
                            break
                    except Exception:
                        continue

                # Búsqueda estructural genérica si no encontramos nada
                if not cards:
                    log.info(f"{name}: búsqueda estructural genérica")
                    candidates = []
                    for el in soup.find_all(["div","li","article"]):
                        if (el.find("a", href=True)
                                and el.find("img")
                                and 10 < len(el.get_text(strip=True)) < 500):
                            candidates.append(el)
                    # Quedarse con los más específicos (sin padres en la lista)
                    deduped = []
                    for c in candidates:
                        if not any(c != o and c in o.descendants for o in candidates):
                            deduped.append(c)
                    cards = deduped[:100]
                    log.info(f"{name}: {len(cards)} cards estructurales")

                if not cards:
                    log.warning(f"{name}: sin cards en {url}")
                    pause(1)
                    continue

                for card in cards:
                    try:
                        title_el = (
                            card.select_one(
                                "[class*='title'],[class*='Title'],"
                                "[class*='name'],[class*='Name']"
                            ) or card.find(["h1","h2","h3","h4","h5"])
                        )
                        title = title_el.get_text(strip=True) if title_el else ""
                        if not title:
                            for el in card.find_all(True):
                                t = el.get_text(strip=True)
                                if 3 < len(t) < 100: title = t; break
                        if not title or len(title) < 3: continue

                        block_text = card.get_text(" ", strip=True)
                        if filter_lp and not is_lp(title + " " + block_text):
                            continue

                        date_el = card.select_one(
                            "[class*='date'],[class*='Date'],[class*='fecha'],time")
                        date_txt = (date_el.get_text(strip=True) if date_el else "") or block_text

                        venue_el = card.select_one(
                            "[class*='venue'],[class*='Venue'],[class*='lugar'],"
                            "[class*='location'],[class*='place']")
                        venue_txt = (venue_el.get_text(strip=True)
                                     if venue_el else "") or venue_default

                        link_el = card.find("a", href=True)
                        href = link_el["href"] if link_el else ""
                        base = "/".join(url.split("/")[:3])
                        if href and not href.startswith("http"):
                            href = base + href

                        img_el = card.find("img")
                        flyer = ""
                        if img_el:
                            flyer = img_el.get("data-src") or img_el.get("src") or ""
                            if flyer and not flyer.startswith("http"):
                                flyer = base + flyer

                        events.append(make_event(
                            title, detect_cat(title),
                            parse_date(date_txt), parse_time(date_txt),
                            venue_txt, "La Plata",
                            name, source_key, href or url, flyer
                        ))
                    except Exception as e:
                        log.debug(f"{name} card: {e}")

                if events: break
            except Exception as e:
                log.error(f"{name} URL {url}: {e}")
            pause(1)

        browser.close()

    log.info(f"{name} → {len(events)} eventos")
    return events


# Ticketeras JS
def scrape_teatro_metro():
    return playwright_scrape("Teatro Metro LP","teatrometrolp",
        ["https://www.teatrometrolp.com.ar/entradas/cartelera/"],
        filter_lp=False, extra_wait=3, venue_default="Teatro Metro LP")

def scrape_mianticipada():
    return playwright_scrape("MiAnticipada","mianticipada",
        ["https://mianticipada.com/La-Plata/",
         "https://mianticipada.com/?ciudad=la-plata"],
        filter_lp=True, extra_wait=2)

def scrape_universotickets():
    return playwright_scrape("UniversoTickets","universotickets",
        ["https://universotickets.com/buscar?q=la+plata"],
        filter_lp=True, extra_wait=3)

def scrape_catpass():
    return playwright_scrape("CatPass","catpass",
        ["https://catpass.net/eventos?ciudad=la-plata",
         "https://catpass.net/eventos?q=la+plata",
         "https://catpass.net/eventos"],
        filter_lp=True, extra_wait=3)

def scrape_ticketek():
    return playwright_scrape("Ticketek","ticketek",
        ["https://www.ticketek.com.ar/shows/shows.aspx?prov=BUE"],
        filter_lp=True, extra_wait=5)

def scrape_ticketpass():
    return playwright_scrape("TicketPass","ticketpass",
        ["https://ticketpass.com.ar/eventos?ciudad=la-plata",
         "https://ticketpass.com.ar/eventos"],
        filter_lp=True, extra_wait=3)

def scrape_livepass():
    return playwright_scrape("LivePass","livepass",
        ["https://www.livepass.com.ar/eventos?ciudad=la-plata",
         "https://www.livepass.com.ar/eventos"],
        filter_lp=True, extra_wait=3)

def scrape_tuentrada():
    return playwright_scrape("TuEntrada","tuentrada",
        ["https://tuentrada.com/eventos?ciudad=la-plata",
         "https://tuentrada.com/"],
        filter_lp=True, extra_wait=3)

def scrape_alpogo():
    return playwright_scrape("Alpogo","alpogo",
        ["https://alpogo.com/search?q=la+plata",
         "https://alpogo.com/"],
        filter_lp=True, extra_wait=3)

def scrape_rgentradas():
    return playwright_scrape("RgEntradas","rgentradas",
        ["https://rgentradas.com/eventos?ciudad=la-plata",
         "https://rgentradas.com/"],
        filter_lp=True, extra_wait=3)


# ══════════════════════════════════════════════════════════
#  PARSEO
# ══════════════════════════════════════════════════════════
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
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m: return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", raw)
    if m: return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    m = re.search(r"([a-zA-ZáéíóúÁÉÍÓÚ]+)\s+(\d{1,2}),?\s+(\d{4})", raw)
    if m:
        mes = MESES.get(m.group(1).lower()[:3],"")
        if mes: return f"{m.group(3)}-{mes}-{m.group(2).zfill(2)}"
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
            seen.add(key); out.append(e)
    return out

def filter_future(events):
    today = datetime.now().strftime("%Y-%m-%d")
    return [e for e in events if e.get("date","9999") >= today or not e.get("date")]

def sort_events(events):
    return sorted(events,
        key=lambda e: (e.get("date") or "9999-12-31", e.get("title","").lower()))


# ══════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════
def main():
    log.info("══════════════════════════════════════════")
    log.info("  La agenda de natu (extendida) — v7")
    log.info("══════════════════════════════════════════")
    t0 = time.time()

    all_events = []

    # HTML estático / API — rápido y confiable
    all_events += scrape_casa_metro();       pause()
    all_events += scrape_teatro_argentino(); pause()
    all_events += scrape_passline();         pause()

    # Bandsintown — la fuente más completa para música en La Plata
    all_events += scrape_bandsintown();      pause()

    # Playwright — resto de ticketeras
    all_events += scrape_teatro_metro();     pause()
    all_events += scrape_mianticipada();     pause()
    all_events += scrape_universotickets();  pause()
    all_events += scrape_catpass();          pause()
    all_events += scrape_livepass();         pause()
    all_events += scrape_ticketek();         pause()
    all_events += scrape_ticketpass();       pause()
    all_events += scrape_tuentrada();        pause()
    all_events += scrape_alpogo();           pause()
    all_events += scrape_rgentradas()

    log.info(f"Total crudo: {len(all_events)}")
    all_events = deduplicate(all_events)
    all_events = filter_future(all_events)
    all_events = sort_events(all_events)

    for i, e in enumerate(all_events):
        e["id"] = i + 1

    output = {
        "updated_at": datetime.now().isoformat(),
        "source":     "scraper-natu-v7",
        "city":       "La Plata",
        "total":      len(all_events),
        "events":     all_events,
    }

    out = Path(__file__).parent / "shows.json"
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    counts = Counter(e["sourceKey"] for e in all_events)
    log.info(f"✓ {len(all_events)} eventos en {time.time()-t0:.1f}s")
    for src, n in sorted(counts.items(), key=lambda x: -x[1]):
        log.info(f"   {src:<22} {n} eventos")


if __name__ == "__main__":
    main()
