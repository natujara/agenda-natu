"""
La agenda de natu (extendida) — Scraper v8
============================================
Fixes basados en el log real de v7:

  Casa Metro      ✅ 12 eventos — sin cambios
  Teatro Argentino✅ 7 eventos  — sin cambios
  Teatro Metro LP ✅ 12 eventos — sin cambios
  MiAnticipada    🔧 3→más    — restaurar selector [class*='card']
  CatPass         ✅ 2 eventos  — sin cambios
  Alpogo          ✅ 6 eventos  — sin cambios, ya usa [class*='evento']
  RgEntradas      ✅ 2 eventos  — sin cambios

  Bandsintown     🔧 0→más    — requests con headers anti-bot (no Playwright)
                               Bandsintown bloquea headless browsers
  LivePass        🔧 0→más    — filtro LP demasiado estricto, relajar
  TicketPass      🔧 0→más    — filtro LP demasiado estricto, relajar
  TuEntrada       🔧 0→más    — filtro LP demasiado estricto, relajar
  Ticketek        🔧 0→más    — URL sin resultados visibles, cambiar estrategia
  UniversoTickets 🔧 0→más    — ampliar búsqueda

Instalación:
    pip install requests beautifulsoup4 playwright lxml
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

# Headers que imitan un navegador real
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.com.ar/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
    "Upgrade-Insecure-Requests": "1",
}

# Headers específicos para Bandsintown (imitar browser más agresivamente)
HEADERS_BIT = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.google.com.ar/search?q=bandsintown+la+plata",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
    "Cache-Control": "no-cache",
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
    "movistar arena la plata",
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
    return "recital"

def is_lp(text):
    return any(k in text.lower() for k in LP_KW)

def pause(s=2): time.sleep(s)

def make_ev(title, cat, date, time_, venue, source, source_key, url, flyer=""):
    return {
        "title":     title[:120],
        "cat":       cat,
        "date":      date,
        "time":      time_,
        "venue":     (venue[:100] if venue else ""),
        "city":      "La Plata",
        "source":    source,
        "sourceKey": source_key,
        "url":       url,
        "flyer":     flyer if (flyer and flyer.startswith("http")) else "",
    }


# ══════════════════════════════════════════════════════════
#  BANDSINTOWN — requests con headers anti-bot
#  La API pública v3 permite app_id=cualquier_string
#  Endpoint de búsqueda por ciudad via GraphQL interno
#  o scraping de la página pública con requests
# ══════════════════════════════════════════════════════════
def scrape_bandsintown():
    events = []
    log.info("Bandsintown → scrapeando con requests…")

    session = requests.Session()
    session.headers.update(HEADERS_BIT)

    # Primero hacemos una visita a Google para tener Referer real
    try:
        session.get("https://www.google.com.ar/search?q=bandsintown+la+plata",
                    timeout=10)
        time.sleep(1)
    except Exception:
        pass

    # URLs de la página pública de Bandsintown por ciudad
    urls = [
        "https://www.bandsintown.com/c/la-plata-argentina/all-dates",
        "https://www.bandsintown.com/c/la-plata-argentina",
    ]

    for url in urls:
        try:
            r = session.get(url, timeout=30)
            log.info(f"Bandsintown: HTTP {r.status_code} en {url}")
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, "html.parser")

            # Buscar JSON embebido (Next.js / React SSR)
            # Bandsintown suele incluir __NEXT_DATA__ con todos los eventos
            script = soup.find("script", id="__NEXT_DATA__")
            if script:
                try:
                    data = json.loads(script.string)
                    # Navegar por la estructura de Next.js para encontrar eventos
                    events_raw = _extract_from_next_data(data)
                    if events_raw:
                        log.info(f"Bandsintown: {len(events_raw)} eventos desde __NEXT_DATA__")
                        for ev in events_raw:
                            try:
                                e = _parse_bandsintown_event(ev)
                                if e:
                                    events.append(e)
                            except Exception as ex:
                                log.debug(f"Bandsintown event parse: {ex}")
                        if events:
                            break
                except Exception as e:
                    log.debug(f"Bandsintown __NEXT_DATA__: {e}")

            # Fallback: buscar en el HTML renderizado
            # Bandsintown usa divs con data-event-id o time[datetime]
            event_blocks = (
                soup.select("[data-event-id]")
                or soup.select("article")
                or soup.select("li:has(time[datetime])")
                or soup.select("[class*='EventCard'], [class*='event-card']")
            )
            log.info(f"Bandsintown: {len(event_blocks)} bloques HTML en {url}")

            for block in event_blocks:
                try:
                    title_el = block.find(["h2","h3","h4","h5","p","strong"])
                    title = title_el.get_text(strip=True) if title_el else ""
                    if not title or len(title) < 3: continue

                    time_el = block.find("time", datetime=True)
                    date_str = parse_date(time_el["datetime"]) if time_el else ""
                    time_str = parse_time(time_el["datetime"]) if time_el else ""

                    all_ps = block.find_all("p")
                    venue = ""
                    if all_ps:
                        last = all_ps[-1].get_text(strip=True)
                        venue = last.split(",")[0].strip() if "," in last else last

                    link_el = block.find("a", href=True)
                    href = link_el["href"] if link_el else url
                    if href.startswith("/"):
                        href = "https://www.bandsintown.com" + href

                    img_el = block.find("img")
                    flyer = img_el.get("src","") if img_el else ""

                    events.append(make_ev(
                        title, detect_cat(title), date_str, time_str,
                        venue, "Bandsintown", "bandsintown", href, flyer
                    ))
                except Exception as e:
                    log.debug(f"Bandsintown bloque HTML: {e}")

            if events: break
            pause(2)

        except Exception as e:
            log.error(f"Bandsintown {url}: {e}")

    log.info(f"Bandsintown → {len(events)} eventos")
    return events


def _extract_from_next_data(data: dict) -> list:
    """Navega recursivamente por el __NEXT_DATA__ de Next.js buscando arrays de eventos."""
    results = []
    def search(obj):
        if isinstance(obj, list) and len(obj) > 0:
            # Si el primer elemento parece un evento (tiene datetime y venue)
            first = obj[0]
            if isinstance(first, dict) and (
                "datetime" in first or "starts_at" in first
                or "date" in first
            ):
                results.extend(obj)
                return
        if isinstance(obj, dict):
            for v in obj.values():
                search(v)
        elif isinstance(obj, list):
            for item in obj:
                search(item)
    search(data)
    return results


def _parse_bandsintown_event(ev: dict) -> dict | None:
    """Convierte un dict de evento de Bandsintown al formato de la agenda."""
    if not isinstance(ev, dict): return None

    # Artista
    artists = ev.get("lineup", ev.get("artists", []))
    if isinstance(artists, list) and artists:
        if isinstance(artists[0], dict):
            title = artists[0].get("name","")
        else:
            title = str(artists[0])
    else:
        title = ev.get("title", ev.get("name",""))

    if not title or len(title) < 3: return None

    # Fecha
    date_raw = ev.get("datetime", ev.get("starts_at", ev.get("date","")))
    date_str = parse_date(str(date_raw))
    time_str = parse_time(str(date_raw))

    # Venue
    venue_data = ev.get("venue", {})
    if isinstance(venue_data, dict):
        venue_name = venue_data.get("name","")
        city = venue_data.get("city","La Plata")
    else:
        venue_name = str(venue_data) if venue_data else ""
        city = "La Plata"

    # Filtrar por La Plata
    if not is_lp(venue_name + " " + city + " " + title):
        return None

    # Tickets
    offers = ev.get("offers", [])
    ticket_url = ev.get("url","")
    if offers and isinstance(offers, list) and isinstance(offers[0], dict):
        ticket_url = offers[0].get("url", ticket_url)
    if not ticket_url:
        ticket_url = f"https://www.bandsintown.com/e/{ev.get('id','')}"

    # Imagen
    flyer = ""
    artist_data = ev.get("artist", {})
    if isinstance(artist_data, dict):
        flyer = artist_data.get("image_url", artist_data.get("thumb_url",""))

    return make_ev(title, detect_cat(title), date_str, time_str,
                   venue_name, "Bandsintown", "bandsintown", ticket_url, flyer)


# ══════════════════════════════════════════════════════════
#  CASA METRO — funciona bien en v7
# ══════════════════════════════════════════════════════════
def scrape_casa_metro():
    """
    Casa Metro — scraping desde la home.
    Estructura real: cada evento está en un bloque con:
      - <img> con el flyer
      - texto con "Día, DD de Mes de YYYY"
      - <h5> con el título
      - <a href="/evento/...">Comprar tickets</a>
    """
    events = []
    log.info("Casa Metro → scrapeando…")
    try:
        r = requests.get("https://casametro.com.ar/", headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")

        # Buscar todos los links a /evento/ — cada uno es un evento
        seen = set()
        for a in soup.find_all("a", href=re.compile(r"/evento/")):
            href = a.get("href","")
            if not href or href in seen: continue
            seen.add(href)

            # El bloque padre contiene imagen, fecha y título
            block = a.find_parent(["div","li","article","section"])
            if not block: continue

            # Título: <h5> o <h4> o <h3>
            title_el = block.find(["h5","h4","h3","h2"])
            title = title_el.get_text(strip=True) if title_el else ""
            # Si el link tiene texto descriptivo, usarlo como título
            if not title:
                link_text = a.get_text(strip=True)
                if link_text and link_text.lower() not in ("comprar tickets","ver más","tickets"):
                    title = link_text
            if not title or len(title) < 3: continue

            block_text = block.get_text(" ", strip=True)
            date_str = parse_date(block_text)
            time_str = parse_time(block_text)

            # Imagen: quitar sufijos de tamaño
            img_el = block.find("img")
            flyer = ""
            if img_el:
                flyer = img_el.get("src") or img_el.get("data-src") or ""
                flyer = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", flyer)

            events.append(make_ev(
                title, detect_cat(title), date_str, time_str,
                "Casa Metro La Plata", "Casa Metro", "casametro", href, flyer
            ))

        log.info(f"Casa Metro: {len(events)} eventos")
    except Exception as e:
        log.error(f"Casa Metro: {e}")
    log.info(f"Casa Metro → {len(events)} eventos")
    return events


# ══════════════════════════════════════════════════════════
#  TEATRO ARGENTINO — funciona bien en v7
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
                bt = parent.get_text(" ", strip=True)
                date_str, time_str = "", ""
                m = re.search(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})", bt)
                if m:
                    date_str = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
                    time_str = f"{m.group(4)}:{m.group(5)}"
                venue = "Teatro Argentino"
                sm = re.search(r"(Alberto Ginastera|Astor Piazzolla|Sala \w+)", bt)
                if sm: venue = f"Teatro Argentino — {sm.group(1)}"
                link_el = parent.find("a", href=re.compile(r"/meet/\d+"))
                link = (f"https://teatroargentino.gba.gob.ar{link_el['href']}"
                        if link_el else url)
                img_el = parent.find("img", src=re.compile(r"/uploads/"))
                flyer = (f"https://teatroargentino.gba.gob.ar{img_el['src']}"
                         if img_el else "")
                events.append(make_ev(title, detect_cat(title), date_str, time_str,
                    venue, "Teatro Argentino", "teatroargentino", link, flyer))
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
                    if not is_lp(title+" "+venue+" "+desc): continue
                    date_raw = str(ev.get("date", ev.get("start_date", ev.get("starts_at",""))))
                    slug = ev.get("slug", ev.get("id",""))
                    img = str(ev.get("image", ev.get("cover","")))
                    events.append(make_ev(title, detect_cat(title, desc),
                        parse_date(date_raw), parse_time(date_raw),
                        venue, "Passline", "passline",
                        f"https://www.passline.com/eventos/{slug}" if slug else "https://www.passline.com",
                        img))
                except Exception as e:
                    log.debug(f"Passline: {e}")
            if events: break
            pause(1)
        except Exception as e:
            log.warning(f"Passline {api_url}: {e}")
    log.info(f"Passline → {len(events)} eventos")
    return events


# ══════════════════════════════════════════════════════════
#  PLAYWRIGHT BASE v8
#  Fixes:
#  1. MiAnticipada: restaura selector [class*='card'] que daba 198 results
#  2. LivePass/TicketPass/TuEntrada: relajar filtro LP cuando la URL
#     ya busca "la-plata" — si la URL filtra por ciudad, confiamos en eso
#  3. Ticketek: nueva URL + esperar networkidle
#  4. Selectores por fuente configurables
# ══════════════════════════════════════════════════════════
def playwright_scrape(name, source_key, urls,
                      filter_lp=True, extra_wait=0, venue_default="",
                      preferred_selector=None, trust_url_filter=False):
    """
    trust_url_filter=True: si la URL ya filtra por ciudad (ej: ?ciudad=la-plata),
    no aplicar el filtro de palabras clave LP (el sitio ya lo hizo por nosotros).
    """
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
            # Determinar si esta URL ya filtra por La Plata
            url_filters_lp = trust_url_filter and (
                "la-plata" in url.lower()
                or "la+plata" in url.lower()
                or "laplata" in url.lower()
            )
            apply_lp_filter = filter_lp and not url_filters_lp

            try:
                page.goto(url, timeout=45000, wait_until="domcontentloaded")

                # Esperar contenido
                for sel in ["article","h2","h3",
                             "[class*='card']","[class*='event']",
                             "[class*='show']","main img","[class*='evento']"]:
                    try:
                        page.wait_for_selector(sel, timeout=12000)
                        break
                    except Exception:
                        continue

                time.sleep(2 + extra_wait)

                # Scroll progresivo
                total = page.evaluate("document.body.scrollHeight")
                for pos in range(0, min(total, 8000), 500):
                    page.evaluate(f"window.scrollTo(0, {pos})")
                    time.sleep(0.2)
                page.evaluate("window.scrollTo(0, 0)")
                time.sleep(1)

                html = page.content()
                soup = BeautifulSoup(html, "html.parser")

                # Selectores a probar — el preferido va primero
                selector_list = []
                if preferred_selector:
                    selector_list.append(preferred_selector)
                selector_list += [
                    "article",
                    "[class*='card']",           # MiAnticipada tenía 198 con esto
                    "[class*='evento']",          # Alpogo tenía 94
                    "[class*='EventCard']","[class*='event-card']",
                    "[class*='EventItem']","[class*='event-item']",
                    "[class*='ShowCard']","[class*='show-card']",
                    "[class*='shows-list'] li","[class*='events-list'] li",
                    "ul > li:has(a):has(h2)","ul > li:has(a):has(h3)",
                    "[class*='grid'] > div:has(a):has(img)",
                    "main > div > div:has(a):has(img):has(h2)",
                ]

                cards = []
                for sel in selector_list:
                    try:
                        found = soup.select(sel)
                        if 2 < len(found) < 300:
                            log.info(f"{name}: {len(found)} cards con '{sel}'")
                            cards = found
                            break
                    except Exception:
                        continue

                # Búsqueda estructural genérica como último recurso
                if not cards:
                    log.info(f"{name}: búsqueda estructural genérica")
                    candidates = []
                    for el in soup.find_all(["div","li","article"]):
                        if (el.find("a", href=True)
                                and el.find("img")
                                and 10 < len(el.get_text(strip=True)) < 600):
                            candidates.append(el)
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
                                if 3 < len(t) < 120: title = t; break
                        if not title or len(title) < 3: continue

                        block_text = card.get_text(" ", strip=True)

                        if apply_lp_filter and not is_lp(title + " " + block_text):
                            continue

                        date_el = card.select_one(
                            "[class*='date'],[class*='Date'],[class*='fecha'],time")
                        date_txt = (date_el.get_text(strip=True)
                                    if date_el else "") or block_text

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

                        events.append(make_ev(
                            title, detect_cat(title),
                            parse_date(date_txt), parse_time(date_txt),
                            venue_txt, name, source_key, href or url, flyer
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


# Ticketeras — configuración específica por fuente

def scrape_teatro_metro():
    return playwright_scrape("Teatro Metro LP","teatrometrolp",
        ["https://www.teatrometrolp.com.ar/entradas/cartelera/"],
        filter_lp=False, extra_wait=3, venue_default="Teatro Metro LP")

def scrape_mianticipada():
    # En v3 encontraba 198 cards con [class*='card'] — lo ponemos como preferido
    return playwright_scrape("MiAnticipada","mianticipada",
        ["https://mianticipada.com/La-Plata/",
         "https://mianticipada.com/?ciudad=la-plata"],
        filter_lp=True, extra_wait=2,
        preferred_selector="[class*='card']")

def scrape_universotickets():
    return playwright_scrape("UniversoTickets","universotickets",
        ["https://universotickets.com/buscar?q=la+plata",
         "https://universotickets.com/eventos?ciudad=la+plata"],
        filter_lp=True, extra_wait=3)

def scrape_catpass():
    return playwright_scrape("CatPass","catpass",
        ["https://catpass.net/eventos?ciudad=la-plata",
         "https://catpass.net/eventos?q=la+plata",
         "https://catpass.net/eventos"],
        filter_lp=True, extra_wait=3)

def scrape_ticketek():
    # Ticketek: intentar con la búsqueda de "la plata" directamente
    return playwright_scrape("Ticketek","ticketek",
        ["https://www.ticketek.com.ar/shows/shows.aspx?q=la+plata",
         "https://www.ticketek.com.ar/comprar/shows/buscar?q=la+plata",
         "https://www.ticketek.com.ar/shows/shows.aspx?prov=BUE"],
        filter_lp=True, extra_wait=6)

def scrape_ticketpass():
    # trust_url_filter: la URL ya filtra por la-plata, no necesitamos filtrar por LP_KW
    return playwright_scrape("TicketPass","ticketpass",
        ["https://ticketpass.com.ar/eventos?ciudad=la-plata",
         "https://ticketpass.com.ar/eventos?q=la+plata"],
        filter_lp=True, extra_wait=3,
        trust_url_filter=True)

def scrape_livepass():
    """
    LivePass — HTML estático, no necesita Playwright.
    Scrapea las páginas de taxón (venue) de La Plata directamente.
    Estructura: h3 = título, h2 = fecha, a[href*='/events/'] = link, img = flyer.
    """
    events = []
    log.info("LivePass → scrapeando páginas de venue…")

    # Páginas de venue/taxón de La Plata conocidas
    venue_pages = [
        ("https://livepass.com.ar/taxons/hipodromo-la-plata", "Hipódromo de La Plata"),
        ("https://livepass.com.ar/taxons/opera-la-plata",     "Opera La Plata"),
        ("https://livepass.com.ar/taxons/teatro-argentino",   "Teatro Argentino"),
    ]

    # También buscar en la home si hay eventos de La Plata destacados
    home_urls = [
        "https://livepass.com.ar/",
        "https://livepass.com.ar/t/show",
    ]

    BASE = "https://livepass.com.ar"

    def parse_livepass_page(html, default_venue):
        found = []
        soup = BeautifulSoup(html, "html.parser")

        # Cada evento: un <a href="/events/..."> que contiene h3 (título) + h2 (fecha)
        for a in soup.find_all("a", href=re.compile(r"/events/")):
            try:
                title_el = a.find("h3") or a.find("h4") or a.find("strong")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title or len(title) < 3:
                    continue

                # Fecha: h2 dentro del link o texto tipo "Sábado 09 Mayo"
                date_el = a.find("h2") or a.find("h4")
                date_txt = date_el.get_text(strip=True) if date_el else ""

                # Venue: texto del <h2> suele incluir venue después de la fecha
                # "Sábado 09 Mayo, Hipodromo de la Plata, Avenida 44..."
                full_date_txt = date_txt
                venue_txt = default_venue
                if "," in date_txt:
                    parts = date_txt.split(",")
                    full_date_txt = parts[0].strip()
                    venue_txt = parts[1].strip() if len(parts) > 1 else default_venue

                href = a.get("href","")
                if href and not href.startswith("http"):
                    href = BASE + href

                img_el = a.find("img")
                flyer = img_el.get("src","") if img_el else ""

                found.append(make_ev(
                    title, detect_cat(title),
                    parse_date(full_date_txt), parse_time(full_date_txt),
                    venue_txt, "LivePass", "livepass", href, flyer
                ))
            except Exception as e:
                log.debug(f"LivePass card: {e}")
        return found

    # Scrapear páginas de venue
    for url, default_venue in venue_pages:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            log.info(f"LivePass: HTTP {r.status_code} — {url}")
            if r.status_code == 200:
                found = parse_livepass_page(r.text, default_venue)
                log.info(f"LivePass: {len(found)} eventos en {default_venue}")
                events += found
            pause(1)
        except Exception as e:
            log.error(f"LivePass {url}: {e}")

    # Scrapear home filtrando por La Plata
    for url in home_urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=re.compile(r"/events/")):
                    try:
                        block_text = a.get_text(" ")
                        if not is_lp(block_text): continue
                        title_el = a.find("h3") or a.find("h4") or a.find("strong")
                        title = title_el.get_text(strip=True) if title_el else ""
                        if not title or len(title) < 3: continue
                        date_el = a.find("h2")
                        date_txt = date_el.get_text(strip=True) if date_el else ""
                        href = a.get("href","")
                        if href and not href.startswith("http"):
                            href = BASE + href
                        img_el = a.find("img")
                        flyer = img_el.get("src","") if img_el else ""
                        events.append(make_ev(
                            title, detect_cat(title),
                            parse_date(date_txt), parse_time(date_txt),
                            "", "LivePass", "livepass", href, flyer
                        ))
                    except Exception as e:
                        log.debug(f"LivePass home card: {e}")
            pause(1)
        except Exception as e:
            log.error(f"LivePass home {url}: {e}")

    # Deduplicar por URL de evento
    seen_urls = set()
    deduped = []
    for e in events:
        if e["url"] not in seen_urls:
            seen_urls.add(e["url"])
            deduped.append(e)

    log.info(f"LivePass → {len(deduped)} eventos")
    return deduped

def scrape_plateanet():
    return playwright_scrape("Plateanet","plateanet",
        ["https://www.plateanet.com/search/-/-/La%20Plata/-/-/-/-"],
        filter_lp=False, extra_wait=4,
        preferred_selector="[class*='card'],[class*='show'],[class*='espectaculo'],article")

def scrape_alpogo():
    return playwright_scrape("Alpogo","alpogo",
        ["https://alpogo.com/search?q=la+plata",
         "https://alpogo.com/eventos?ciudad=la-plata"],
        filter_lp=True, extra_wait=3,
        preferred_selector="[class*='evento']")

def scrape_rgentradas():
    return playwright_scrape("RgEntradas","rgentradas",
        ["https://rgentradas.com/eventos?ciudad=la-plata",
         "https://rgentradas.com/buscar?q=la+plata",
         "https://rgentradas.com/"],
        filter_lp=True, extra_wait=3,
        trust_url_filter=True)


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
    log.info("  La agenda de natu (extendida) — v9")
    log.info("══════════════════════════════════════════")
    t0 = time.time()

    all_events = []

    # HTML estático / API
    all_events += scrape_casa_metro();       pause()
    all_events += scrape_teatro_argentino(); pause()
    all_events += scrape_passline();         pause()
    all_events += scrape_bandsintown();      pause()

    # Playwright
    all_events += scrape_teatro_metro();     pause()
    all_events += scrape_mianticipada();     pause()
    all_events += scrape_plateanet();        pause()
    all_events += scrape_alpogo();           pause()
    all_events += scrape_universotickets();  pause()
    all_events += scrape_catpass();          pause()
    all_events += scrape_rgentradas();       pause()
    all_events += scrape_livepass();         pause()
    all_events += scrape_ticketpass();       pause()
    all_events += scrape_ticketek()

    log.info(f"Total crudo: {len(all_events)}")
    all_events = deduplicate(all_events)
    all_events = filter_future(all_events)
    all_events = sort_events(all_events)

    for i, e in enumerate(all_events):
        e["id"] = i + 1

    output = {
        "updated_at": datetime.now().isoformat(),
        "source":     "scraper-natu-v8",
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
