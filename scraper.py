"""
La agenda de natu (extendida) — Scraper v10
=============================================
Fuentes verificadas con estructura real:

  HTML ESTÁTICO (requests):
    · Casa Metro         /cartelera/ — WooCommerce, li.product, h2, Fecha: DD/MM
    · Teatro Argentino   /meets/no-season — h5, DD/MM/YYYY HH:MM
    · LivePass           /taxons/* — a[href*/events/], h1/h3 título, h2 fecha
    · Alternativa Teatral cartelera.asp?ciudad=La+Plata — HTML con filtro ciudad

  JS / Playwright:
    · CatPass            catpass.net/eventos — article, sin filtro LP
    · Plateanet          search/-/-/La Plata — URL ya filtra, sin filtro LP
    · Alpogo             buscar?busqueda=la plata — [class*='evento'], filtro LP
    · Passline           home.passline.com — filtro LP en texto

  Playwright (funcionan bien, sin cambios):
    · Teatro Metro LP
    · MiAnticipada

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
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.com.ar/",
}

LP_KW = [
    "la plata", "berisso", "ensenada", "gonnet", "tolosa", "city bell",
    "villa elisa", "ringuelet",
    "teatro argentino", "estadio estudiantes", "estadio uno", "estadio único",
    "estadio unico", "estadio gimnasia", "coliseo podestá", "coliseo podesta",
    "pasaje dardo rocha", "casa metro", "teatro metro", "teatro ópera lp",
    "teatro opera lp", "hipódromo de la plata", "hipodromo de la plata",
    "anfiteatro martin fierro", "anfiteatro martín fierro",
    "quality espacio", "el galpón", "el galpon", "club atenas",
    "cine select", "centro cultural islas malvinas", "casa curutchet",
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
#  CASA METRO — /cartelera/ WooCommerce
#  Estructura real verificada:
#    <li class="product">
#      <img src="...-300x188.png"> (quitar sufijo tamaño)
#      **Fecha:** mayo 09, 2026
#      <h2> TÍTULO </h2>
#      <a href="/evento/slug">
# ══════════════════════════════════════════════════════════
def scrape_casa_metro():
    """
    Casa Metro — Playwright con URL exacta /cartelera/
    El HTML tiene li dentro de ul.products, cada uno con h2 título y Fecha: en texto.
    """
    events = []
    log.info("Casa Metro → scrapeando…")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage"]
            )
            ctx = browser.new_context(
                user_agent=HEADERS["User-Agent"], locale="es-AR",
                viewport={"width": 1280, "height": 900},
            )
            page = ctx.new_page()
            page.goto("https://casametro.com.ar/cartelera/",
                      timeout=30000, wait_until="domcontentloaded")
            time.sleep(3)
            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "html.parser")

        # WooCommerce: <ul class="products"> > <li>
        cards = soup.select("ul.products li")
        if not cards:
            # fallback: li que contenga link a /evento/
            all_li = [a.find_parent("li") for a in
                      soup.find_all("a", href=re.compile(r"/evento/"))]
            cards = list({id(c): c for c in all_li if c}.values())

        log.info(f"Casa Metro: {len(cards)} cards")
        seen = set()
        for card in cards:
            try:
                title_el = card.find("h2")
                title = title_el.get_text(strip=True) if title_el else ""
                if not title or len(title) < 3: continue

                link_el = card.find("a", href=re.compile(r"/evento/"))
                href = link_el["href"] if link_el else "https://casametro.com.ar/cartelera/"
                if href in seen: continue
                seen.add(href)

                block_text = card.get_text(" ", strip=True)
                img_el = card.find("img")
                flyer = ""
                if img_el:
                    flyer = img_el.get("src") or img_el.get("data-src") or ""
                    flyer = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", flyer)

                events.append(make_ev(
                    title, detect_cat(title),
                    parse_date(block_text), parse_time(block_text),
                    "Casa Metro La Plata", "Casa Metro", "casametro", href, flyer
                ))
            except Exception as e:
                log.debug(f"Casa Metro card: {e}")
    except Exception as e:
        log.error(f"Casa Metro: {e}")
    log.info(f"Casa Metro → {len(events)} eventos")
    return events


def scrape_livepass():
    """
    LivePass — HTML ESTÁTICO, no necesita Playwright.
    Estructura verificada en el HTML real:
      <a href="https://livepass.com.ar/events/SLUG">
        <img src="...thumbs/...">
        DD MES   ← texto antes del h1
        <h1> TÍTULO COMPLETO </h1>
      </a>
    Hay eventos duplicados (sección "Destacados" + sección "Eventos").
    Se deduplica por href.
    """
    events = []
    log.info("LivePass → scrapeando…")

    venue_pages = [
        ("https://livepass.com.ar/taxons/hipodromo-la-plata", "Hipódromo de La Plata"),
        ("https://livepass.com.ar/taxons/opera",              "Teatro Ópera LP"),
        ("https://livepass.com.ar/taxons/teatro-argentino",   "Teatro Argentino La Plata"),
    ]

    seen_hrefs = set()

    for url, default_venue in venue_pages:
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            log.info(f"LivePass: HTTP {r.status_code} — {url}")
            if r.status_code != 200:
                pause(1)
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            found = 0

            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                # Solo links de eventos individuales
                if "livepass.com.ar/events/" not in href:
                    continue
                if href in seen_hrefs:
                    continue
                seen_hrefs.add(href)

                try:
                    # Título: <h1> dentro del link
                    h1 = a.find("h1")
                    title = h1.get_text(strip=True) if h1 else ""
                    if not title or len(title) < 3:
                        continue

                    # Fecha: texto completo del link tipo "08 MAY\n# TÍTULO"
                    # extraemos todo el texto y buscamos patrón "DD MES"
                    full_text = a.get_text(" ", strip=True)
                    date_str = parse_date(full_text)

                    # Flyer
                    img_el = a.find("img")
                    flyer = img_el.get("src", "") if img_el else ""

                    events.append(make_ev(
                        title, detect_cat(title), date_str, "",
                        default_venue, "LivePass", "livepass", href, flyer
                    ))
                    found += 1
                except Exception as e:
                    log.debug(f"LivePass card: {e}")

            log.info(f"LivePass: {found} eventos en {default_venue}")
            pause(1)

        except Exception as e:
            log.error(f"LivePass {url}: {e}")

    log.info(f"LivePass → {len(events)} eventos")
    return events


# ══════════════════════════════════════════════════════════
#  TEATRO ARGENTINO — HTML estático, funciona bien
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
#  LIVEPASS — HTML estático por páginas de venue
#  Estructura verificada:
#    <a href="https://livepass.com.ar/events/SLUG">
#      <h1> NOMBRE COMPLETO </h1>
#      <h3> nombre corto </h3>
#      <h2> DD MES (fecha sin año) </h2>
#      <img src="..."> flyer
# ══════════════════════════════════════════════════════════
def scrape_alternativa_teatral():
    """
    Alternativa Teatral — Playwright porque es una SPA.
    Filtramos directamente con el parámetro ciudad=La+Plata en la URL.
    Estructura: lista de espectáculos con nombre, teatro y horarios.
    """
    events = []
    log.info("Alternativa Teatral → scrapeando…")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("Alternativa Teatral: Playwright no instalado.")
        return events

    BASE = "https://www.alternativateatral.com"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage"]
        )
        ctx = browser.new_context(
            user_agent=HEADERS["User-Agent"], locale="es-AR",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()

        urls = [
            f"{BASE}/cartelera.asp?ciudad=La+Plata",
            f"{BASE}/cartelera.asp?prov=2&ciudad=La+Plata",
            f"{BASE}/cartelera.asp",
        ]

        for url in urls:
            try:
                page.goto(url, timeout=35000, wait_until="domcontentloaded")
                time.sleep(3)
                # Scroll para cargar lazy content
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2)

                html = page.content()
                soup = BeautifulSoup(html, "html.parser")

                # Alternativa Teatral: lista con links a /obra_NNNNN
                # Cada espectáculo tiene el nombre en el link y el teatro debajo
                obra_links = soup.find_all("a", href=re.compile(r"/obra_\d+"))
                log.info(f"Alternativa Teatral: {len(obra_links)} links en {url}")

                for a in obra_links:
                    try:
                        title = a.get_text(strip=True)
                        if not title or len(title) < 3: continue

                        parent = a.find_parent(["tr","li","div","td"])
                        block_text = parent.get_text(" ") if parent else ""

                        # Filtrar por La Plata si la URL no filtra
                        if "ciudad=La" not in url and not is_lp(block_text):
                            continue

                        href = a["href"]
                        if not href.startswith("http"):
                            href = BASE + href

                        events.append(make_ev(
                            title, "teatro",
                            parse_date(block_text), parse_time(block_text),
                            "", "Alternativa Teatral", "alternativateatral",
                            href, ""
                        ))
                    except Exception as e:
                        log.debug(f"Alternativa Teatral link: {e}")

                if events: break
                pause(1)

            except Exception as e:
                log.error(f"Alternativa Teatral {url}: {e}")

        browser.close()

    log.info(f"Alternativa Teatral → {len(events)} eventos")
    return events


# ══════════════════════════════════════════════════════════
#  PLAYWRIGHT BASE — para sitios JS
# ══════════════════════════════════════════════════════════
def playwright_scrape(name, source_key, urls,
                      filter_lp=True, extra_wait=0, venue_default="",
                      preferred_selector=None, trust_url_filter=False):
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
            url_filters_lp = trust_url_filter and any(
                x in url.lower() for x in ["la-plata","la+plata","la%20plata","laplata"]
            )
            apply_lp_filter = filter_lp and not url_filters_lp

            try:
                page.goto(url, timeout=45000, wait_until="domcontentloaded")

                for sel in ["article","h2","h3","[class*='card']",
                             "[class*='event']","[class*='show']",
                             "[class*='evento']","main img"]:
                    try:
                        page.wait_for_selector(sel, timeout=12000)
                        break
                    except Exception:
                        continue

                time.sleep(2 + extra_wait)

                # Scroll para lazy-load
                total = page.evaluate("document.body.scrollHeight")
                for pos in range(0, min(total, 8000), 500):
                    page.evaluate(f"window.scrollTo(0, {pos})")
                    time.sleep(0.2)
                page.evaluate("window.scrollTo(0, 0)")
                time.sleep(1)

                html = page.content()
                soup = BeautifulSoup(html, "html.parser")

                # Selectores a probar
                selector_list = []
                if preferred_selector:
                    for s in preferred_selector.split(","):
                        selector_list.append(s.strip())
                selector_list += [
                    "article",
                    "[class*='card']",
                    "[class*='evento']",
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
                        if len(found) >= 2 and len(found) < 300:
                            log.info(f"{name}: {len(found)} cards con '{sel}'")
                            cards = found
                            break
                        elif len(found) == 1 and name in ("Alpogo","CatPass","Plateanet"):
                            # Para fuentes pequeñas aceptar 1 resultado
                            log.info(f"{name}: {len(found)} card con '{sel}'")
                            cards = found
                            break
                    except Exception:
                        continue

                # Búsqueda estructural genérica
                if not cards:
                    log.info(f"{name}: búsqueda estructural genérica")
                    candidates = []
                    for el in soup.find_all(["div","li","article"]):
                        if (el.find("a", href=True) and el.find("img")
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


# ══════════════════════════════════════════════════════════
#  TICKETERAS JS
# ══════════════════════════════════════════════════════════

def scrape_teatro_metro():
    """Funciona bien — sin cambios."""
    return playwright_scrape("Teatro Metro LP","teatrometrolp",
        ["https://www.teatrometrolp.com.ar/entradas/cartelera/"],
        filter_lp=False, extra_wait=3, venue_default="Teatro Metro LP")

def scrape_mianticipada():
    """Funciona bien — sin cambios."""
    return playwright_scrape("MiAnticipada","mianticipada",
        ["https://mianticipada.com/La-Plata/",
         "https://mianticipada.com/?ciudad=la-plata"],
        filter_lp=True, extra_wait=2,
        preferred_selector="[class*='card']")

def scrape_catpass():
    """Sin filtro LP — todos los eventos de la plataforma son de La Plata."""
    return playwright_scrape("CatPass","catpass",
        ["https://catpass.net/eventos"],
        filter_lp=False, extra_wait=3,
        preferred_selector="article")

def scrape_plateanet():
    """Sin filtro LP — URL ya filtra por La Plata."""
    return playwright_scrape("Plateanet","plateanet",
        ["https://www.plateanet.com/search/-/-/La%20Plata/-/-/-/-"],
        filter_lp=False, extra_wait=4,
        preferred_selector="[class*='card'],[class*='show'],[class*='espectaculo'],article")

def scrape_alpogo():
    """URL correcta verificada: buscar?busqueda=la plata. Filtro LP activo."""
    return playwright_scrape("Alpogo","alpogo",
        ["https://alpogo.com/buscar?busqueda=la%20plata"],
        filter_lp=True, extra_wait=3,
        preferred_selector="[class*='evento']")

def scrape_passline():
    """
    Passline — home.passline.com con filtro por comuna La Plata (26324).
    Necesita Playwright, filtro LP activo como seguridad adicional.
    """
    return playwright_scrape("Passline","passline",
        [
            "https://home.passline.com/eventos.php?q=&catS=&region=1&comuna=26324&mes=&pais=argentina&page=1",
            "https://www.passline.com/eventos?ciudad=la-plata",
            "https://www.passline.com/buscar?q=la+plata",
        ],
        filter_lp=True, extra_wait=5,
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
    # ISO: 2025-06-14
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m: return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # DD/MM/YYYY
    m = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", raw)
    if m: return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    # "mayo 09, 2026" / "May 9, 2026"
    m = re.search(r"([a-zA-ZáéíóúÁÉÍÓÚ]+)\s+(\d{1,2}),?\s+(\d{4})", raw)
    if m:
        mes = MESES.get(m.group(1).lower()[:3],"")
        if mes: return f"{m.group(3)}-{mes}-{m.group(2).zfill(2)}"
    # "14 de junio de 2025" / "14 junio 2025"
    m = re.search(
        r"(\d{1,2})\s+(?:de\s+)?([a-zA-ZáéíóúÁÉÍÓÚ]+)\s+(?:de\s+)?(\d{4})", raw)
    if m:
        mes = MESES.get(m.group(2).lower()[:3], MESES.get(m.group(2).lower(),""))
        if mes: return f"{m.group(3)}-{mes}-{m.group(1).zfill(2)}"
    # "09 MAY" (sin año) → asumir año actual o próximo
    m = re.search(r"(\d{1,2})\s+([A-Za-záéíóú]{3,})\b", raw)
    if m:
        mes = MESES.get(m.group(2).lower()[:3],"")
        if mes:
            year = datetime.now().year
            day = int(m.group(1))
            month = int(mes)
            # Si la fecha ya pasó, asumir próximo año
            try:
                candidate = datetime(year, month, day)
                if candidate < datetime.now():
                    year += 1
            except Exception:
                pass
            return f"{year}-{mes}-{m.group(1).zfill(2)}"
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
    log.info("  La agenda de natu (extendida) — v12")
    log.info("══════════════════════════════════════════")
    t0 = time.time()

    all_events = []

    # HTML estático / rápido
    all_events += scrape_casa_metro();           pause()
    all_events += scrape_teatro_argentino();     pause()
    all_events += scrape_livepass();             pause()

    # Playwright
    all_events += scrape_teatro_metro();         pause()
    all_events += scrape_mianticipada();         pause()
    all_events += scrape_alternativa_teatral();  pause()
    all_events += scrape_catpass();              pause()
    all_events += scrape_plateanet();            pause()
    all_events += scrape_alpogo();               pause()
    all_events += scrape_passline()

    log.info(f"Total crudo: {len(all_events)}")
    all_events = deduplicate(all_events)
    all_events = filter_future(all_events)
    all_events = sort_events(all_events)

    for i, e in enumerate(all_events):
        e["id"] = i + 1

    output = {
        "updated_at": datetime.now().isoformat(),
        "source":     "scraper-natu-v10",
        "city":       "La Plata",
        "total":      len(all_events),
        "events":     all_events,
    }

    out = Path(__file__).parent / "shows.json"
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    counts = Counter(e["sourceKey"] for e in all_events)
    log.info(f"✓ {len(all_events)} eventos en {time.time()-t0:.1f}s")
    for src, n in sorted(counts.items(), key=lambda x: -x[1]):
        log.info(f"   {src:<25} {n} eventos")


if __name__ == "__main__":
    main()
